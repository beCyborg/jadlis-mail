"""Shared fixtures for the jadlis-mail tests: jm loaded as a module with every path patched into tmp, a fake
himalaya (tests/fake_himalaya.py) behind jm's real subprocess path, and a fake secret command that prints a
per-account canary. Nothing here touches ~/.claude/jadlis/mail, ~/.config/himalaya, the network or a mailbox."""
import base64
import datetime as dt
import email
import email.policy
import email.utils
import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time
import uuid
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JM_PATH = ROOT / "scripts" / "jm"
GATE_PATH = ROOT / "hooks" / "send_gate.py"
FAKE_HIMALAYA = Path(__file__).resolve().parent / "fake_himalaya.py"
CANARY = "canary-SECRET-4711"

SECRET_SCRIPT = f"""#!/usr/bin/env python3
import json, os, sys
acct = sys.argv[1]
log = os.environ.get("FAKE_SECRET_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({{"acct": acct, "env": dict(os.environ)}}) + "\\n")
print("{CANARY}-" + acct)
"""


def load_jm():
    loader = importlib.machinery.SourceFileLoader("jm", str(JM_PATH))
    spec = importlib.util.spec_from_loader("jm", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _box(attrs, uv):
    return {"attributes": attrs, "uidvalidity": uv, "uidnext": 1, "messages": []}


def gmail_boxes(base):
    return {"INBOX": _box(["\\HasNoChildren"], base + 1),
            "[Gmail]": _box(["\\HasChildren", "\\Noselect"], base + 2),
            "[Gmail]/Вся почта": _box(["\\All", "\\HasNoChildren"], base + 3),
            "[Gmail]/Спам": _box(["\\Junk", "\\HasNoChildren"], base + 4),
            "[Gmail]/Отправленные": _box(["\\Sent", "\\HasNoChildren"], base + 5),
            "[Gmail]/Черновики": _box(["\\Drafts", "\\HasNoChildren"], base + 6),
            "[Gmail]/Корзина": _box(["\\Trash", "\\HasNoChildren"], base + 7),
            "[Gmail]/Помеченные": _box(["\\Flagged", "\\HasNoChildren"], base + 8),
            "Рассылки": _box(["\\HasNoChildren"], base + 9),
            "Уведомления": _box(["\\HasNoChildren"], base + 10)}


def proton_boxes(base):
    return {"Inbox": _box([], base + 1), "Spam": _box(["\\Junk"], base + 2), "Sent": _box(["\\Sent"], base + 3),
            "Drafts": _box(["\\Drafts"], base + 4), "Trash": _box(["\\Trash"], base + 5),
            "All Mail": _box(["\\All"], base + 6), "Archive": _box(["\\Archive"], base + 7),
            "Starred": _box(["\\Flagged"], base + 8), "Folders": _box(["\\Noselect"], base + 9),
            "Folders/Рассылки": _box([], base + 10), "Folders/Уведомления": _box([], base + 11)}


def icloud_boxes(base):
    return {"INBOX": _box([], base + 1), "Junk": _box(["\\Junk"], base + 2),
            "Sent Messages": _box(["\\Sent"], base + 3), "Drafts": _box(["\\Drafts"], base + 4),
            "Deleted Messages": _box(["\\Trash"], base + 5), "Archive": _box(["\\Archive"], base + 6),
            "Рассылки": _box([], base + 7), "Уведомления": _box([], base + 8)}


CAPS = ["IMAP4rev1", "MOVE", "UIDPLUS", "IDLE", "NAMESPACE"]


class MailEnv:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.capsys = capsys
        self.root = tmp_path
        self.home = tmp_path / "home"
        self.state = self.home / ".claude" / "jadlis" / "mail"
        self.fake = tmp_path / "fake"
        self.fake.mkdir(parents=True)
        self.state.mkdir(parents=True)
        self.fake_state = self.fake / "imap.json"
        self.fake_log = self.fake / "himalaya-calls.jsonl"
        self.secret_log = self.fake / "secret-env.jsonl"
        self.secret_cmd = self.fake / "fake_secret.py"
        self.secret_cmd.write_text(SECRET_SCRIPT)
        self.secret_cmd.chmod(self.secret_cmd.stat().st_mode | stat.S_IXUSR)
        FAKE_HIMALAYA.chmod(FAKE_HIMALAYA.stat().st_mode | stat.S_IXUSR)
        self.session = "sess-" + uuid.uuid4().hex[:8]
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("FAKE_HIM_STATE", str(self.fake_state))
        monkeypatch.setenv("FAKE_HIM_LOG", str(self.fake_log))
        monkeypatch.setenv("FAKE_SECRET_LOG", str(self.secret_log))
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.session)
        self.t0 = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.offset = dt.timedelta(0)
        self.jm = self.load()
        self.write_config()
        self.write_imap({"accounts": {
            "gmail-01": {"mode": {}, "capabilities": CAPS, "mailboxes": gmail_boxes(100), "sent_out": []},
            "gmail-sp": {"mode": {}, "capabilities": CAPS, "mailboxes": gmail_boxes(200), "sent_out": []},
            "proton": {"mode": {}, "capabilities": CAPS, "mailboxes": proton_boxes(300), "sent_out": []},
            "icloud": {"mode": {}, "capabilities": CAPS, "mailboxes": icloud_boxes(400), "sent_out": []},
        }})

    # ---------------------------------------------------------------- jm
    def load(self):
        jm = load_jm()
        hconf = self.home / ".config" / "himalaya"
        jm.STATE = self.state
        jm.HCONF = hconf
        jm.BASE_TOML = hconf / "config.toml"
        jm.PERSONAL_TOML = hconf / "personal.toml"
        jm.SEND_TOML = hconf / "send.toml"
        jm.HIMALAYA = str(FAKE_HIMALAYA)
        jm.bridge_up = lambda: True
        jm.ensure_bridge = lambda: None
        jm.now = lambda: self.t0 + self.offset
        return jm

    def write_config(self, **over):
        def acct(short, provider, mail, folders, **kw):
            return {"enabled": True, "short": short, "provider": provider, "email": mail,
                    "display_name": "Owner", "secret": [str(self.secret_cmd), None], "track": ["inbox", "spam"],
                    "folders": folders, "save_sent": False, **kw}
        ru = {"newsletters": "Рассылки", "notifications": "Уведомления"}
        cfg = {"accounts": {
            "icloud": acct("ic", "icloud", "owner@icloud.example", ru, aliases=["owner.alias@icloud.example"],  # privacy-ok: RFC 2606 fixture
                           save_sent=True),
            "gmail-sp": acct("gs", "gmail", "bank.owner@gmail.example", ru, digest_senders=True),  # privacy-ok: RFC 2606 fixture
            "gmail-01": acct("g1", "gmail", "owner.g1@gmail.example", ru),  # privacy-ok: RFC 2606 fixture
            "proton": acct("pm", "proton", "owner@proton.example", {"newsletters": "Folders/Рассылки",  # privacy-ok: RFC 2606 fixture
                                                            "notifications": "Folders/Уведомления"}),
        },
            "protected": {"domains": ["corp.example"], "addresses": [], "recipient_locals": ["contact", "agent-*"],
                          "subject_words": ["CORP"]},
            "vip": ["boss@vip.example"],  # privacy-ok: RFC 2606 fixture
            "rules": []}
        for name, a in cfg["accounts"].items():
            a["secret"][1] = name
        cfg.update(over)
        (self.state / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))

    def run(self, *args):
        """jm.main(args) → (rc, parsed JSON stdout). Each call advances the clock one second."""
        self.offset += dt.timedelta(seconds=1)
        self.capsys.readouterr()
        rc = self.jm.main([str(a) for a in args])
        out = self.capsys.readouterr().out
        return rc, (json.loads(out) if out.strip() else None)

    def advance(self, minutes):
        self.offset += dt.timedelta(minutes=minutes)

    # ---------------------------------------------------------------- fake IMAP state
    def imap(self):
        return json.loads(self.fake_state.read_text())

    def write_imap(self, data):
        self.fake_state.write_text(json.dumps(data, ensure_ascii=False, indent=1))

    def box(self, acct, mbox):
        return self.imap()["accounts"][acct]["mailboxes"][mbox]

    def add_msg(self, acct, mbox, *, frm, to, subject="Hello", age_min=40, body="Hello there", cc=None,
                headers=None, flags=(), mid=None):
        mid = mid or f"<{uuid.uuid4().hex}@sender.example>"
        received = self.t0 - dt.timedelta(minutes=age_min)
        m = EmailMessage()
        m["From"] = frm
        m["To"] = to
        if cc:
            m["Cc"] = cc
        m["Subject"] = subject
        m["Date"] = email.utils.format_datetime(received)
        m["Message-ID"] = mid
        for k, v in (headers or {}).items():
            m[k] = v
        m.set_content(body)
        raw = m.as_bytes(policy=email.policy.SMTP)
        data = self.imap()
        b = data["accounts"][acct]["mailboxes"][mbox]
        b["messages"].append({"uid": b["uidnext"], "raw_b64": base64.b64encode(raw).decode(), "flags": list(flags),
                              "internal_date": received.isoformat(timespec="seconds")})
        b["uidnext"] += 1
        self.write_imap(data)
        return mid

    def messages(self, acct, mbox):
        out = []
        for m in self.box(acct, mbox)["messages"]:
            raw = base64.b64decode(m["raw_b64"])
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            out.append({"uid": m["uid"], "mid": str(msg["Message-ID"] or ""), "flags": m["flags"], "raw": raw})
        return out

    def mids(self, acct, mbox):
        return [m["mid"] for m in self.messages(acct, mbox)]

    def flags_of(self, acct, mbox, mid):
        for m in self.messages(acct, mbox):
            if m["mid"] == mid:
                return set(m["flags"])
        raise AssertionError(f"{mid} not in {acct}/{mbox}")

    def set_mode(self, acct, **mode):
        data = self.imap()
        data["accounts"][acct]["mode"].update(mode)
        self.write_imap(data)

    def mutate(self, fn):
        data = self.imap()
        fn(data)
        self.write_imap(data)

    def calls(self):
        rows = []
        if self.fake_log.exists():
            for line in self.fake_log.read_text().splitlines():
                rows.append(json.loads(line))
        return rows

    @staticmethod
    def command(call):
        argv = call["argv"]
        i = 0
        while i < len(argv) and argv[i] in ("-c", "-a", "--json", "--log-level"):
            i += 1 if argv[i] == "--json" else 2
        return argv[i:]

    def calls_of(self, *prefix):
        return [c for c in self.calls() if self.command(c)[:len(prefix)] == list(prefix)]

    # ---------------------------------------------------------------- jm state
    def read_state(self, name, default=None):
        p = self.state / name
        return json.loads(p.read_text()) if p.exists() else default

    def jsonl(self, name):
        p = self.state / name
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []

    def audit(self):
        rows = []
        for p in sorted((self.state / "audit").glob("*.jsonl")):
            rows += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
        return rows

    def queue(self):
        return {q["key"]: q for q in self.jsonl("queue.jsonl")}

    def ticket(self, code, digest, ts=None, session=None):
        d = self.state / "tickets"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{code}.json").write_text(json.dumps({"code": code, "hash": digest, "ts": ts or time.time(),
                                                    "session": session or self.session}))

    def gate(self, command, session=None):
        """Run the real send_gate.py hook with HOME = tmp home, as Claude Code would."""
        return run_gate(self.home, command, session or self.session)


def run_gate(home, command, session, tool="Bash"):
    payload = {"session_id": session, "tool_name": tool, "tool_input": {"command": command},
               "hook_event_name": "PreToolUse"}
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    r = subprocess.run([str(GATE_PATH)], input=json.dumps(payload), capture_output=True, text=True, env=env,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


@pytest.fixture
def mail(tmp_path, monkeypatch, capsys):
    return MailEnv(tmp_path, monkeypatch, capsys)


def by_subject(items, subject):
    hit = [i for i in items if i.get("subject") == subject]
    assert len(hit) == 1, (subject, items)
    return hit[0]
