# himalaya 2.2.1 cookbook — commands and JSON shapes

Exact CLI calls and `--json` output shapes of himalaya v2.2.1, checked live against Proton Mail Bridge (account `proton`) on 2026-10-15.
`jm` wraps all of this; use raw himalaya only for read-only ad-hoc checks.

## Global flags

| Flag | Meaning |
|---|---|
| `-c a.toml:b.toml` | Config paths, `:`-separated like `$PATH`; the first is the base, later files override its keys. Env `HIMALAYA_CONFIG`. |
| `-a <account>` | Account name (a root table of the TOML). Omitted → the `default = true` account. |
| `--json` | JSON output for data AND errors. There is no `--output json`. |
| `-b <backend>` | Pin a shared command (`envelope`, `message`, …) to `imap`/`jmap`/…; default `auto`. |
| `--log-level trace --log-file <path>` | Debug the IMAP dialogue (the log holds message bodies — delete it after). |

Flags can go before or after the subcommand. v2 renamed folders: `mailbox list`, not `folder list`.

## Task → command

| Task | Command |
|---|---|
| List mailboxes (role names) | `himalaya mailbox list --json` (`--counts` adds total/unread, one STATUS per box) |
| List mailboxes (attributes) | `himalaya imap list --json` — the only way to find Junk/Archive/All/Flagged |
| Counts, UIDVALIDITY, UIDNEXT | `himalaya imap status INBOX --json` (mailbox is positional) |
| Newest envelopes | `himalaya envelope list -m INBOX --page-size 20 --page 1 --json` |
| Filtered envelopes | `himalaya envelope search -m INBOX --page-size 50 --json 'after 2026-10-14 and not flag seen'` |
| UIDs by criteria | `himalaya imap search -m INBOX --since 2026-10-14 --unseen --from example.com --json` |
| UIDs sorted | `himalaya imap sort -m INBOX -S arrival -r --since 2026-10-14 --json` |
| Envelope/flags/size by UID | `himalaya imap fetch -m INBOX --envelope --flags --internal-date --size 421,425:430 --json` |
| MIME tree by UID | `himalaya imap fetch -m INBOX --structure 421 --json` |
| Raw RFC 5322 (base64) | `himalaya imap fetch -m INBOX --body 421 --json` → `.messages[0].body` |
| Read a message (parsed) | `himalaya message read 421 -m INBOX --json` (no `--seen` → flags untouched) |
| Read a message (raw) | `himalaya message read 421 --raw --json` → one JSON string |
| List attachments | `himalaya attachment list 421 -m INBOX --json` (`-i` adds inline parts) |
| Save attachments | `himalaya attachment download 421 3 -d /path/dir --json` (part ids after the message id) |
| Allowed flags of a box | `himalaya imap flag INBOX --json` |
| Find UID by Message-ID | `himalaya imap raw -- 'a1 EXAMINE "INBOX"\r\na2 UID SEARCH HEADER Message-ID "<id@example.com>"\r\n'` |

### Envelope search DSL (`envelope search [QUERY]...`)

- Conditions: `date <yyyy-mm-dd>`, `after <yyyy-mm-dd>`, `from <pat>`, `to <pat>`, `subject <pat>`, `body <pat>`, `flag <seen|answered|flagged|draft>`.
- Combine with `and`, `or`, `not`, parentheses. Sort: `order by <date|from|to|subject> [asc|desc]`.
- Patterns are case-insensitive substrings; quote a pattern with spaces: `'subject "invoice march"'`.
- The query may be one quoted string or several words; both parse the same.
- There is NO `before` clause (parse error). Use `not after X` (includes day X) or `imap search --before`.
- `after X` is strict: it starts at day X+1. `date X` is that one day.

### `imap search` / `imap sort` criteria

`--from --to --cc --bcc --subject --body --text <TEXT>`, `--before --since --on <YYYY-MM-DD>`, `--larger --smaller <BYTES>`, `--seen --unseen --flagged --unflagged --answered --unanswered --deleted --undeleted --draft --undraft --new --old --recent`, `--seq`. Several flags are ANDed; none = all. No header search: use `imap raw` for Message-ID.

## JSON shapes (synthetic values)

`mailbox list` — `id` equals `name` on IMAP; `role` is set only for inbox/sent/drafts/trash on Bridge; `\Noselect` boxes are omitted:
```json
{"mailboxes":[{"id":"INBOX","name":"INBOX","role":"inbox","total":null,"unread":null}]}
```

