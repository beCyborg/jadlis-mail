# Accounts

jm works with any IMAP account that himalaya can open. Every account is one entry in `~/.claude/jadlis/mail/config.json → accounts`; the name of the entry (`icloud`, `gmail-work`, `proton`, …) is the jm account name. The examples use `example.com` addresses.

| Provider (`provider`) | IMAP | SMTP | Password | Notes |
|---|---|---|---|---|
| `icloud` | `imap.mail.me.com:993`, login = the part before `@icloud.com` | `smtp.mail.me.com:587` STARTTLS | app-specific password (appleid.apple.com → Sign-In and Security → App-Specific Passwords) | no IMAP MOVE: jm copies, verifies, then expunges only those UIDs; Hide My Email replies only from Mail |
| `gmail` | `imap.gmail.com:993` | `smtp.gmail.com:465` | app password (myaccount.google.com/apppasswords, needs 2-Step Verification) | folders are labels; a move removes the inbox label, the letter stays in All Mail |
| `proton` | Proton Mail Bridge `127.0.0.1:1143`, STARTTLS with Bridge's exported certificate | Bridge `127.0.0.1:1025` STARTTLS | the mailbox password Bridge shows (Bridge → the account → Mailbox details) | jm starts Bridge when it is not answering; non-ASCII search is matched locally |
| anything else | the provider's IMAP host | the provider's SMTP host | app password | special folders are found by IMAP attributes |

## Folders

| Role | iCloud | Gmail (labels) | Proton |
|---|---|---|---|
| inbox | `INBOX` | `INBOX` | `Inbox` |
| newsletters | `Рассылки` | `Рассылки` | `Folders/Рассылки` |
| notifications | `Уведомления` | `Уведомления` | `Folders/Уведомления` |
| spam | found by `\Junk` | `[Gmail]/Spam` (`\Junk`) | `Spam` |
| drafts, sent, all | by special-use attributes | `[Gmail]/Drafts`, `[Gmail]/Sent Mail`, `[Gmail]/All Mail` | `Drafts`, `Sent`, `All Mail` |

jm finds special folders by IMAP attributes, not by names (Gmail localises them to the UI language). The newsletters and notifications folders are whatever `folders` in `config.json` names — any language works; `jm preflight --create-folders` creates them.

## Files

- `~/.config/himalaya/config.toml` and the optional `~/.config/himalaya/personal.toml` — IMAP blocks. jm loads them together (`config.toml:personal.toml`), so you can keep accounts that other tools read from `config.toml` apart from jm-only ones.
- `~/.config/himalaya/send.toml` — SMTP blocks, loaded only by `jm send`. Claude's Bash should be denied any command that names it (`references/security.md`).
- `~/.claude/jadlis/mail/config.json` — jm's own settings (below).
- `~/.claude/jadlis/mail/profile.md` — optional free-form owner notes the skill reads (path: `config.json → profile`).
- `~/.config/jadlis/agent.conf` — optional shared agent settings; `mail-wait.sh` reads `MAIL_ACCOUNT` and `MAIL_FOLDER` from it.

No file holds a password: every himalaya block reads it with `password.command = "printenv JM_SECRET_<ACCOUNT>"`, and jm sets that variable only for its own himalaya child, from the account's `secret` command.

## himalaya blocks

```toml
# ~/.config/himalaya/personal.toml — one block per account; the block name is the jm account name
[accounts.gmail-work]
email = "me@example.com"
display-name = "Me"
imap.server = "imaps://imap.gmail.com:993"
imap.sasl.plain.username = "me@example.com"
imap.sasl.plain.password.command = "printenv JM_SECRET_GMAIL_WORK"

[accounts.proton]
email = "me@example.com"
imap.server = "imap://127.0.0.1:1143"
imap.starttls = true
imap.tls.cert = "{{HOME}}/.config/himalaya/proton-bridge-cert.pem"
imap.sasl.plain.username = "me@example.com"
imap.sasl.plain.password.command = "printenv JM_SECRET_PROTON"
```

