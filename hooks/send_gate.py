#!/usr/bin/env -S python3 -I -S
"""PreToolUse(Bash) gate for `jm send` (jadlis-mail).

The canonical command alone — `jm send D<n> --hash <hex>`, optionally with a path to jm — gets a one-time
ticket in ~/.claude/jadlis/mail/tickets/<code>.json and the decision "ask", so Claude Code shows the owner that
exact command (also in bypassPermissions mode, and on the phone through Remote Control). `jm send` refuses to
send without a fresh ticket for the same code and hash and consumes it.

Any other Bash call of the same session voids that session's open tickets. So a send written in any other form —
inside a compound command, through bash -c, with an env prefix, quoted — finds no ticket: either the ticket was
voided by that very call's hook, or it never existed. Sending without the prompt needs a deliberately forged
ticket; this gate stops a misled model, not a hostile one (references/security.md).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

TICKETS = Path.home() / ".claude" / "jadlis" / "mail" / "tickets"
CANON = re.compile(r"\A[ \t]*(?:[A-Za-z0-9_.~/-]*/)?jm[ \t]+send[ \t]+(D\d{1,5})[ \t]+--hash[ \t]+([0-9a-f]{10,64})[ \t]*\Z")


def void(session):
    if not TICKETS.is_dir():
        return
    for p in TICKETS.glob("*.json"):
        try:
            t = json.loads(p.read_text())
        except (OSError, ValueError):
            t = {}
        if not session or t.get("session") in (None, session) or time.time() - float(t.get("ts", 0)) > 900:
            try:
                p.unlink()
            except OSError:
                pass


def main():
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    session = data.get("session_id")
    m = CANON.match(cmd)
    if not m:
        void(session)
        return 0
    code, digest = m.groups()
    TICKETS.mkdir(parents=True, exist_ok=True)
    tmp = TICKETS / f".{code}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"code": code, "hash": digest, "ts": time.time(), "session": session}, f)
    os.replace(tmp, TICKETS / f"{code}.json")
    reason = (f"Отправить письмо {code}? Уйдёт ровно та версия черновика, которую ты видел (hash {digest}). "
              "Нет — отправка не произойдёт.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
