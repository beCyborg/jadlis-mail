"""Linux port of jm: himalaya path, Bridge start through systemd, local time zone from config.json."""
import json
import os
import subprocess
import time

from conftest import load_jm


def test_jm_himalaya_env_wins(tmp_path, monkeypatch):
    fake = tmp_path / "himalaya"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("JM_HIMALAYA", str(fake))
    assert load_jm().HIMALAYA == str(fake)


def test_timezone_from_config_when_tz_unset(tmp_path, monkeypatch):
    jm = load_jm()
    monkeypatch.setattr(jm, "STATE", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"timezone": "Europe/Warsaw", "accounts": {}}))
    monkeypatch.delenv("TZ", raising=False)
    try:
        jm.load_config()
        assert os.environ["TZ"] == "Europe/Warsaw"
        assert time.strftime("%Z", time.localtime(1763280000)) in ("CET", "CEST")
    finally:
        os.environ.pop("TZ", None)
        time.tzset()


def test_bridge_started_by_systemd_on_linux(monkeypatch):
    jm = load_jm()
    calls = []
    monkeypatch.setattr(jm.sys, "platform", "linux")
    monkeypatch.setattr(jm, "bridge_up", lambda: len(calls) > 0)
    monkeypatch.setattr(jm.time, "sleep", lambda s: None)
    monkeypatch.setattr(jm.subprocess, "run", lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0))
    jm.ensure_bridge()
    assert calls == [["systemctl", "--user", "start", "proton-bridge.service"]]
