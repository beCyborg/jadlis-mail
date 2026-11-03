Русский · [English](README.en.md)

# jadlis-mail

Почта для Claude Code: твои ящики по IMAP через himalaya — iCloud, Gmail, Proton через Proton Mail Bridge или любой другой IMAP.

```
claude plugin marketplace add https://gitlab.com/beCyborg/jadlis-hub.git
claude plugin install jadlis-mail@jadlis
```

## Зачем

Claude сам разбирает входящие, ищет письма и вложения, ждёт нужное письмо и готовит черновики. Отправляет только то, что ты подтвердил. Каждый перенос он проверяет, а «верни» откатывает весь разбор.

## Как выглядит

Дайджест: важное по пунктам с предложением действия, «разложено N — скажи «верни»», «в архив N», «ждём: …».

## Как поставить

Нужны macOS, Claude Code и Homebrew.

1. Поставь плагин командами выше и инструменты: `brew install himalaya jq python@3.13`.
2. Положи `jm` в PATH. Обёртка ниже всегда берёт последнюю установленную версию плагина:

   ```sh
   mkdir -p ~/.local/bin && cat > ~/.local/bin/jm <<'EOF'
   #!/bin/sh
   exec "$(ls -td "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/jadlis/jadlis-mail/*/scripts/jm | head -1)" "$@"
   EOF
   chmod +x ~/.local/bin/jm
   ```

3. Создай пароль приложения для каждого ящика: iCloud — appleid.apple.com, Gmail — myaccount.google.com/apppasswords, Proton — пароль ящика в Bridge. Сохрани его в Связку ключей или в менеджер паролей, не в чат.
4. Опиши ящики для himalaya: IMAP в `~/.config/himalaya/config.toml` или `personal.toml`, SMTP в `send.toml`. Пароль в файлах не хранится: `password.command = "printenv JM_SECRET_<ACCOUNT>"`. Образцы — в [skills/mail/references/accounts.md](skills/mail/references/accounts.md).
5. Создай `~/.claude/jadlis/mail/config.json`:

   ```json
   {
     "accounts": {
       "gmail-work": {
         "enabled": true, "short": "gw", "provider": "gmail", "email": "me@example.com",
         "display_name": "Me", "role": "работа: клиенты и счета",
         "secret": ["security", "find-generic-password", "-s", "jm-gmail-work", "-a", "me", "-w"],
         "track": ["inbox", "spam"],
         "folders": {"newsletters": "Рассылки", "notifications": "Уведомления"},
         "save_sent": false
       }
     },
     "protected": {"domains": [], "addresses": [], "recipient_locals": [], "subject_words": []},
     "vip": ["boss@example.com"],
     "rules": [{"from": "*@linkedin.com", "hint": "notifications"}]
   }
   ```

   `secret` — команда, которая печатает пароль: здесь Связка ключей macOS, подойдёт и `op read op://…` из 1Password.
6. Проверь: `jm preflight --create-folders`, затем `jm window --dry-run`.
7. По желанию: свои заметки для разбора в `~/.claude/jadlis/mail/profile.md` — какие темы и отправители сейчас важны, как писать дайджест. Скилл читает файл, если он есть. Путь меняет ключ `profile` в `config.json`.

## Шлюз отправки

Хук плагина `hooks/send_gate.py` включается сам. Правила разрешений добавь вручную в `~/.claude/settings.json`: `ask` заставляет Claude Code спрашивать тебя перед каждым `jm send` в любом режиме, `deny` закрывает отправку в обход jm.

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

Если в файле уже есть `permissions`, допиши строки в существующие списки. Письмо уходит, только когда ты ответишь «да» на запрос с кодом и хешем черновика. Подробно — [skills/mail/references/security.md](skills/mail/references/security.md).

## Ожидание письма из скрипта

`scripts/mail-wait.sh` ждёт письмо с подтверждением, например после регистрации на сервисе:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/mail-wait.sh" "shop.example" --account gmail-work --timeout 600
```

Скрипт печатает одну строку JSON: ключ письма `id`, тему `subject` и первую ссылку `url`. Код выхода 1 значит «не дождался», 3 — ошибку ящика. Ящик и папку по умолчанию он берёт из `~/.config/jadlis/agent.conf` (`MAIL_ACCOUNT`, `MAIL_FOLDER`), потом из `config.json` (`mail_wait`), потом первый включённый ящик. Без папки ищет по всей почте, поэтому разобранное письмо тоже найдётся. `--dry-run` показывает итоговые настройки и почту не трогает.

## Как пользоваться

«Что с почтой», «разбери почту», «найди письмо от …», «жду письмо от …», «ответь …», «отправь», «верни».

## Границы и стоимость

Бесплатно. Нужен Mac: jm использует Python из Homebrew, а быстрый поиск читает копию Apple Mail. Шлюз отправки останавливает обманутую модель, но не враждебную — [skills/mail/references/security.md](skills/mail/references/security.md).
