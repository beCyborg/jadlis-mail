"""Offline tests of jm (scripts/jm) against the fake himalaya — one test (or group) per check of the owner's plan."""
import base64
import json
import time

import pytest

from conftest import CANARY, by_subject

OWNER = "owner.g1@gmail.example"  # privacy-ok: RFC 2606 fixture


def window(mail, *accts):
    rc, out = mail.run("window", "--acct", *accts)
    assert rc == 0, out
    return out


def apply(mail, run, decisions):
    return mail.run("apply", "--run", run, "--decisions", json.dumps(decisions))


# ---------------------------------------------------------------- 1. window / cursor and the 30-minute rule

def test_01_young_message_waits_then_is_offered_next_window(mail):
    mail.add_msg("gmail-01", "INBOX", frm="Ann <ann@people.example>", to=OWNER, subject="Fresh", age_min=29)  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    assert out["accounts"]["gmail-01"]["young"] == 1
    assert out["accounts"]["gmail-01"]["new"] == 0
    assert out["decide"] == 0 and out["items"] == []
    q = list(mail.queue().values())
    assert len(q) == 1 and q[0]["status"] == "young"

    mail.advance(2)                                      # the message is now 31 minutes old
    out = window(mail, "gmail-01")
    assert out["decide"] == 1
    assert by_subject(out["items"], "Fresh")["from"] == "Ann <ann@people.example>"  # privacy-ok: RFC 2606 fixture


def test_01b_apply_refuses_a_young_key(mail):
    mail.add_msg("gmail-01", "INBOX", frm="Ann <ann@people.example>", to=OWNER, subject="Fresh", age_min=29)  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    key = next(iter(mail.queue()))
    rc, res = apply(mail, out["run"], {key: "newsletters"})
    assert res["problems"] == [{"key": key, "error": "younger than 30 minutes — waits for the next window"}]
    assert mail.calls_of("imap", "move") == [] and mail.calls_of("imap", "store") == []
    assert key in mail.queue()


# ---------------------------------------------------------------- 2. a crash between window and apply

def test_02_crash_between_window_and_apply_loses_nothing(mail):
    mail.add_msg("gmail-01", "INBOX", frm="Old <old@people.example>", to=OWNER, subject="M0")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    rc, res = apply(mail, out["run"], {out["items"][0]["key"]: "keep"})
    assert rc == 0 and res["ok"]
    cur = mail.read_state("cursors.json")["gmail-01/inbox"]
    assert cur["last_uid"] == 1 and "pending" not in cur

    mail.add_msg("gmail-01", "INBOX", frm="New <new@people.example>", to=OWNER, subject="M1")     # uid 2  # privacy-ok: RFC 2606 fixture
    first = window(mail, "gmail-01")
    assert [i["subject"] for i in first["items"]] == ["M1"]
    cur = mail.read_state("cursors.json")["gmail-01/inbox"]
    assert cur["last_uid"] == 1 and cur["pending"]["last_uid"] == 2      # not moved past the queued message

    # crash: no apply. The next window offers the same item once, with no duplicate in the queue.
    second = window(mail, "gmail-01")
    assert [i["subject"] for i in second["items"]] == ["M1"]
    assert second["items"][0]["key"] == first["items"][0]["key"]
    assert len(mail.jsonl("queue.jsonl")) == 1
    assert mail.read_state("cursors.json")["gmail-01/inbox"]["last_uid"] == 1

    rc, res = apply(mail, second["run"], {second["items"][0]["key"]: "keep"})
    assert rc == 0 and res["ok"]
    cur = mail.read_state("cursors.json")["gmail-01/inbox"]
    assert cur["last_uid"] == 2 and "pending" not in cur
    assert window(mail, "gmail-01")["decide"] == 0


def test_02b_cursor_stops_before_the_oldest_undecided_message(mail):
    mail.add_msg("gmail-01", "INBOX", frm="A <a@people.example>", to=OWNER, subject="A")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-01", "INBOX", frm="B <b@people.example>", to=OWNER, subject="B")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    b = by_subject(out["items"], "B")
    rc, res = apply(mail, out["run"], {b["key"]: "keep"})
    assert res["ok"]
    cur = mail.read_state("cursors.json")["gmail-01/inbox"]
    assert cur["last_uid"] == 0 and cur["pending"]["last_uid"] == 2       # A (uid 1) still waits
    out = window(mail, "gmail-01")
    assert [i["subject"] for i in out["items"]] == ["A"]


# ---------------------------------------------------------------- 3. UIDVALIDITY change