`send.toml` repeats each account with its SMTP block only (`smtp.server`, `smtp.starttls` where needed, the same username, `smtp.sasl.plain.password.command = "printenv JM_SECRET_<ACCOUNT>"`). The variable name is `JM_SECRET_` + the account name in upper case with every other character turned into `_`.

## config.json

```json
{
  "accounts": {
    "gmail-work": {
      "enabled": true, "short": "gw", "provider": "gmail", "email": "me@example.com",
      "aliases": [], "display_name": "Me", "role": "work: clients and invoices",
      "secret": ["security", "find-generic-password", "-s", "jm-gmail-work", "-a", "me", "-w"],
      "track": ["inbox", "spam"],
      "folders": {"newsletters": "Рассылки", "notifications": "Уведомления"},
      "save_sent": false, "digest_senders": false, "mail_dir": "<Apple Mail account folder, optional>"
    }
  },
  "protected": {"domains": ["corp.example"], "addresses": [], "recipient_locals": ["contact"], "subject_words": []},
  "vip": ["boss@example.com", "@lawfirm.example"],
  "rules": [{"from": "*@linkedin.com", "hint": "notifications"}],
  "profile": "~/.claude/jadlis/mail/profile.md",
  "mail_wait": {"account": "gmail-work", "folder": ""}
}
```

| Key | Meaning |
|---|---|
| `short` | two-letter key prefix (`gw-1a2b3c4d`) |
| `provider` | `icloud`, `gmail`, `proton` or anything else — switches provider quirks |
| `email`, `aliases`, `send_as` | the account's address (the From of every draft); `aliases` — its other addresses (iCloud `@me.com`/`@mac.com`), never taken for Hide My Email; `send_as` — extra From addresses `jm send` accepts |
| `role` | one line about what the mailbox is for — the skill uses it in triage and the digest |
| `secret` | argv of a command that prints the app password on stdout: macOS Keychain (`security … -w`), 1Password (`op read op://<vault>/<item>/password`) or any wrapper. Run without a shell; `~` is expanded |
| `track` | boxes the triage window reads |
| `save_sent` | put a copy into Sent after a send (iCloud needs it; Gmail and Proton do it themselves) |
| `digest_senders` | the digest names the senders of mail moved out of this inbox instead of a number (sensitive inboxes, e.g. banks) |
| `mail_dir` | the account's folder under `~/Library/Mail/V10/` (a UUID) — enables the fast local search index |
| `protected` | mail jm never queues or moves: sender/recipient domains (with subdomains, globs allowed), exact addresses or globs, recipient local parts (`contact`, `billing-*`), subject words |
| `vip` | addresses or `@domain`s whose mail only gets `keep` or `flag` and is never archived |
| `rules` | sender globs → a triage hint |
| `profile` | path of the owner's notes (default `~/.claude/jadlis/mail/profile.md`) |
| `mail_wait` | defaults for `mail-wait.sh` when `agent.conf` does not set them |

## Add an account

Prerequisites: `brew install himalaya jq python@3.13` (jm runs on `/opt/homebrew/bin/python3.13`); `ln -s "<plugin>/scripts/jm" ~/.local/bin/jm`; for Proton, Proton Mail Bridge signed in and its TLS certificate exported (Bridge → Settings → Advanced settings → Export TLS certificates).

1. The owner creates the app password and stores it where the `secret` command will read it (Keychain or a password manager) — never in the chat.
2. Add the himalaya IMAP block (and the SMTP block in `send.toml`) and the `config.json` entry.
3. `jm preflight --acct <name> --create-folders` — folders listed, the newsletters and notifications folders exist, MOVE and UIDPLUS reported.
4. `jm window --acct <name> --dry-run` — the first window reads the last 30 days only.
5. Optional: set `mail_dir` for the local index and run `jm index --acct <name>`.