`imap list` — names come back decoded (Cyrillic as UTF-8), `\Noselect` parents included:
```json
{"mailboxes":[{"name":"Spam","delimiter":"/","attributes":["\\Junk","\\Noinferiors","\\Unmarked"]},
              {"name":"Folders/Проекты","delimiter":"/","attributes":["\\Unmarked"]}]}
```

`imap status` — unsupported items are `null`:
```json
{"messages":462,"recent":0,"uid_next":463,"uid_validity":123456789,"unseen":56,
 "deleted":null,"deleted_storage":null,"highest_mod_seq":null}
```

`envelope list` / `envelope search` — an OBJECT, not a bare list; kebab-case keys; `id` is a STRING (the IMAP UID):
```json
{"queued":0,
 "envelopes":[{"id":"421","flags":[{"raw":"\\Seen","iana":"seen"}],
   "subject":"Invoice 42","from":[{"name":"Alice","email":"alice@example.com"}],
   "to":[{"name":null,"email":"me@example.com"}],"date":"2026-10-14T16:59:59-07:00",
   "message-id":"abc123@example.com","in-reply-to":[],"size":16912,"has-attachment":null}]}
```
jq: `.envelopes[] | {id, from: .from[0].email, seen: (.flags | map(.iana) | index("seen") != null)}`.

`imap search` — ids are objects, ascending:
```json
{"uid_mode":true,"ids":[{"id":422},{"id":423}]}
```
jq: `[.ids[].id]`. With `--seq` → `"uid_mode":false` and message numbers.

`imap sort` — ids are bare integers, in sort order:
```json
{"uid_mode":true,"ids":[462,461,460]}
```

`imap fetch` — every key is present; items not asked for are `null` (`uid` is always fetched):
```json
{"messages":[{"seq":421,"uid":421,"flags":["\\Seen"],"internal_date":"2026-10-13T19:23:37+00:00","size":16646,
  "envelope":{"date":"Tue, 13 Oct 2026 19:23:31 +0000","subject":"Invoice 42",
    "message_id":"<abc123@example.com>","in_reply_to":null,
    "from":["Alice <alice@example.com>"],"sender":["Alice <alice@example.com>"],
    "reply_to":["Alice <alice@example.com>"],"to":["me@example.com"],"cc":[],"bcc":[]},
  "structure":{"content_type":"multipart/mixed","name":null,"size":null,"parts":[
    {"content_type":"text/html","name":null,"size":921,"parts":[]},
    {"content_type":"application/gzip","name":"report.gz","size":723,"parts":[]}]},
  "body":null}]}
```
`--body` alone gives `"body":"<base64 of the whole RFC 5322 message>"` and `"envelope":null`.

`message read --json` — the parsed message tree (mail-parser), not a flat view:
```json
{"text_body":[1],"html_body":[1],"attachments":[2],
 "parts":[{"headers":[{"name":"subject","value":{"Text":"Invoice 42"}},
                      {"name":"from","value":{"Address":{"List":[{"name":"Alice","address":"alice@example.com"}]}}},
                      {"name":{"other":"X-Custom"},"value":{"Text":"..."}}],
           "body":{"Multipart":[1,2]},"is_encoding_problem":false},
          {"headers":[],"body":{"Html":"<p>...</p>"}},
          {"headers":[],"body":{"Binary":[31,139,8]}}]}
```
`text_body`/`html_body`/`attachments` are indexes into `parts`. Body variants: `Text`, `Html`, `Binary` / `InlineBinary` (byte array), `Multipart` (child indexes), `Message`. Header `name` is a snake_case string for known headers, `{"other":"X-…"}` otherwise. `date` is `{"DateTime":{"year":…,"tz_hour":…}}`.

`attachment list` — `id` is a STRING, 1-based part position (= `parts` index + 1), sparse:
```json
{"attachments":[{"id":"3","filename":"report.gz","mime":"application/gzip","size":723,"inline":false,"path":null}]}
```
`attachment download` fills `path`.

`imap flag INBOX` (Bridge: no `\Answered`, no `\Draft`):
```json
{"flags":["$Forwarded","Forwarded","\\Deleted","\\Flagged","\\Seen"],"permanent_flags":["..."]}
```

