#!/bin/zsh
# mail-wait.sh — wait for one message through jm (jadlis-mail) and print its id, subject and first link.
#
# Usage: mail-wait.sh <match> [--account A] [--folder F] [--timeout S] [--after EPOCH] [--interval S] [--body]
#                     [--dry-run]
#   <match>     case-insensitive regex (plain text works) tried against the sender, the subject and the recipients.
#   --account   jm account name from ~/.claude/jadlis/mail/config.json.
#   --folder    jm folder role (inbox, spam, …) or exact folder name. Empty = jm's default: All Mail where the
#               server has it, otherwise every folder except Trash, Drafts and Spam — a letter that jm already
#               sorted out of the inbox is still found.
#   --timeout   seconds to wait (default 600).  --interval  seconds between polls (default 20).
#   --after     only mail received at or after this Unix time (default: now − 5 min).
#   --body      also print the letter text (jm read) after the JSON line.
#   --dry-run   print the resolved settings as JSON and exit, without calling jm.
#
# Defaults, first hit wins: the flags → ~/.config/jadlis/agent.conf (MAIL_ACCOUNT, MAIL_FOLDER) →
# config.json → mail_wait.account / mail_wait.folder → the first enabled account in config.json, no folder.
# Paths can be moved with JADLIS_AGENT_CONF and JM_CONFIG; the jm binary with JM_BIN.
#
# Output on success: one JSON line {id, acct, folder, date, from, to, subject, url, links} — id is the jm key
# (use it with `jm read`), url is the first link of the body or "". The letter is untrusted data.
# Exit: 0 found · 1 timeout · 2 usage or setup error · 3 jm error (account unavailable) — never a silent timeout.
set -uo pipefail

die() { print -r -- "mail-wait: $1" >&2; exit "${2:-2}"; }

