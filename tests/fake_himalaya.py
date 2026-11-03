#!/usr/bin/env python3
"""Fake himalaya 2.2.1 for the jadlis-mail tests — only the calls jm makes, with the JSON shapes of
skills/mail/references/cookbook.md.

IMAP state lives in the JSON file named by FAKE_HIM_STATE:
  {"accounts": {"<name>": {"mode": {"move_noop": bool}, "capabilities": [...], "sent_out": [...],
                           "mailboxes": {"<name>": {"attributes": [...], "uidvalidity": n, "uidnext": n,
                                                    "messages": [{"uid", "raw_b64", "flags", "internal_date"}]}}}}}
Every call appends one JSON line to FAKE_HIM_LOG: argv and the JM_SECRET_* variables it saw (with values).

Honest on purpose: `imap move` replies success even for a UID that does not exist (himalaya #777), and in
mode move_noop it replies success without moving anything; `n:*` above the highest UID returns the highest
message, like real IMAP. Errors print {"error", "sources", "backtrace"} on stdout and exit 1.
"""
import base64
import datetime as dt
import email
import email.policy
import email.utils
import json
import os
import re
import sys


class Fail(Exception):
    pass


def utf7_decode(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "&":
            j = s.index("-", i)
            if j == i + 1:
                out.append("&")
            else:
                b = s[i + 1:j].replace(",", "/")
                b += "=" * (-len(b) % 4)
                out.append(base64.b64decode(b).decode("utf-16-be"))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def raw_of(m):
    return base64.b64decode(m["raw_b64"])


def parsed(m):
    return email.message_from_bytes(raw_of(m), policy=email.policy.default)


def header(msg, name):
    v = msg.get(name)
    return str(v) if v is not None else ""


def addr_list(value):
    out = []
    for name, addr in email.utils.getaddresses([value or ""]):
        if addr:
            out.append(f"{name} <{addr}>" if name else addr)
    return out


def find_box(acct, name, selectable=True):
    for n, b in acct["mailboxes"].items():
        if n == name or (n.upper() == "INBOX" and name.upper() == "INBOX"):
            if selectable and any(a.lower() == "\\noselect" for a in b["attributes"]):
                break
            return n, b
    raise Fail("IMAP SELECT failed: NO no such mailbox")


def sorted_msgs(box):
    return sorted(box["messages"], key=lambda m: m["uid"])


def parse_set(spec, box):
    uids = [m["uid"] for m in sorted_msgs(box)]
    mx = uids[-1] if uids else 0
    hit = set()
    for part in spec.split(","):
        if ":" in part:
            lo, hi = part.split(":", 1)
            lo = mx if lo == "*" else int(lo)
            hi = mx if hi == "*" else int(hi)
            if lo > hi:
                lo, hi = hi, lo
            hit.update(u for u in uids if lo <= u <= hi)
        else:
            u = mx if part == "*" else int(part)
            if u in uids:
                hit.add(u)
    return sorted(hit)


def add_message(box, raw, flags, internal_date=None):
    uid = box["uidnext"]
    box["uidnext"] += 1
    box["messages"].append({"uid": uid, "raw_b64": base64.b64encode(raw).decode(), "flags": list(flags),
                            "internal_date": internal_date or dt.datetime.now(dt.timezone.utc)
                            .isoformat(timespec="seconds")})
    return uid


def has_flag(m, flag):
    return flag.lower() in (f.lower() for f in m["flags"])


def envelope(m):
    msg = parsed(m)
    return {"date": header(msg, "Date"), "subject": header(msg, "Subject"),
            "message_id": header(msg, "Message-ID") or None, "in_reply_to": header(msg, "In-Reply-To") or None,
            "from": addr_list(header(msg, "From")), "sender": addr_list(header(msg, "Sender") or header(msg, "From")),
            "reply_to": addr_list(header(msg, "Reply-To") or header(msg, "From")),
            "to": addr_list(header(msg, "To")), "cc": addr_list(header(msg, "Cc")), "bcc": addr_list(header(msg, "Bcc"))}


def opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        return args[i + 1]
    return default


# ------------------------------------------------------------------ commands

def imap_list(acct, args):
    return {"mailboxes": [{"name": n, "delimiter": "/", "attributes": b["attributes"]}
                          for n, b in acct["mailboxes"].items()]}


def imap_status(acct, args):
    _, b = find_box(acct, args[0])
    return {"messages": len(b["messages"]), "recent": 0, "uid_next": b["uidnext"], "uid_validity": b["uidvalidity"],
            "unseen": sum(1 for m in b["messages"] if not has_flag(m, "\\Seen")), "deleted": None,
            "deleted_storage": None, "highest_mod_seq": None}


def _text_of(msg):
    parts = []
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                parts.append(part.get_content())
            except Exception:
                pass
    return "\n".join(parts)


def imap_search(acct, args):
    _, b = find_box(acct, opt(args, "-m"))
    since, before = opt(args, "--since"), opt(args, "--before")
    ids = []
    for m in sorted_msgs(b):
        msg = parsed(m)
        day = dt.datetime.fromisoformat(m["internal_date"]).astimezone(dt.timezone.utc).date().isoformat()
        if since and day < since:
            continue
        if before and day >= before:
            continue
        ok = True
        for flag, hname in (("--from", "From"), ("--to", "To"), ("--subject", "Subject")):
            val = opt(args, flag)
            if val is not None and val.lower() not in header(msg, hname).lower():
                ok = False
        val = opt(args, "--text")
        if val is not None and val.lower() not in (str(msg) + "\n" + _text_of(msg)).lower():
            ok = False
        if "--unseen" in args and has_flag(m, "\\Seen"):
            ok = False
        if "--flagged" in args and not has_flag(m, "\\Flagged"):
            ok = False
        if "--seen" in args and not has_flag(m, "\\Seen"):
            ok = False
        if "--unflagged" in args and has_flag(m, "\\Flagged"):
            ok = False
        if ok:
            ids.append({"id": m["uid"]})
    return {"uid_mode": True, "ids": ids}


def imap_fetch(acct, args):
    _, b = find_box(acct, opt(args, "-m"))
    spec = args[-1]
    want = {k: k in args for k in ("--envelope", "--flags", "--internal-date", "--size", "--body")}
    msgs = sorted_msgs(b)
    seq = {m["uid"]: i for i, m in enumerate(msgs, 1)}
    by_uid = {m["uid"]: m for m in msgs}
    out = []
    for uid in parse_set(spec, b):
        m = by_uid[uid]
        out.append({"seq": seq[uid], "uid": uid,
                    "flags": list(m["flags"]) if want["--flags"] else None,
                    "internal_date": m["internal_date"] if want["--internal-date"] else None,
                    "size": len(raw_of(m)) if want["--size"] else None,
                    "envelope": envelope(m) if want["--envelope"] else None, "structure": None,
                    "body": m["raw_b64"] if want["--body"] else None})
    return {"messages": out}


def imap_store(acct, args):
    spec = args[0]
    _, b = find_box(acct, opt(args, "-m"))
    action, flag = opt(args, "--action"), opt(args, "--flag")
    uids = set(parse_set(spec, b))
    for m in b["messages"]:
        if m["uid"] in uids:
            if action == "add" and not has_flag(m, flag):
                m["flags"].append(flag)
            elif action == "remove":
                m["flags"] = [f for f in m["flags"] if f.lower() != flag.lower()]
    return {"message": "Flag(s) successfully updated"}


def imap_move(acct, args):
    i = args.index("-m")
    src_name = args[i + 1]
    rest = args[:i] + args[i + 2:]
    spec, target = rest[0], rest[1]
    _, src = find_box(acct, src_name)
    _, dst = find_box(acct, target)
    if not acct.get("mode", {}).get("move_noop"):
        uids = set(parse_set(spec, src))
        moving = [m for m in sorted_msgs(src) if m["uid"] in uids]
        src["messages"] = [m for m in src["messages"] if m["uid"] not in uids]
        for m in moving:
            add_message(dst, raw_of(m), m["flags"], m["internal_date"])
    return {"message": "Message(s) successfully moved"}


def imap_copy(acct, args):
    i = args.index("-m")
    src_name = args[i + 1]
    rest = args[:i] + args[i + 2:]
    spec, target = rest[0], rest[1]
    _, src = find_box(acct, src_name)
    _, dst = find_box(acct, target)
    if not acct.get("mode", {}).get("move_noop"):
        uids = set(parse_set(spec, src))
        for m in [m for m in sorted_msgs(src) if m["uid"] in uids]:
            add_message(dst, raw_of(m), list(m["flags"]), m["internal_date"])
    return {"message": "Message(s) successfully copied"}


def imap_append(acct, args, stdin):
    name = args[0]
    _, b = find_box(acct, name)
    flags = [args[i + 1] for i, a in enumerate(args) if a == "--flag"]
    add_message(b, stdin, flags)
    return {"message": "Message successfully added"}


def imap_create(acct, args):
    name = args[0]
    if name in acct["mailboxes"]:
        raise Fail("IMAP CREATE failed: NO mailbox already exists")
    uv = max([b["uidvalidity"] for b in acct["mailboxes"].values()] + [0]) + 1
    acct["mailboxes"][name] = {"attributes": [], "uidvalidity": uv, "uidnext": 1, "messages": []}
    return {"message": "Mailbox successfully created"}


def imap_raw(acct, stdin):
    text = stdin.decode("utf-8")
    lines, selected, readonly = [], None, True
    for line in text.split("\r\n"):
        if not line:
            continue
        tag, _, rest = line.partition(" ")
        up = rest.upper()
        m = re.match(r'^(EXAMINE|SELECT) "(.*)"$', rest, re.I)
        if up == "CAPABILITY":
            lines.append("* CAPABILITY " + " ".join(acct.get("capabilities", ["IMAP4rev1"])))
            lines.append(f"{tag} OK CAPABILITY completed")
        elif m:
            try:
                name, box = find_box(acct, utf7_decode(m.group(2)))
            except Fail:
                selected = None
                lines.append(f"{tag} NO Mailbox doesn't exist")
                continue
            selected, readonly = box, m.group(1).upper() == "EXAMINE"
            lines += [f"* {len(box['messages'])} EXISTS", f"* OK [UIDVALIDITY {box['uidvalidity']}] UIDs valid",
                      f"* OK [UIDNEXT {box['uidnext']}] Predicted next UID"]
            lines.append(f"{tag} OK [{'READ-ONLY' if readonly else 'READ-WRITE'}] {m.group(1).upper()} completed")
        elif selected is None:
            lines.append(f"{tag} BAD No mailbox selected")
        elif re.match(r'^UID SEARCH HEADER Message-ID "(.*)"$', rest, re.I):
            want = re.match(r'^UID SEARCH HEADER Message-ID "(.*)"$', rest, re.I).group(1).lower()
            hits = [str(x["uid"]) for x in sorted_msgs(selected)
                    if want in header(parsed(x), "Message-ID").lower()]
            lines += [("* SEARCH " + " ".join(hits)).rstrip(), f"{tag} OK SEARCH completed"]
        elif re.match(r'^UID SEARCH OR TO "(.*)" CC "(.*)"$', rest, re.I):
            g = re.match(r'^UID SEARCH OR TO "(.*)" CC "(.*)"$', rest, re.I)
            hits = [str(x["uid"]) for x in sorted_msgs(selected)
                    if g.group(1).lower() in header(parsed(x), "To").lower()
                    or g.group(2).lower() in header(parsed(x), "Cc").lower()]
            lines += [("* SEARCH " + " ".join(hits)).rstrip(), f"{tag} OK SEARCH completed"]
        elif re.match(r"^UID STORE ([\d,]+) \+FLAGS(?:\.SILENT)? \((.*)\)$", rest, re.I):
            g = re.match(r"^UID STORE ([\d,]+) \+FLAGS(?:\.SILENT)? \((.*)\)$", rest, re.I)
            if readonly:
                lines.append(f"{tag} NO Mailbox is read-only")
                continue
            uidset = {int(u) for u in g.group(1).split(",")}
            msgs = sorted_msgs(selected)
            for i, x in enumerate(msgs, 1):
                if x["uid"] in uidset:
                    for f in g.group(2).split():
                        if not has_flag(x, f):
                            x["flags"].append(f)
                    lines.append(f"* {i} FETCH (UID {x['uid']} FLAGS ({' '.join(x['flags'])}))")
            lines.append(f"{tag} OK STORE completed")
        elif re.match(r"^UID EXPUNGE ([\d,]+)$", rest, re.I):
            if readonly:
                lines.append(f"{tag} NO Mailbox is read-only")
                continue
            uidset = {int(u) for u in re.match(r"^UID EXPUNGE ([\d,]+)$", rest, re.I).group(1).split(",")}
            msgs = sorted_msgs(selected)
            gone = [(i, x) for i, x in enumerate(msgs, 1) if x["uid"] in uidset and has_flag(x, "\\Deleted")]
            for i, x in reversed(gone):
                lines.append(f"* {i} EXPUNGE")
            selected["messages"] = [x for x in selected["messages"] if all(x is not g2 for _, g2 in gone)]
            lines.append(f"{tag} OK EXPUNGE completed")
        else:
            lines.append(f"{tag} BAD Unknown command")
    return {"message": "\r\n".join(lines) + "\r\n"}


def message_send(acct, args, stdin):
    save = opt(args, "--save")
    if save:
        _, b = find_box(acct, save)
        add_message(b, stdin, ["\\Seen"])
    acct.setdefault("sent_out", []).append({"raw_b64": base64.b64encode(stdin).decode(), "save": save})
    return {"message": "Message successfully sent"}


def dispatch(acct, cmd, stdin):
    if cmd[:2] == ["imap", "list"]:
        return imap_list(acct, cmd[2:])
    if cmd[:2] == ["imap", "status"]:
        return imap_status(acct, cmd[2:])
    if cmd[:2] == ["imap", "search"]:
        return imap_search(acct, cmd[2:])
    if cmd[:2] == ["imap", "fetch"]:
        return imap_fetch(acct, cmd[2:])
    if cmd[:2] == ["imap", "store"]:
        return imap_store(acct, cmd[2:])
    if cmd[:2] == ["imap", "move"]:
        return imap_move(acct, cmd[2:])
    if cmd[:2] == ["imap", "copy"]:
        return imap_copy(acct, cmd[2:])
    if cmd[:2] == ["imap", "append"]:
        return imap_append(acct, cmd[2:], stdin)
    if cmd[:2] == ["imap", "create"]:
        return imap_create(acct, cmd[2:])
    if cmd[:2] == ["imap", "raw"]:
        return imap_raw(acct, stdin)
    if cmd[:2] == ["message", "send"]:
        return message_send(acct, cmd[2:], stdin)
    raise Fail(f"fake himalaya does not know: {' '.join(cmd[:3])}")


def main():
    argv = sys.argv[1:]
    with open(os.environ["FAKE_HIM_LOG"], "a") as f:
        f.write(json.dumps({"argv": argv, "secrets": {k: v for k, v in os.environ.items()
                                                      if k.startswith("JM_SECRET_")}}, ensure_ascii=False) + "\n")
    i, acct_name = 0, None
    while i < len(argv):
        a = argv[i]
        if a in ("-c", "--log-level"):
            i += 2
        elif a == "-a":
            acct_name = argv[i + 1]
            i += 2
        elif a == "--json":
            i += 1
        else:
            break
    cmd = argv[i:]
    stdin = sys.stdin.buffer.read()
    path = os.environ["FAKE_HIM_STATE"]
    with open(path) as f:
        state = json.load(f)
    try:
        acct = state["accounts"].get(acct_name)
        if acct is None:
            raise Fail(f"cannot find account {acct_name}")
        result = dispatch(acct, cmd, stdin)
    except (Fail, ValueError, IndexError, KeyError) as e:
        sys.stdout.write(json.dumps({"error": str(e), "sources": [], "backtrace": None}))
        return 1
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