def test_03_uidvalidity_change_rescans_by_date_skips_decided_loses_nothing(mail):
    mid_a = mail.add_msg("gmail-01", "INBOX", frm="A <a@people.example>", to=OWNER, subject="A")     # uid 1  # privacy-ok: RFC 2606 fixture
    mid_c = mail.add_msg("gmail-01", "INBOX", frm="C <c@people.example>", to=OWNER, subject="C")     # uid 2  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    rc, res = apply(mail, out["run"], {by_subject(out["items"], "A")["key"]: "keep"})
    assert res["ok"]
    cur = mail.read_state("cursors.json")["gmail-01/inbox"]
    old_uv = cur["uidvalidity"]

    # the server rebuilds INBOX: new UIDVALIDITY, UIDs renumbered from 1 (C first), then B arrives
    def renumber(data):
        box = data["accounts"]["gmail-01"]["mailboxes"]["INBOX"]
        box["uidvalidity"] = old_uv + 1000
        msgs = sorted(box["messages"], key=lambda m: m["uid"], reverse=True)
        for i, m in enumerate(msgs, 1):
            m["uid"] = i
        box["messages"], box["uidnext"] = msgs, len(msgs) + 1
    mail.mutate(renumber)
    mid_b = mail.add_msg("gmail-01", "INBOX", frm="B <b@people.example>", to=OWNER, subject="B", age_min=35)  # privacy-ok: RFC 2606 fixture

    out = window(mail, "gmail-01")
    st = out["accounts"]["gmail-01"]
    assert any(r.startswith("inbox since") for r in st["rescan"])
    assert st["known"] == 1 and st["new"] == 1
    assert sorted(i["subject"] for i in out["items"]) == ["B", "C"]          # A skipped, nothing lost or doubled
    q = {x["mid"]: x for x in mail.queue().values()}
    assert set(q) == {mid_b, mid_c}
    assert q[mid_c]["uid"] == 1 and q[mid_c]["uidvalidity"] == old_uv + 1000

    rc, res = apply(mail, out["run"], {i["key"]: "keep" for i in out["items"]})
    assert res["ok"]
    cur = mail.read_state("cursors.json")["gmail-01/inbox"]
    assert cur["uidvalidity"] == old_uv + 1000 and cur["last_uid"] == 3
    assert window(mail, "gmail-01")["decide"] == 0
    assert mid_a in mail.mids("gmail-01", "INBOX")


# ---------------------------------------------------------------- 4. verified moves

def test_04_move_is_verified_source_and_target_proton(mail):
    mid = mail.add_msg("proton", "Inbox", frm="Digest <digest@lists.example>", to="owner@proton.example", subject="Weekly")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "proton")
    rc, res = apply(mail, out["run"], {out["items"][0]["key"]: "newsletters"})
    assert rc == 0 and res["ok"] and res["accounts"]["proton"]["moved"] == {"newsletters": 1}
    assert mid not in mail.mids("proton", "Inbox")
    assert mid in mail.mids("proton", "Folders/Рассылки")
    raw = [c for c in mail.calls_of("imap", "raw")]
    assert raw, "the move must be verified by Message-ID searches"


def test_04b_message_gone_between_window_and_apply_is_reported_gone(mail):
    mid = mail.add_msg("gmail-01", "INBOX", frm="Shop <news@shop.example>", to=OWNER, subject="Sale")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")

    def owner_moves_it(data):
        boxes = data["accounts"]["gmail-01"]["mailboxes"]
        m = boxes["INBOX"]["messages"].pop()
        m["uid"] = boxes["Уведомления"]["uidnext"]
        boxes["Уведомления"]["uidnext"] += 1
        boxes["Уведомления"]["messages"].append(m)
    mail.mutate(owner_moves_it)

    rc, res = apply(mail, out["run"], {out["items"][0]["key"]: "newsletters"})
    acc = res["accounts"]["gmail-01"]
    assert acc["gone"] == 1 and acc["moved"] == {}
    assert mail.calls_of("imap", "move") == []
    assert [r["result"] for r in mail.audit() if r.get("cmd") == "apply"] == ["gone"]
    assert mid in mail.mids("gmail-01", "Уведомления") and mid not in mail.mids("gmail-01", "Рассылки")


def test_04c_move_that_silently_does_nothing_is_an_error_and_stays_queued(mail):
    mid = mail.add_msg("gmail-01", "INBOX", frm="Shop <news@shop.example>", to=OWNER, subject="Sale")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    key = out["items"][0]["key"]
    mail.set_mode("gmail-01", move_noop=True)            # himalaya #777: «successfully moved», nothing moved
    rc, res = apply(mail, out["run"], {key: "newsletters"})
    assert rc == 2 and res["ok"] is False
    errs = res["accounts"]["gmail-01"]["errors"]
    assert errs[0]["key"] == key and "still in source" in errs[0]["error"]
    assert res["accounts"]["gmail-01"]["moved"] == {}
    q = mail.queue()[key]
    assert q["status"] == "error" and q["attempts"] == 1
    assert mid in mail.mids("gmail-01", "INBOX")
    assert [r["result"] for r in mail.audit() if r.get("cmd") == "apply"] == ["error"]

    mail.set_mode("gmail-01", move_noop=False)           # the next window retries it
    out = window(mail, "gmail-01")
    assert [i["key"] for i in out["items"]] == [key] and out["items"][0]["retry"] == 1


def test_04d_move_of_a_uid_that_does_not_exist_is_reported_as_success_by_the_fake(mail):
    """The fake keeps himalaya bug #777 — the premise of every verification in jm."""
    jm = mail.jm
    cfg = jm.load_config()
    h = jm.Himalaya(cfg, jm.Secrets(cfg))
    a = jm.Account(h, cfg, "gmail-01")
    a.move("INBOX", [999], "Рассылки", ["<nobody@x>"])   # no exception
    assert mail.mids("gmail-01", "Рассылки") == []


# ---------------------------------------------------------------- 5. Gmail labels