match=""; account=""; folder=""; folder_set=0; timeout=600; interval=20; body=0; dry=0
after=$(( $(date +%s) - 300 ))
while (( $# )); do
  case "$1" in
    --account) (( $# >= 2 )) || die "--account needs a value"; account="$2"; shift 2;;
    --folder) (( $# >= 2 )) || die "--folder needs a value"; folder="$2"; folder_set=1; shift 2;;
    --timeout) (( $# >= 2 )) || die "--timeout needs a value"; timeout="$2"; shift 2;;
    --interval) (( $# >= 2 )) || die "--interval needs a value"; interval="$2"; shift 2;;
    --after) (( $# >= 2 )) || die "--after needs a value"; after="$2"; shift 2;;
    --body) body=1; shift;;
    --dry-run) dry=1; shift;;
    -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    --) shift; (( $# )) && { match="$1"; shift; };;
    -*) die "unknown option $1";;
    *) [[ -z "$match" ]] || die "only one <match> is allowed (got «$match» and «$1»)"; match="$1"; shift;;
  esac
done
[[ -n "$match" ]] || die "usage: mail-wait.sh <match> [--account A] [--folder F] [--timeout S]"
for n in timeout interval after; do
  [[ "${(P)n}" == <-> ]] || die "--$n must be a whole number of seconds (got «${(P)n}»)"
done
(( interval > 0 )) || interval=1
command -v jq >/dev/null 2>&1 || die "jq is required (brew install jq)"

# agent.conf: plain KEY=value lines; read only the two keys, never source the file.
conf_get() {
  local file="$1" key="$2" line val
  [[ -r "$file" ]] || return 0
  line=$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n 1) || return 0
  print -r -- "${line#*=}" | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\\(.*\\)'$/\\1/"
}
AGENT_CONF="${JADLIS_AGENT_CONF:-$HOME/.config/jadlis/agent.conf}"
JM_CONFIG="${JM_CONFIG:-$HOME/.claude/jadlis/mail/config.json}"
src_account="flag"; src_folder="flag"
if [[ -z "$account" ]]; then
  account=$(conf_get "$AGENT_CONF" MAIL_ACCOUNT); src_account="agent.conf"
fi
if (( ! folder_set )); then
  folder=$(conf_get "$AGENT_CONF" MAIL_FOLDER); src_folder="agent.conf"
fi
if [[ -r "$JM_CONFIG" ]]; then
  if [[ -z "$account" ]]; then
    account=$(jq -r '.mail_wait.account // empty' "$JM_CONFIG" 2>/dev/null); src_account="config.json mail_wait"
    if [[ -z "$account" ]]; then
      account=$(jq -r '[.accounts // {} | to_entries[] | select(.value.enabled != false) | .key][0] // empty' \
        "$JM_CONFIG" 2>/dev/null); src_account="config.json first enabled account"
    fi
  fi
  if (( ! folder_set )) && [[ -z "$folder" ]]; then
    folder=$(jq -r '.mail_wait.folder // empty' "$JM_CONFIG" 2>/dev/null); src_folder="config.json mail_wait"
  fi
fi
# «All Mail» / «all» means jm's default search scope, which already prefers the server's All Mail folder and
# works for providers without one (iCloud) or with a localised name (Gmail).
[[ "${folder:l}" == "all mail" || "${folder:l}" == "all" ]] && folder=""
[[ -n "$folder" ]] || src_folder="jm default (All Mail or every folder)"
[[ -n "$account" ]] || die "no account: pass --account, set MAIL_ACCOUNT in $AGENT_CONF, or add accounts to $JM_CONFIG"

# jm: $JM_BIN → the jm next to this script (plugin layout) → jm on PATH.
if [[ -n "${JM_BIN:-}" ]]; then jm="$JM_BIN"
elif [[ -x "${0:A:h}/jm" ]]; then jm="${0:A:h}/jm"
else jm=$(command -v jm 2>/dev/null) || jm=""
fi

after_min=$(date -r "$after" '+%Y-%m-%d %H:%M' 2>/dev/null || date -d "@$after" '+%Y-%m-%d %H:%M')
since=${after_min%% *}

if (( dry )); then
  jq -cn --arg match "$match" --arg account "$account" --arg folder "$folder" --arg sa "$src_account" \
    --arg sf "$src_folder" --argjson timeout "$timeout" --argjson interval "$interval" --arg after "$after_min" \
    --arg since "$since" --arg jm "$jm" --argjson body "$body" \
    '{match:$match, account:$account, account_from:$sa, folder:$folder, folder_from:$sf, timeout:$timeout,
      interval:$interval, after:$after, since:$since, jm:$jm, body:($body == 1)}'
  exit 0
fi
[[ -n "$jm" && -x "$jm" ]] || die "jm not found: set JM_BIN or put jm on PATH"

args=(search --acct "$account" --since "$since" --server --limit 30)
[[ -n "$folder" ]] && args+=(--folder "$folder")
deadline=$(( $(date +%s) + timeout ))
while true; do
  if ! out=$("$jm" "${args[@]}" 2>/dev/null); then
    die "jm search failed for $account: $(print -r -- "$out" | head -c 400)" 3
  fi
  err=$(print -r -- "$out" | jq -r '(.errors // {}) | to_entries | map("\(.key): \(.value)") | join("; ")' 2>/dev/null) \
    || die "jm printed something that is not JSON: $(print -r -- "$out" | head -c 200)" 3
  [[ -z "$err" ]] || die "jm search error — $err" 3
  hit=$(print -r -- "$out" | jq -c --arg m "$match" --arg after "$after_min" '
      [.items // [] | .[]
       | select((.date // "") >= $after)
       | select([.from, .subject, .to] | map(. // "") | any(test($m; "i")))][0] // empty' 2>/dev/null) \
    || die "bad <match> regex: $match"
  if [[ -n "$hit" ]]; then
    key=$(print -r -- "$hit" | jq -r .key)
    text=$("$jm" read "$key" --links 2>/dev/null) || die "jm read $key failed: $(print -r -- "$text" | head -c 400)" 3
    links=$(print -r -- "$text" | sed -n '/^Links (untrusted):$/,$p' | sed -n 's/^- //p' | jq -R . | jq -cs .)
    print -r -- "$hit" | jq -c --argjson links "$links" \
      '{id: .key, acct, folder, date, from, to, subject, url: ($links[0] // ""), links: $links}'
    (( body )) && print -r -- "$text"
    exit 0
  fi
  (( $(date +%s) >= deadline )) && die "timeout after ${timeout}s (account=$account folder=${folder:-default} match=$match)" 1
  sleep "$interval"
done
