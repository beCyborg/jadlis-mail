"""Offline tests of the PreToolUse send gate (hooks/send_gate.py), run as Claude Code runs it: JSON on stdin,
HOME pointed at a tmp dir so tickets land in <tmp>/.claude/jadlis/mail/tickets/."""
import json
import time

import pytest

from conftest import run_gate

SESSION = "sess-1"
CANON = "jm send D1 --hash 0123456789"


@pytest.fixture
def home(tmp_path):
    return tmp_path


def tickets(home):
    d = home / ".claude" / "jadlis" / "mail" / "tickets"
    return {p.name: json.loads(p.read_text()) for p in d.glob("*.json")} if d.is_dir() else {}


def test_13a_canonical_send_gets_a_ticket_and_ask(home):
    out = run_gate(home, CANON, SESSION)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse" and hso["permissionDecision"] == "ask"
    assert "D1" in hso["permissionDecisionReason"] and "0123456789" in hso["permissionDecisionReason"]
    t = tickets(home)["D1.json"]
    assert t["code"] == "D1" and t["hash"] == "0123456789" and t["session"] == SESSION
    assert abs(time.time() - t["ts"]) < 60


@pytest.mark.parametrize("path", ["jm", "~/bin/jm", "/opt/agent/.claude/plugins/jadlis-mail/scripts/jm"])
def test_13b_canonical_with_a_path_to_jm(home, path):
    out = run_gate(home, f"{path} send D7 --hash abcdef0123", SESSION)
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert "D7.json" in tickets(home)


@pytest.mark.parametrize("command", [
    'bash -c "jm send D1 --hash 0123456789"',
    "X=1 jm send D1 --hash 0123456789",
    "jm send D1 --hash 0123456789 && echo",
    "jm  'send' D1 --hash 0123456789",
    "jm send D1 --hash 0123456789; jm send D2 --hash 0123456789",
    "jm send D1 --hash 0123456789\njm send D2 --hash 0123456789",
    "jm send D1 --hash 0123456789 --x",
    "echo hi",
])
def test_13c_any_other_form_gets_no_ticket_and_voids_the_session_ticket(home, command):
    run_gate(home, CANON, SESSION)
    assert "D1.json" in tickets(home)
    out = run_gate(home, command, SESSION)
    assert out is None                                    # no decision: the normal permission flow applies
    assert tickets(home) == {}


def test_13d_ticket_of_another_session_survives_an_unrelated_call(home):
    run_gate(home, CANON, "other-session")
    run_gate(home, "ls -la", SESSION)
    t = tickets(home)
    assert t["D1.json"]["session"] == "other-session"


def test_13e_stale_ticket_of_another_session_is_voided(home):
    run_gate(home, CANON, "other-session")
    p = home / ".claude" / "jadlis" / "mail" / "tickets" / "D1.json"
    t = json.loads(p.read_text())
    t["ts"] -= 901
    p.write_text(json.dumps(t))
    run_gate(home, "ls", SESSION)
    assert tickets(home) == {}


def test_13f_non_bash_tool_is_ignored(home):
    run_gate(home, CANON, SESSION)
    assert run_gate(home, "anything", SESSION, tool="Read") is None
    assert "D1.json" in tickets(home)