def test_05_gmail_newsletters_lands_in_label_and_leaves_inbox(mail):
    mid = mail.add_msg("gmail-01", "INBOX", frm="Digest <digest@lists.example>", to=OWNER, subject="Weekly",  # privacy-ok: RFC 2606 fixture
                       headers={"List-Unsubscribe": "<mailto:u@lists.example>"})  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    item = out["items"][0]
    assert item["hint"] == "newsletters"
    rc, res = apply(mail, out["run"], {item["key"]: "newsletters"})
    assert rc == 0 and res["ok"]
    assert mid in mail.mids("gmail-01", "Рассылки")
    assert mid not in mail.mids("gmail-01", "INBOX")
    row = [r for r in mail.audit() if r.get("cmd") == "apply"][0]
    assert row["from_folder"] == "INBOX" and row["to_folder"] == "Рассылки" and row["result"] == "ok"


# ---------------------------------------------------------------- 6. undo

def test_06_undo_restores_place_and_removes_only_flags_jm_added(mail):
    m1 = mail.add_msg("gmail-01", "INBOX", frm="A <a@lists.example>", to=OWNER, subject="Read by owner",  # privacy-ok: RFC 2606 fixture
                      flags=["\\Seen"])
    m2 = mail.add_msg("gmail-01", "INBOX", frm="B <b@lists.example>", to=OWNER, subject="Starred by owner",  # privacy-ok: RFC 2606 fixture
                      flags=["\\Flagged"])
    out = window(mail, "gmail-01")
    k1 = by_subject(out["items"], "Read by owner")["key"]
    k2 = by_subject(out["items"], "Starred by owner")["key"]
    rc, res = apply(mail, out["run"], {k1: "newsletters+flag+seen", k2: "newsletters+flag+seen"})
    assert rc == 0 and res["ok"]
    assert mail.flags_of("gmail-01", "Рассылки", m1) == {"\\Seen", "\\Flagged"}
    assert mail.flags_of("gmail-01", "Рассылки", m2) == {"\\Seen", "\\Flagged"}

    rc, res = mail.run("undo", "--run", out["run"])
    assert rc == 0 and res["ok"] and len(res["undone"]) == 2
    assert set(mail.mids("gmail-01", "INBOX")) == {m1, m2}
    assert mail.mids("gmail-01", "Рассылки") == []
    assert mail.flags_of("gmail-01", "INBOX", m1) == {"\\Seen"}        # owner's \Seen stays, jm's \Flagged gone
    assert mail.flags_of("gmail-01", "INBOX", m2) == {"\\Flagged"}     # owner's \Flagged stays, jm's \Seen gone

    rc, res = mail.run("undo", "--run", out["run"])                   # a second undo finds nothing to do
    assert rc == 1 and res["ok"] is False


# ---------------------------------------------------------------- 7. protected mail

def test_07_protected_mail_is_never_queued_or_moved(mail):
    mail.add_msg("gmail-01", "INBOX", frm="CEO <ceo@corp.example>", to=OWNER, subject="P1 from domain")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-01", "INBOX", frm="X <x@people.example>", to="team@mail.corp.example", cc=OWNER,  # privacy-ok: RFC 2606 fixture
                 subject="P2 to subdomain")
    mail.add_msg("gmail-01", "INBOX", frm="Y <y@people.example>", to="contact@biz.example", subject="P3 contact")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-01", "INBOX", frm="Z <z@people.example>", to="agent-shop@proton.example", subject="P4 alias")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-01", "INBOX", frm="W <w@people.example>", to=OWNER, subject="Счёт CORP за октябрь")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-01", "INBOX", frm="N <n@people.example>", to=OWNER, subject="Normal")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    assert out["accounts"]["gmail-01"]["protected"] == 5
    assert [i["subject"] for i in out["items"]] == ["Normal"]
    assert [q["subject"] for q in mail.queue().values()] == ["Normal"]
    kept = [r for r in mail.audit() if r.get("cmd") == "window" and r["result"] == "keep"]
    assert len(kept) == 5 and all(r["reason"].startswith("protected: ") for r in kept)

    # apply refuses protected keys: they are not in the queue …
    rc, res = apply(mail, out["run"], {r["key"]: "spam" for r in kept})
    assert all(p["error"].startswith("not in the queue") for p in res["problems"]) and len(res["problems"]) == 5
    # … and even a protected item that got into the queue is refused
    q = next(iter(mail.queue().values()))
    q["protected"] = "domain corp.example"
    (mail.state / "queue.jsonl").write_text(json.dumps(q, ensure_ascii=False) + "\n")
    rc, res = apply(mail, out["run"], {q["key"]: "newsletters"})
    assert res["problems"] == [{"key": q["key"], "error": "protected mail is never moved"}]
    assert mail.calls_of("imap", "move") == [] and mail.calls_of("imap", "store") == []
    assert len(mail.mids("gmail-01", "INBOX")) == 6

    out = window(mail, "gmail-01")                                    # protected mail is not re-counted
    assert out["accounts"]["gmail-01"]["protected"] == 0


# ---------------------------------------------------------------- 8. spam only for strangers

