# Changelog — jadlis-mail

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

## [0.4.0] — 2026-11-16 — jm на Linux / jm on Linux

### Для человека
- jm работает на сервере с Linux: та же почта, поиск и черновики, что на Mac. На Mac ничего не меняется.

### For agents
- Changed: `scripts/jm` starts through `/bin/sh`: Homebrew `python3.13 -I` when present (macOS, as before), else `python3 -I` from `PATH`.
- Changed: himalaya path = `JM_HIMALAYA` → `/opt/homebrew/bin/himalaya` on macOS → `PATH` → `~/.local/bin/himalaya`.
- Changed: on Linux `ensure_bridge` starts the `systemd --user` unit `proton-bridge.service` (`JM_BRIDGE_UNIT`) instead of `open -a`.
- Added: `config.json` → `timezone` (IANA) sets `TZ` when the environment has none.
- Docs: `references/accounts.md` § Linux. Tests: `tests/test_jadlis_mail_linux.py`.

## [0.3.1] — 2026-11-07 — `2>&1` в конце отправки / trailing `2>&1` on send

### Для человека
- Отправка больше не срывается, если агент по привычке дописал к команде `2>&1`.

### For agents
- Changed: `hooks/send_gate.py` CANON accepts an optional trailing ` 2>&1`; any other suffix (pipes, `;`, `&&`) still finds no ticket. `SKILL.md` rule 3 says so. Tests: 13j.

## [0.3.0] — 2026-11-07 — режим отправки по политике / policy send mode

### Для человека

- Новая опция `send_confirmation`: `always` (как раньше, по умолчанию) или `policy` — автономный агент отправляет письмо сам, по правилам своей политики, без запроса.
- В режиме `policy` проверка хеша черновика, отправителя и Hide My Email остаётся; убери только правило `ask` для `jm send`.

### For agents

- Added: `userConfig.send_confirmation` (`options: always|policy`, default `always`; needs Claude Code 2.1.271+).
- Changed: `hooks/send_gate.py` — with `CLAUDE_PLUGIN_OPTION_SEND_CONFIRMATION=policy` it writes the same ticket and returns `permissionDecision: allow`; any other value asks as before.
- Changed: `skills/mail/SKILL.md` hard rule 3 branches on `${user_config.send_confirmation}`; `references/security.md` and both READMEs describe the mode.
- Migration: none for `always`. For `policy`: `claude plugin uninstall jadlis-mail@<m>` → `claude plugin install jadlis-mail@<m> --config send_confirmation=policy`, remove `Bash(*jm send*)` from `permissions.ask`.
- Tests: `tests/test_jadlis_mail_gate.py` 13g–13i.

## [0.2.0] — 2026-11-03 — публичная версия и mail-wait.sh / public release and mail-wait.sh

### Для человека

- Плагин стал общим: ящики, роли, защищённые адреса и VIP описаны только в твоём `config.json`, в самом плагине личных данных нет.
- Свои заметки для разбора почты можно положить в `~/.claude/jadlis/mail/profile.md` — скилл читает их, если файл есть.
- `mail-wait.sh` ждёт письмо с подтверждением и печатает его ключ, тему и первую ссылку — для регистраций и других скриптов.
- В README есть готовый блок правил для `~/.claude/settings.json`: Claude Code спрашивает перед каждой отправкой, обход jm закрыт.

### For agents

- Added: `scripts/mail-wait.sh <match> [--account A] [--folder F] [--timeout S] [--after EPOCH] [--interval S] [--body] [--dry-run]` — polls `jm search --server`, matches sender/subject/recipients (case-insensitive regex), prints `{id, acct, folder, date, from, to, subject, url, links}`; exit 0 found, 1 timeout, 2 usage, 3 jm error. Defaults: flags → `~/.config/jadlis/agent.conf` `MAIL_ACCOUNT`/`MAIL_FOLDER` → `config.json → mail_wait` → first enabled account. `JM_BIN`, `JM_CONFIG`, `JADLIS_AGENT_CONF` override paths.
- Added: `jm profile` — no network; accounts with `email`/`provider`/`role`/`digest_senders`/`enabled` and the owner profile path (`config.json → profile`, default `~/.claude/jadlis/mail/profile.md`) with `exists`.
- Changed: `jm search` items carry `to`.
- Changed: skill and references are provider-generic (any IMAP account from `config.json`); personal account tables, triage specifics and sender lists moved out of the repo.
- Changed: `plugin.json` — version 0.2.0, GitLab homepage/repository, `author: Be Cyborg`; `.gitlab-ci.yml` includes the hub CI.
- Kept: `hooks/hooks.json` registers `send_gate.py`; README shows the `permissions.ask`/`deny` snippet.
- Tests: `tests/test_jadlis_mail_wait.py` (fake jm, no network); fixtures use `*.example` addresses.

## [0.1.2] — 2026-10-16 — быстрый поиск и Inbox Zero / fast search and Inbox Zero

### Для человека
- Поиск по всей почте за 1–3 секунды, с кириллицей и «ё», по копии, которую Почта уже скачала на Mac.
- Прочитанное без флажка, не от VIP, старше 7 дней само уходит в «Архив»; «верни» откатывает.

### For agents
- Added: `jm index` (SQLite FTS5 over Apple Mail's `.emlx`, `config.json → accounts.*.mail_dir`), used by `jm search` for indexed accounts; `--server` forces IMAP.
- Added: `jm archive [--days 7] [--run R]` — read, unflagged, non-VIP, unprotected inbox mail → Archive (Gmail: All Mail).
- Fixed: `addresses()` parses IMAP envelope form `a@b <a@b>` (protection of recipient-local patterns was missed on envelope-only paths).

## [0.1.1] — 2026-10-15 — пятый ящик и перенос в iCloud / fifth mailbox, iCloud moves

### Для человека
- Подключён пятый ящик.
- В iCloud нет команды переноса — jm копирует, проверяет копию и только потом убирает оригинал.

### For agents
- Added: a fifth account in the owner's `config.json`; `Account.move(..., mids)` falls back to COPY → verify → UID EXPUNGE without MOVE.
- Changed: `consume_ticket` binds tickets to `CLAUDE_CODE_SESSION_ID`; `safe_mid` accepts bare Message-IDs ≥16 chars.

## [0.1.0] — 2026-10-15 — первая версия: разбор, поиск, черновики, отправка через подтверждение / first release: triage, search, drafts, gated send

### Для человека
- Claude сам раскладывает входящие iCloud, двух Gmail и Proton по «Рассылкам», «Уведомлениям» и «Спаму», важное помечает флажком; «верни» откатывает.
- Поиск писем и вложений по всем ящикам, «жду письмо» между сессиями, черновики прямо в «Черновиках» Почты.
- Письмо уходит только после твоего «да» в запросе Claude Code на этот черновик — с Mac или с телефона.

### For agents
- Added: `scripts/jm` (preflight, window, apply, ack, search, read, attach, undo, draft, send, watch); state in `~/.claude/jadlis/mail/`.
- Added: `hooks/send_gate.py` — PreToolUse(Bash) ticket + `ask` for the canonical `jm send <code> --hash <h>`.
- Added: `skills/mail/` with `references/{accounts,triage-policy,cookbook,security}.md`; tests in `tests/`.
