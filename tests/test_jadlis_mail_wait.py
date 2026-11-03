"""scripts/mail-wait.sh: argument parsing, default resolution and the match loop against a fake jm (no network)."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WAIT = ROOT / "scripts" / "mail-wait.sh"

pytestmark = pytest.mark.skipif(not (shutil.which("zsh") and shutil.which("jq")), reason="needs zsh and jq")

FAKE_JM = """#!/bin/sh
# fake jm: `search` prints $FAKE_SEARCH, `read` prints $FAKE_READ; every call is logged
echo "$*" >> "$FAKE_LOG"
case "$1" in
  search) cat "$FAKE_SEARCH";;
  read) cat "$FAKE_READ";;
  *) echo '{"ok":false,"error":"unexpected"}'; exit 1;;
esac
"""


def now_min(offset_s=0):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + offset_s))


@pytest.fixture
def env(tmp_path):
    jm = tmp_path / "jm"
    jm.write_text(FAKE_JM)
    jm.chmod(0o755)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("JM_", "JADLIS_", "FAKE_"))}
    e.update({"HOME": str(tmp_path), "JM_BIN": str(jm), "FAKE_LOG": str(tmp_path / "log"),
              "FAKE_SEARCH": str(tmp_path / "search.json"), "FAKE_READ": str(tmp_path / "read.txt"),
              "JADLIS_AGENT_CONF": str(tmp_path / "agent.conf"), "JM_CONFIG": str(tmp_path / "config.json")})
    return tmp_path, e


def run(e, *args):
    r = subprocess.run([str(WAIT), *args], env=e, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def dry(e, *args):
    rc, out, err = run(e, *args, "--dry-run")
    assert rc == 0, err
    return json.loads(out)


def test_usage_errors(env):
    _, e = env
    assert run(e)[0] == 2
    assert run(e, "a", "b")[0] == 2
    assert run(e, "x", "--bogus")[0] == 2
    assert run(e, "x", "--timeout", "ten")[0] == 2
    assert run(e, "x", "--account")[0] == 2


def test_no_account_anywhere_is_an_error(env):
    _, e = env
    rc, _, err = run(e, "x", "--dry-run")
    assert rc == 2 and "no account" in err


def test_defaults_agent_conf_then_config_json(env):
    tmp, e = env
    (tmp / "config.json").write_text(json.dumps({"accounts": {"off": {"enabled": False}, "main": {}},
                                                 "mail_wait": {"folder": "Spam"}}))
    d = dry(e, "verify")
    assert (d["account"], d["folder"]) == ("main", "Spam")
    (tmp / "config.json").write_text(json.dumps({"accounts": {"main": {}}, "mail_wait": {"account": "w"}}))
    d = dry(e, "verify")
    assert (d["account"], d["folder"]) == ("w", "")
    (tmp / "agent.conf").write_text('# agent.conf\nOP_VAULT=Agent\nMAIL_ACCOUNT="agentbox"\nMAIL_FOLDER=Inbox  \n')
    d = dry(e, "verify")
    assert (d["account"], d["folder"], d["account_from"]) == ("agentbox", "Inbox", "agent.conf")
    d = dry(e, "verify", "--account", "flagged", "--folder", "Sent", "--timeout", "30", "--interval", "2")
    assert (d["account"], d["folder"], d["timeout"], d["interval"]) == ("flagged", "Sent", 30, 2)


def test_all_mail_means_jm_default_scope(env):
    tmp, e = env
    (tmp / "agent.conf").write_text("MAIL_ACCOUNT=box\nMAIL_FOLDER=All Mail\n")
    assert dry(e, "x")["folder"] == ""
    assert dry(e, "x", "--folder", "all")["folder"] == ""


def test_found_prints_id_subject_first_link(env):
    tmp, e = env
    (tmp / "search.json").write_text(json.dumps({"ok": True, "errors": None, "items": [
        {"key": "ag-old", "acct": "box", "folder": "All Mail", "date": now_min(-3600), "from": "Shop <a@shop.example>",  # privacy-ok: RFC 2606 fixture
         "to": "me@corp.example", "subject": "Verify your account"},  # privacy-ok: RFC 2606 fixture
        {"key": "ag-other", "acct": "box", "folder": "All Mail", "date": now_min(), "from": "News <n@news.example>",  # privacy-ok: RFC 2606 fixture
         "to": "me@corp.example", "subject": "Weekly"},  # privacy-ok: RFC 2606 fixture
        {"key": "ag-new", "acct": "box", "folder": "All Mail", "date": now_min(), "from": "Shop <a@shop.example>",  # privacy-ok: RFC 2606 fixture
         "to": "agent-shop@corp.example", "subject": "Confirm your email"}]}))  # privacy-ok: RFC 2606 fixture
    (tmp / "read.txt").write_text("key: ag-new\nSubject: Confirm your email\n\nbody\n"
                                  "Links (untrusted):\n- https://shop.example/confirm?t=1\n- https://shop.example/x\n")
    rc, out, err = run(e, "AGENT-SHOP@", "--account", "box", "--timeout", "0", "--folder", "Inbox")
    assert rc == 0, err
    d = json.loads(out.splitlines()[0])
    assert d["id"] == "ag-new" and d["subject"] == "Confirm your email"
    assert d["url"] == "https://shop.example/confirm?t=1" and len(d["links"]) == 2
    calls = (tmp / "log").read_text().splitlines()
    assert calls[0].startswith("search --acct box --since ") and "--server" in calls[0] and "--folder Inbox" in calls[0]
    assert calls[1] == "read ag-new --links"


def test_timeout_exit_1_and_jm_error_exit_3(env):
    tmp, e = env
    (tmp / "search.json").write_text(json.dumps({"ok": True, "items": []}))
    rc, _, err = run(e, "nothing", "--account", "box", "--timeout", "0")
    assert rc == 1 and "timeout" in err
    (tmp / "search.json").write_text(json.dumps({"ok": False, "errors": {"box": "Proton Mail Bridge is not answering"},
                                                 "items": []}))
    rc, _, err = run(e, "nothing", "--account", "box", "--timeout", "0")
    assert rc == 3 and "Bridge" in err