def test_08_spam_for_a_correspondent_is_downgraded_to_newsletters(mail):
    mail.add_msg("gmail-01", "[Gmail]/Отправленные", frm=f"Owner <{OWNER}>", to="Friend <friend@people.example>",  # privacy-ok: RFC 2606 fixture
                 cc="pal@people.example", subject="Привет")  # privacy-ok: RFC 2606 fixture
    f = mail.add_msg("gmail-01", "INBOX", frm="Friend <friend@people.example>", to=OWNER, subject="From friend")  # privacy-ok: RFC 2606 fixture
    p = mail.add_msg("gmail-01", "INBOX", frm="Pal <pal@people.example>", to=OWNER, subject="From pal")  # privacy-ok: RFC 2606 fixture
    s = mail.add_msg("gmail-01", "INBOX", frm="Deals <deals@spammy.example>", to=OWNER, subject="Win")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    rc, res = apply(mail, out["run"], {i["key"]: "spam" for i in out["items"]})
    assert rc == 0 and res["ok"]
    assert res["accounts"]["gmail-01"]["moved"] == {"newsletters": 2, "spam": 1}
    assert set(mail.mids("gmail-01", "Рассылки")) == {f, p}
    assert mail.mids("gmail-01", "[Gmail]/Спам") == [s]
    rows = {r["subject"]: r for r in mail.audit() if r.get("cmd") == "apply"}
    assert rows["From friend"]["downgraded"] == "correspondent" and rows["From friend"]["action"] == "newsletters"
    assert rows["From pal"]["downgraded"] == "correspondent"
    assert "downgraded" not in rows["Win"] and rows["Win"]["spam_until"]


# ---------------------------------------------------------------- 9. bank mailbox digest

def test_09_digest_senders_account_reports_who_was_moved(mail):
    mail.add_msg("gmail-sp", "INBOX", frm="Bank Promo <promo@bank.example>", to="bank.owner@gmail.example", subject="1")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-sp", "INBOX", frm="Shop <news@shop.example>", to="bank.owner@gmail.example", subject="2")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-01", "INBOX", frm="Other <other@shop.example>", to=OWNER, subject="3")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-sp", "gmail-01")
    dec = {by_subject(out["items"], "1")["key"]: "newsletters", by_subject(out["items"], "2")["key"]: "notifications",
           by_subject(out["items"], "3")["key"]: "newsletters"}
    rc, res = apply(mail, out["run"], dec)
    assert rc == 0 and res["ok"]
    assert res["senders"] == {"gmail-sp": ["Bank Promo <promo@bank.example>", "Shop <news@shop.example>"]}  # privacy-ok: RFC 2606 fixture


# ---------------------------------------------------------------- 10. VIP stays in the inbox

def test_10_vip_mail_is_never_moved_to_newsletters_or_spam(mail):
    mid = mail.add_msg("gmail-01", "INBOX", frm="Boss <boss@vip.example>", to=OWNER, subject="Call me",  # privacy-ok: RFC 2606 fixture
                       headers={"List-Unsubscribe": "<mailto:x@vip.example>"})  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    item = out["items"][0]
    assert item["vip"] is True and item["hint"] == "flag"
    for act in ("newsletters", "spam", "notifications"):
        rc, res = apply(mail, out["run"], {item["key"]: act})
        assert res["problems"] == [{"key": item["key"], "error": "VIP mail stays in the inbox (flag or keep)"}]
    assert mail.calls_of("imap", "move") == []
    rc, res = apply(mail, out["run"], {item["key"]: "flag"})
    assert rc == 0 and res["ok"]
    assert mail.mids("gmail-01", "INBOX") == [mid]
    assert "\\Flagged" in mail.flags_of("gmail-01", "INBOX", mid)


# ---------------------------------------------------------------- 11. watches

def test_11_watch_survives_a_new_process_matches_and_closes(mail):
    rc, out = mail.run("watch", "add", "--from", "orders@store.example", "--note", "жду трек-номер")  # privacy-ok: RFC 2606 fixture
    assert rc == 0 and out["watch"]["id"] == "W1" and out["watch"]["status"] == "open"

    mail.jm = mail.load()                                 # a new process: fresh module, same state dir
    mail.add_msg("gmail-01", "INBOX", frm="Store <orders@store.example>", to=OWNER, subject="Shipped")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("gmail-01", "INBOX", frm="Else <else@people.example>", to=OWNER, subject="Other")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01")
    w = out["watches"]
    assert len(w) == 1 and w[0]["id"] == "W1" and w[0]["status"] == "matched"
    assert [m["subject"] for m in w[0]["matches"]] == ["Shipped"]
    out = window(mail, "gmail-01")                        # no duplicate match on the next window
    assert len(out["watches"][0]["matches"]) == 1

    mail.jm = mail.load()
    rc, out = mail.run("watch", "close", "W1")
    assert rc == 0 and out["closed"] == ["W1"]
    rc, out = mail.run("watch", "list")
    assert out["watches"] == []
    assert window(mail, "gmail-01")["watches"] == []


# ---------------------------------------------------------------- 12. send gate, jm side

def make_draft(mail, acct="gmail-01", to="friend@people.example", subject="Привет", body="Hello there"):  # privacy-ok: RFC 2606 fixture
    rc, out = mail.run("draft", "--acct", acct, "--to", to, "--subject", subject, "--body", body)
    assert rc == 0 and out["ok"], out
    return out["code"], out["hash"]


def drafts_folder(acct):
    return {"gmail-01": "[Gmail]/Черновики", "icloud": "Drafts", "proton": "Drafts"}[acct]


