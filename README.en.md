[Русский](README.md) · English

# jadlis-mail

Mail for Claude Code: your mailboxes over IMAP through himalaya — iCloud, Gmail, Proton through Proton Mail Bridge, or any other IMAP server.

```
claude plugin marketplace add https://github.com/beCyborg/jadlis-hub.git
claude plugin install jadlis-mail@jadlis
```

## Why

Claude sorts the inbox, finds letters and attachments, waits for the letter you need and drafts replies. It sends only what you confirmed. It verifies every move, and «undo» reverses a whole sort.

## What it looks like

A digest: important letters with a proposed action, «sorted N — say undo», «archived N», open watches.

## Install

You need macOS, Claude Code and Homebrew.

1. Install the plugin with the commands above and the tools: `brew install himalaya jq python@3.13`.
2. Put `jm` on PATH. This wrapper always runs the newest installed version of the plugin:

   ```sh
   mkdir -p ~/.local/bin && cat > ~/.local/bin/jm <<'EOF'
   #!/bin/sh
   exec "$(ls -td "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/jadlis/jadlis-mail/*/scripts/jm | head -1)" "$@"
   EOF
   chmod +x ~/.local/bin/jm
   ```

3. Create an app password for every mailbox: iCloud — appleid.apple.com, Gmail — myaccount.google.com/apppasswords, Proton — the mailbox password Bridge shows. Store it in the Keychain or a password manager, never in the chat.
4. Describe the mailboxes for himalaya: IMAP in `~/.config/himalaya/config.toml` or `personal.toml`, SMTP in `send.toml`. No file holds a password: `password.command = "printenv JM_SECRET_<ACCOUNT>"`. Samples are in [skills/mail/references/accounts.md](skills/mail/references/accounts.md).
5. Create `~/.claude/jadlis/mail/config.json`:

   ```json
   {
     "accounts": {
       "gmail-work": {
         "enabled": true, "short": "gw", "provider": "gmail", "email": "me@example.com",
         "display_name": "Me", "role": "work: clients and invoices",
         "secret": ["security", "find-generic-password", "-s", "jm-gmail-work", "-a", "me", "-w"],
         "track": ["inbox", "spam"],
         "folders": {"newsletters": "Newsletters", "notifications": "Notifications"},
         "save_sent": false
       }
     },
     "protected": {"domains": [], "addresses": [], "recipient_locals": [], "subject_words": []},
     "vip": ["boss@example.com"],
     "rules": [{"from": "*@linkedin.com", "hint": "notifications"}]
   }
   ```

   `secret` is a command that prints the password: here the macOS Keychain; `op read op://…` from 1Password works too.
6. Check: `jm preflight --create-folders`, then `jm window --dry-run`.
7. Optional: your own triage notes in `~/.claude/jadlis/mail/profile.md` — which topics and senders matter now, how to write the digest. The skill reads the file when it exists. The `profile` key in `config.json` moves it.

## Send gate

The plugin's hook `hooks/send_gate.py` is on by itself. Add the permission rules to `~/.claude/settings.json` by hand: `ask` makes Claude Code ask you before every `jm send` in every mode, `deny` blocks sending around jm.

```json
{
  "permissions": {
    "ask": ["Bash(*jm send*)"],
    "deny": [
      "Bash(himalaya message send*)",
      "Bash(himalaya * message send*)",
      "Bash(himalaya * --send*)",
      "Bash(himalaya smtp *)",
      "Bash(himalaya * smtp *)",
      "Bash(*send.toml*)",
      "Bash(*smtplib*)"
    ]
  }
}
```

If the file already has `permissions`, add the lines to the existing lists. A letter goes out only when you answer «yes» to the prompt with the draft's code and hash. Details — [skills/mail/references/security.md](skills/mail/references/security.md).

## Waiting for a letter from a script

`scripts/mail-wait.sh` waits for a confirmation letter, for example after a sign-up on a service:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/mail-wait.sh" "shop.example" --account gmail-work --timeout 600
```

It prints one JSON line: the letter's key `id`, its `subject` and the first link `url`. Exit code 1 means timeout, 3 a mailbox error. The default mailbox and folder come from `~/.config/jadlis/agent.conf` (`MAIL_ACCOUNT`, `MAIL_FOLDER`), then from `config.json` (`mail_wait`), then the first enabled mailbox. Without a folder it searches all mail, so a letter that triage already moved is still found. `--dry-run` prints the resolved settings and leaves the mail alone.

## Use

"What's in my mail", "sort my inbox", "find the email from …", "I'm waiting for a letter from …", "reply …", "send it", "undo".

## Limits and cost

Free. Needs a Mac: jm runs on Homebrew's Python, and fast search reads Apple Mail's copy. The send gate stops a misled model, not a hostile one — [skills/mail/references/security.md](skills/mail/references/security.md).