`imap raw --json` — the verbatim server text in one string:
```json
{"message":"* OK [UIDVALIDITY 123456789]\r\na1 OK [READ-ONLY] EXAMINE\r\n* SEARCH 421\r\na2 OK command completed\r\n"}
```

Errors under `--json` — printed on STDOUT, exit code 1:
```json
{"error":"IMAP SELECT failed: NO no such mailbox","sources":[],"backtrace":null}
```
Argument errors (bad flag, bad date) are plain text on stderr, exit code 2, never JSON.

## Traps

1. Three address shapes. `envelope list/search`: objects `{"name","email"}` (key `email`, never `addr`). `imap fetch`: strings `"Name <addr>"` or a bare `"addr"`. `message read`: `{"name","address"}` inside `Address.List`.
2. `envelope list/search` return `{"envelopes":[...],"queued":0}`. Never treat the output as a bare list.
3. Envelope `flags` are objects `{"raw","iana"}`; `imap fetch` flags are plain strings like `"\\Seen"`. Unread = no `seen` in `iana`.
4. Message-ID: envelope `message-id` has NO angle brackets; `imap fetch` `message_id` HAS them. `UID SEARCH HEADER Message-ID` matches either form.
5. Dates: envelope `date` is RFC 3339 with the sender's offset (`Z` or `-07:00`) — normalise before comparing. `imap fetch` `envelope.date` is the raw RFC 2822 header; `internal_date` is RFC 3339 receive time.
6. `imap search/sort/thread` dates are `YYYY-MM-DD`; IMAP style `14-Oct-2026` fails with exit 2.
7. `imap fetch` takes UIDs by default; `--seq` switches to message numbers. A missing UID returns `{"messages":[]}` with exit 0 — check the length.
8. Read-only reads: `imap fetch --body`, `message read` (without `--seen`) and `attachment list` all fetch with `BODY.PEEK` (trace log: `peek: true`). They do not set `\Seen`.
9. `-m <role>` resolves only roles the backend reports. On Bridge: `inbox`, `sent`, `drafts`, `trash`. `-m junk|archive|all|flagged` falls through as a literal name → `no such mailbox`. Find those boxes in `imap list` by attribute: `\All \Junk \Sent \Drafts \Trash \Archive \Flagged`.
10. Never match special folders by name. Gmail names are localized (`[Gmail]/Вся почта`, `[Gmail]/Спам`); Proton uses `Inbox`, `Spam`, `All Mail`, `Starred`, `Folders/…`, `Labels/…` (`-m INBOX` still works: INBOX is case-insensitive).
11. Structured commands (`imap status`, `envelope list -m`, `imap fetch -m`) take decoded UTF-8 names and encode them. In `imap raw`, a non-ASCII name must be modified UTF-7 (`Folders/JM-&BEIENQRBBEI-`).
12. `imap raw` sends bytes verbatim: give every command its own tag and `\r\n`. Tagged `NO`/`BAD` come back as output, not as an error — grep for `^aN OK`. Allowed here only: `EXAMINE` (read-only select), `UID SEARCH`, `UID FETCH … BODY.PEEK[...]`.
13. `imap search` has no header criterion; look up a Message-ID with `imap raw` (see the task table).
14. `imap thread` fails on Proton Bridge (`Decode IMAP response error`). Use `imap sort` or the envelope `in-reply-to` list.
15. `imap store` `-f/--flag` takes several values and swallows the next positional. Put the UID set first: `himalaya imap store 12 -m INBOX --action add --flag '\Flagged'`. Flags are raw tokens: `'\Seen'` is the system flag, bare `seen` stores a custom keyword.
16. `imap append <MAILBOX> -- <file>` needs the `--` separator before the message (path, inline text or stdin).
17. `imap move` / `message move --to <box>` report success for a UID that does not exist (also upstream issue #777 on Gmail). Verify every move: fetch the UID in the source and search the Message-ID in the target.
18. `mailbox list --counts` costs one STATUS per mailbox on IMAP; prefer `imap status <box>` for one box.
19. `envelope list --has-attachment` fills `has-attachment`; without it the field is `null`, not `false`.
20. `message read --json`: `text_body` may point at an `Html` part when the mail has no plain text (seen live: `text_body` and `html_body` both `[1]`). Read `parts[text_body[0]].body` and take `.Text // .Html`.