def assert_nothing_sent(mail):
    assert mail.calls_of("message", "send") == []
    assert all(not a["sent_out"] for a in mail.imap()["accounts"].values())


def test_12a_send_without_ticket_is_refused(mail):
    code, h = make_draft(mail)
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 1 and out["ok"] is False and "no confirmation ticket" in out["error"]
    assert_nothing_sent(mail)


def test_12b_ticket_for_d1_does_not_let_d2_go(mail):
    c1, h1 = make_draft(mail, subject="one")
    c2, h2 = make_draft(mail, subject="two")
    assert (c1, c2) == ("D1", "D2")
    mail.ticket(c1, h1)
    rc, out = mail.run("send", c2, "--hash", h2)
    assert rc == 1 and "no confirmation ticket" in out["error"]
    assert_nothing_sent(mail)


def test_12c_ticket_with_another_hash_is_refused(mail):
    code, h = make_draft(mail)
    other = "0123456789"
    mail.ticket(code, other)
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 1 and "another draft or hash" in out["error"]
    mail.ticket(code, other)
    rc, out = mail.run("send", code, "--hash", other)         # the ticket matches, the draft does not
    assert rc == 1 and "changed after you confirmed" in out["error"]
    assert_nothing_sent(mail)


def test_12d_ticket_older_than_15_minutes_is_refused(mail):
    code, h = make_draft(mail)
    mail.ticket(code, h, ts=time.time() - 15 * 60 - 5)
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 1 and "older than 15 minutes" in out["error"]
    assert_nothing_sent(mail)


def test_12e_ticket_is_consumed(mail):
    code, h = make_draft(mail)
    mail.ticket(code, h, ts=time.time() - 16 * 60)               # even a refused ticket is gone afterwards
    mail.run("send", code, "--hash", h)
    assert not (mail.state / "tickets" / f"{code}.json").exists()
    mail.ticket(code, h)
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 0 and out["ok"]
    assert not (mail.state / "tickets" / f"{code}.json").exists()
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 1 and "no confirmation ticket" in out["error"]
    assert len(mail.calls_of("message", "send")) == 1


def test_12f_draft_changed_on_server_after_confirmation_is_refused(mail):
    code, h = make_draft(mail)

    def edit(data):
        box = data["accounts"]["gmail-01"]["mailboxes"][drafts_folder("gmail-01")]
        raw = base64.b64decode(box["messages"][0]["raw_b64"])
        assert b"Hello there" in raw
        box["messages"][0]["raw_b64"] = base64.b64encode(raw.replace(b"Hello there", b"Pay to IBAN X")).decode()
    mail.mutate(edit)
    mail.ticket(code, h)
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 1 and "changed after you confirmed" in out["error"]
    assert_nothing_sent(mail)
    assert len(mail.mids("gmail-01", drafts_folder("gmail-01"))) == 1


def test_12g_reply_in_hide_my_email_thread_is_refused(mail):
    mail.add_msg("icloud", "INBOX", frm="Store <orders@store.example>", to="quiet-fox-42@privaterelay.appleid.com",  # privacy-ok: RFC 2606 fixture
                 headers={"Delivered-To": "owner@icloud.example"}, subject="Your order")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "icloud")
    item = out["items"][0]
    assert item["hme"] == "quiet-fox-42@privaterelay.appleid.com"  # privacy-ok: RFC 2606 fixture
    rc, d = mail.run("draft", "--reply", item["key"], "--body", "Thanks")
    assert rc == 0 and d["hme"] == "quiet-fox-42@privaterelay.appleid.com" and d["send"] is None and "warning" in d  # privacy-ok: RFC 2606 fixture
    assert d["to"] == "orders@store.example" and d["subject"] == "Re: Your order"  # privacy-ok: RFC 2606 fixture
    mail.ticket(d["code"], d["hash"])
    rc, out = mail.run("send", d["code"], "--hash", d["hash"])
    assert rc == 1 and "Hide My Email" in out["error"]
    assert_nothing_sent(mail)


def test_12h_extra_argv_is_refused(mail):
    code, h = make_draft(mail)
    for argv in (["send", code, "--hash", h, "--x"], ["send", code, "--hash", h, "extra"]):
        mail.ticket(code, h)
        with pytest.raises(SystemExit):
            mail.run(*argv)
    for argv in (["send", code, "--hash", h, "--hash", h], ["send", "--hash", h, code]):
        mail.ticket(code, h)
        rc, out = mail.run(*argv)
        assert rc == 1 and "send takes exactly" in out["error"]
    assert_nothing_sent(mail)


def test_12i_valid_ticket_from_the_hook_sends_exactly_once(mail):
    code, h = make_draft(mail)
    folder = drafts_folder("gmail-01")
    assert len(mail.mids("gmail-01", folder)) == 1
    decision = mail.gate(f"jm send {code} --hash {h}")                # the real hook writes the ticket
    assert decision["hookSpecificOutput"]["permissionDecision"] == "ask"
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 0 and out["ok"] and out["sent"] == code and out["draft_removed"] is True
    sends = mail.calls_of("message", "send")
    assert len(sends) == 1 and "--no-save" in mail.command(sends[0])
    sent = mail.imap()["accounts"]["gmail-01"]["sent_out"]
    assert len(sent) == 1 and b"Hello there" in base64.b64decode(sent[0]["raw_b64"])
    assert mail.mids("gmail-01", folder) == []
    d = {x["code"]: x for x in mail.jsonl("drafts.jsonl")}
    assert d[code]["status"] == "sent"


def test_12j_any_other_bash_call_voids_the_ticket_before_send(mail):
    code, h = make_draft(mail)
    mail.gate(f"jm send {code} --hash {h}")
    mail.gate(f"jm send {code} --hash {h} && echo done")             # the call that would actually run
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 1 and "no confirmation ticket" in out["error"]
    assert_nothing_sent(mail)


# ---------------------------------------------------------------- 12k. ticket bound to the Claude Code session

def test_12k_ticket_of_another_session_is_refused_and_left_in_place(mail, monkeypatch):
    code, h = make_draft(mail)
    mail.ticket(code, h, session="session-A")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-B")
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 1 and "belongs to another session" in out["error"]
    assert (mail.state / "tickets" / f"{code}.json").exists()
    assert_nothing_sent(mail)


def test_12l_send_outside_a_claude_code_session_is_refused(mail, monkeypatch):
    code, h = make_draft(mail)
    mail.ticket(code, h)
    for value in (None, ""):
        if value is None:
            monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        else:
            monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", value)
        rc, out = mail.run("send", code, "--hash", h)
        assert rc == 1 and "only inside a Claude Code session" in out["error"]
    assert_nothing_sent(mail)


def test_12m_ticket_of_the_same_session_sends(mail, monkeypatch):
    code, h = make_draft(mail)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-A")
    mail.gate(f"jm send {code} --hash {h}", session="session-A")
    rc, out = mail.run("send", code, "--hash", h)
    assert rc == 0 and out["ok"]
    assert len(mail.calls_of("message", "send")) == 1


# ---------------------------------------------------------------- 14. secrets

def test_14_secret_reaches_only_its_own_himalaya_call(mail, monkeypatch):
    monkeypatch.setenv("JM_SECRET_GMAIL_SP", "parent-leak-0000")      # a stray var in jm's own environment
    mail.add_msg("gmail-01", "INBOX", frm="A <a@lists.example>", to=OWNER, subject="g")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("proton", "Inbox", frm="B <b@lists.example>", to="owner@proton.example", subject="p")  # privacy-ok: RFC 2606 fixture
    mail.add_msg("icloud", "INBOX", frm="C <c@lists.example>", to="owner@icloud.example", subject="i")  # privacy-ok: RFC 2606 fixture
    out = window(mail, "gmail-01", "proton", "icloud")
    rc, res = apply(mail, out["run"], {i["key"]: "newsletters" for i in out["items"]})
    assert res["ok"]
    rc, _ = mail.run("search", "--from", "lists.example")
    assert rc == 0
    code, h = make_draft(mail, acct="proton")
    mail.gate(f"jm send {code} --hash {h}")
    rc, sent = mail.run("send", code, "--hash", h)
    assert rc == 0 and sent["ok"]

    calls = mail.calls()
    accts = set()
    for c in calls:
        argv = c["argv"]
        acct = argv[argv.index("-a") + 1]
        accts.add(acct)
        assert not any(CANARY in a for a in argv), argv
        env_name = "JM_SECRET_" + acct.upper().replace("-", "_")
        assert c["secrets"] == {env_name: f"{CANARY}-{acct}"}, (acct, c["secrets"])
    assert accts == {"gmail-01", "gmail-sp", "proton", "icloud"}    # search runs over every account
    assert not any("parent-leak" in json.dumps(c) for c in calls)

    secret_runs = [json.loads(x) for x in mail.secret_log.read_text().splitlines()]
    assert {r["acct"] for r in secret_runs} == accts
    for r in secret_runs:
        assert not any(k.startswith("JM_SECRET_") for k in r["env"]), r["acct"]
        assert not any(CANARY in v for v in r["env"].values())

    files = [p for p in mail.state.rglob("*") if p.is_file()]
    names = {p.name for p in files}
    assert {"queue.jsonl", "refs.json", "drafts.jsonl", "runs.jsonl", "cursors.json"} <= names
    assert any(p.parent.name == "audit" for p in files)
    for p in files:
        assert CANARY.encode() not in p.read_bytes(), p


# ---------------------------------------------------------------- 15. undecided limit

def test_15_item_undecided_for_more_than_three_windows_is_kept_in_place(mail):
    mid = mail.add_msg("gmail-01", "INBOX", frm="Q <q@people.example>", to=OWNER, subject="Nobody decides")  # privacy-ok: RFC 2606 fixture
    for n in (1, 2, 3):
        out = window(mail, "gmail-01")
        assert [i["subject"] for i in out["items"]] == ["Nobody decides"], n
    out = window(mail, "gmail-01")                                   # the 4th window
    assert out["decide"] == 0 and out["items"] == []
    assert mail.queue() == {}
    rows = [r for r in mail.audit() if r.get("cmd") == "window"]
    assert len(rows) == 1 and rows[0]["result"] == "keep" and rows[0]["reason"] == "undecided"
    assert rows[0]["mid"] == mid
    out = window(mail, "gmail-01")                                   # and it does not come back
    assert out["decide"] == 0 and out["accounts"]["gmail-01"]["known"] == 1
    assert mail.queue() == {}
    assert mail.mids("gmail-01", "INBOX") == [mid]
    assert mail.calls_of("imap", "move") == []


# ---------------------------------------------------------------- iCloud has no MOVE: copy → verify → expunge

def _no_move(mail, acct="icloud"):
    mail.mutate(lambda d: d["accounts"][acct].update(capabilities=["IMAP4rev1", "UIDPLUS", "IDLE"]))


def test_16_icloud_without_move_copies_verifies_then_removes_original(mail):
    _no_move(mail)
    other = mail.add_msg("icloud", "INBOX", frm="Friend <f@friend.example>", to="owner@icloud.example", subject="Hi",  # privacy-ok: RFC 2606 fixture
                         age_min=10)
    mid = mail.add_msg("icloud", "INBOX", frm="Digest <digest@lists.example>", to="owner@icloud.example",  # privacy-ok: RFC 2606 fixture
                       subject="Weekly", headers={"List-Unsubscribe": "<mailto:u@lists.example>"})  # privacy-ok: RFC 2606 fixture
    out = window(mail, "icloud")
    key = [i["key"] for i in out["items"] if i["subject"] == "Weekly"][0]
    rc, res = apply(mail, out["run"], {key: "newsletters"})
    assert rc == 0 and res["ok"] and res["accounts"]["icloud"]["moved"] == {"newsletters": 1}
    assert mid in mail.mids("icloud", "Рассылки") and mid not in mail.mids("icloud", "INBOX")
    assert other in mail.mids("icloud", "INBOX"), "only the copied UID may be expunged"
    assert mail.calls_of("imap", "move") == [] and mail.calls_of("imap", "copy")
    rc, un = mail.run("undo", "--run", out["run"])
    assert rc == 0 and un["ok"]
    assert mid in mail.mids("icloud", "INBOX") and mid not in mail.mids("icloud", "Рассылки")


def test_16b_icloud_copy_that_did_not_arrive_never_removes_the_original(mail):
    _no_move(mail)
    mid = mail.add_msg("icloud", "INBOX", frm="Digest <digest@lists.example>", to="owner@icloud.example",  # privacy-ok: RFC 2606 fixture
                       subject="Weekly")
    out = window(mail, "icloud")
    key = out["items"][0]["key"]
    mail.set_mode("icloud", move_noop=True)              # copy «succeeds», nothing copied
    rc, res = apply(mail, out["run"], {key: "newsletters"})
    assert rc == 2 and res["accounts"]["icloud"]["errors"][0]["key"] == key
    assert mid in mail.mids("icloud", "INBOX") and mid not in mail.mids("icloud", "Рассылки")
    assert not [c for c in mail.calls_of("imap", "raw") if "EXPUNGE" in json.dumps(c)]


def test_17_safe_mid_accepts_long_bare_ids_only(mail):
    jm = mail.jm
    assert jm.safe_mid("<a@b>") and jm.safe_mid("ae60b8425cdd468d83f45ac6b93f28ae")
    assert not jm.safe_mid("short123") and not jm.safe_mid('<a"b@c>') and not jm.safe_mid("<a b@c>")
    assert not jm.safe_mid("ae60b8425cdd468d83f45ac6b93f28ae\r\na9 STORE")


# ---------------------------------------------------------------- 18. Inbox Zero: archive after 7 days

DAY = 24 * 60


def test_18_archive_moves_only_old_read_unflagged_non_vip(mail):
    old = mail.add_msg("gmail-01", "INBOX", frm="Shop <a@shop.example>", to=OWNER, subject="Old read",  # privacy-ok: RFC 2606 fixture
                       age_min=8 * DAY, flags=["\\Seen"])
    fresh = mail.add_msg("gmail-01", "INBOX", frm="Shop <a@shop.example>", to=OWNER, subject="Fresh read",  # privacy-ok: RFC 2606 fixture
                         age_min=2 * DAY, flags=["\\Seen"])
    unread = mail.add_msg("gmail-01", "INBOX", frm="Shop <a@shop.example>", to=OWNER, subject="Old unread",  # privacy-ok: RFC 2606 fixture
                          age_min=9 * DAY)
    flagged = mail.add_msg("gmail-01", "INBOX", frm="Shop <a@shop.example>", to=OWNER, subject="Old flagged",  # privacy-ok: RFC 2606 fixture
                           age_min=9 * DAY, flags=["\\Seen", "\\Flagged"])
    vip = mail.add_msg("gmail-01", "INBOX", frm="Boss <boss@vip.example>", to=OWNER, subject="Old vip",  # privacy-ok: RFC 2606 fixture
                       age_min=9 * DAY, flags=["\\Seen"])
    prot = mail.add_msg("gmail-01", "INBOX", frm="Lead <x@corp.example>", to=OWNER, subject="Old protected",  # privacy-ok: RFC 2606 fixture
                       age_min=9 * DAY, flags=["\\Seen"])
    rc, out = mail.run("archive", "--acct", "gmail-01")
    assert rc == 0 and out["ok"], out
    acc = out["accounts"]["gmail-01"]
    assert acc["moved"] == {"archive": 1} and acc["skipped"] == {"protected": 1, "vip": 1}
    inbox = mail.mids("gmail-01", "INBOX")
    assert old not in inbox and old in mail.mids("gmail-01", "[Gmail]/Вся почта")
    for m in (fresh, unread, flagged, vip, prot):
        assert m in inbox
    rc, un = mail.run("undo", "--run", out["run"])
    assert rc == 0 and un["ok"], un
    assert old in mail.mids("gmail-01", "INBOX")


def test_18b_archive_dry_run_changes_nothing(mail):
    old = mail.add_msg("icloud", "INBOX", frm="Shop <a@shop.example>", to="owner@icloud.example", subject="Old",  # privacy-ok: RFC 2606 fixture
                       age_min=8 * DAY, flags=["\\Seen"])
    rc, out = mail.run("archive", "--acct", "icloud", "--dry-run")
    assert rc == 0 and out["accounts"]["icloud"]["would"][0]["to"] == "Archive"
    assert old in mail.mids("icloud", "INBOX") and not mail.audit()


# ---------------------------------------------------------------- 19. local index over Apple Mail's copy

def _emlx(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"{len(raw)}\n".encode() + raw + b"<?xml version=\"1.0\"?><plist/>")


def _raw(subject, frm="Bank <info@bank.example>", body="text", mid=None):  # privacy-ok: RFC 2606 fixture
    from email.message import EmailMessage
    import email.policy
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "owner.g1@gmail.example", subject  # privacy-ok: RFC 2606 fixture
    m["Date"] = "Wed, 14 Oct 2026 10:00:00 +0000"
    m["Message-ID"] = mid or f"<{subject.encode().hex()[:20]}@bank.example>"
    m.set_content(body)
    return m.as_bytes(policy=email.policy.SMTP)


def test_19_index_finds_cyrillic_with_yo_dedupes_and_tracks_deletes(mail, tmp_path):
    jm = mail.jm
    jm.MAIL_ROOT = tmp_path / "Mail"
    cfg = json.loads((mail.state / "config.json").read_text())
    cfg["accounts"]["gmail-01"]["mail_dir"] = "UUID-G1"
    (mail.state / "config.json").write_text(json.dumps(cfg, ensure_ascii=False))
    base = jm.MAIL_ROOT / "V10" / "UUID-G1"
    raw = _raw("Счёт за октябрь", body="Оплатите счёт до пятницы", mid="<bill-1@bank.example>")  # privacy-ok: RFC 2606 fixture
    _emlx(base / "INBOX.mbox" / "u" / "Data" / "Messages" / "1.emlx", raw)
    _emlx(base / "[Gmail].mbox" / "Вся почта.mbox" / "u" / "Data" / "Messages" / "1.emlx", raw)
    _emlx(base / "[Gmail].mbox" / "Спам.mbox" / "u" / "Data" / "Messages" / "2.emlx",
          _raw("Счет-фактура спам", mid="<spam-1@bank.example>"))  # privacy-ok: RFC 2606 fixture
    rc, out = mail.run("search", "--acct", "gmail-01", "--subject", "счет")
    assert rc == 0 and out["count"] == 1 and out["items"][0]["folder"] == "INBOX", out
    assert "index" in out
    rc, out = mail.run("search", "--acct", "gmail-01", "--text", "пятницы")
    assert out["count"] == 1
    rc, out = mail.run("search", "--acct", "gmail-01", "--subject", "счет", "--spam")
    assert out["count"] == 2
    (base / "INBOX.mbox" / "u" / "Data" / "Messages" / "1.emlx").unlink()
    (base / "[Gmail].mbox" / "Вся почта.mbox" / "u" / "Data" / "Messages" / "1.emlx").unlink()
    rc, out = mail.run("search", "--acct", "gmail-01", "--subject", "счет")
    assert out["count"] == 0
    assert not mail.calls_of("imap", "search"), "indexed accounts must not hit the server"


def test_20_addresses_survive_envelope_name_equal_to_address(mail):
    jm = mail.jm
    assert [a for _, a in jm.addresses("alias-x.y@relay.example <alias-x.y@relay.example>")] == ["alias-x.y@relay.example"]  # privacy-ok: RFC 2606 fixture
    assert jm.addresses("Ivan <ivan@net.example>, b@c.example") == [("Ivan", "ivan@net.example"), ("", "b@c.example")]  # privacy-ok: RFC 2606 fixture
    assert jm.addresses("") == []


def test_profile_path_default_and_configured(mail, tmp_path):
    rc, out = mail.run("profile")
    assert rc == 0 and out["profile"] == str(mail.state / "profile.md") and out["exists"] is False
    assert out["accounts"]["gmail-sp"] == {"email": "bank.owner@gmail.example", "provider": "gmail",  # privacy-ok: RFC 2606 fixture
                                           "digest_senders": True, "enabled": True}
    assert "secret" not in json.dumps(out["accounts"])
    notes = tmp_path / "notes.md"
    notes.write_text("owner notes")
    mail.write_config(profile=str(notes))
    rc, out = mail.run("profile")
    assert rc == 0 and out["profile"] == str(notes) and out["exists"] is True


def test_search_view_has_recipient(mail):
    mail.add_msg("proton", "Inbox", frm="Shop <a@shop.example>", to="agent-shop@proton.example", subject="Confirm")  # privacy-ok: RFC 2606 fixture
    rc, out = mail.run("search", "--acct", "proton", "--server", "--folder", "inbox", "--subject", "Confirm")
    assert rc == 0 and out["items"][0]["to"] == "agent-shop@proton.example"  # privacy-ok: RFC 2606 fixture
