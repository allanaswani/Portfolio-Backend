#!/usr/bin/env bash
# Turn PostgreSQL "trust" entries (no password asked) into md5, without
# locking out anything that works today. Run as root on a database host.
#
#   bash deploy/host/pg_trust_fix.sh check        read-only: trust entries, live use, do the apps' passwords work
#   bash deploy/host/pg_trust_fix.sh apply        remote ranges -> md5 (refused while anything connects from them)
#   bash deploy/host/pg_trust_fix.sh apply-local  127.0.0.1 -> md5 (refused unless every app password works)
#   bash deploy/host/pg_trust_fix.sh watch        failed password logins since the change
#   bash deploy/host/pg_trust_fix.sh rollback     pg_hba.conf back exactly as it was before the first change
#
# Why the password test matters: under trust the server never checks the
# password, so an app configured with a WRONG one works today and would stop
# the moment trust goes. The test logs each app in through a temporary md5
# entry on 127.0.0.2 (also loopback), then removes it. No password is printed.
set -uo pipefail
cd /

pg() { sudo -u postgres psql -X -At -c "$1"; }
PSQL="$(command -v psql || ls /usr/pgsql-*/bin/psql 2>/dev/null | tail -1)"
HBA="$(pg 'show hba_file')"
[ -n "$HBA" ] && [ -f "$HBA" ] || { echo "Cannot find pg_hba.conf (is PostgreSQL running?)"; exit 1; }
BACKUP="$HBA.before-trust-fix"
STAMP=/var/tmp/pg_trust_fix.applied_at
PROBE="host all all 127.0.0.2/32 md5 # pg_trust_fix probe"
ETL_DIRS="/data/apps/datascience/etls /data/apps/datascience/etls-recon"

# "line-number address" for every host* trust entry, replication excluded.
trust_lines() { awk '$1 ~ /^host/ && $2 != "replication" && $5 == "trust" {print NR" "$4}' "$HBA"; }
remote_trust() { trust_lines | awk '$2 != "127.0.0.1/32" && $2 != "::1/128" {print $2}'; }
local_trust()  { trust_lines | awk '$2 == "127.0.0.1/32" || $2 == "::1/128" {print $2}'; }
live_from() { pg "select count(*) from pg_stat_activity where client_addr is not null and client_addr <<= '$1'::inet"; }

no_password_logins() {
  pg "select '  '||rolname||case when rolsuper then '  (superuser)' else '' end
      from pg_authid where rolcanlogin and rolpassword is null order by 1"
}

env_get() {  # file key -> value, quotes stripped; empty when absent
  [ -f "$1" ] || return 0
  sed -n "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*//p" "$1" | tail -1 \
    | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

probe_on()  { grep -qF "pg_trust_fix probe" "$HBA" || sed -i "1i $PROBE" "$HBA"; pg 'select pg_reload_conf()' >/dev/null; }
probe_off() { sed -i '/pg_trust_fix probe/d' "$HBA"; pg 'select pg_reload_conf()' >/dev/null; }

try_login() {  # label user password db port
  local label="$1" user="$2" pass="$3" db="${4:-postgres}" port="${5:-5432}" err
  if [ -z "$user" ]; then echo "  SKIP  $label: not configured on this host"; return 0; fi
  if [ -z "$pass" ]; then
    echo "  FAIL  $label ($user): no password configured - it only connects because of trust"; return 1
  fi
  if err="$(PGPASSWORD="$pass" PGCONNECT_TIMEOUT=5 "$PSQL" -X -h 127.0.0.2 -p "$port" -U "$user" -d "$db" -Atc 'select 1' 2>&1 >/dev/null)"; then
    echo "  OK    $label ($user)"; return 0
  fi
  case "$err" in
    *"password authentication failed"*)
      echo "  FAIL  $label ($user): its configured password is WRONG - it only connects because of trust" ;;
    *) echo "  FAIL  $label ($user): could not test - $(printf '%s' "$err" | head -1)" ;;
  esac
  return 1
}

etl_creds() {  # dir -> user, password, db, port on four lines (into a pipe, never the screen)
  python3.6 - "$1" 2>/dev/null <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import app_settings as s
p = getattr(s, "postgres", None) or {}
print(p.get("user", ""))
print(p.get("password", ""))
print(p.get("db") or p.get("database") or p.get("dbname") or "datawarehouse")
print(p.get("port", 5432))
PY
}

app_passwords() {  # returns the number of failures
  local fails=0 f=/etc/hf/prod.env c=/etc/hf/c360.env d C
  probe_on
  trap probe_off EXIT
  # The backend's own defaults (config/settings/base.py) apply when a key is unset.
  if [ -f "$f" ]; then
    try_login "backend app DB (DB_*)" "$(env_get $f DB_USER)" "$(env_get $f DB_PASSWORD)" \
      "$(env_get $f DB_NAME)" "$(env_get $f DB_PORT)" || fails=$((fails + 1))
    local dwu dwn
    dwu="$(env_get $f DW_USER)"; dwn="$(env_get $f DW_NAME)"
    try_login "backend warehouse (DW_*)" "${dwu:-postgres}" "$(env_get $f DW_PASSWORD)" \
      "${dwn:-datawarehouse1}" "$(env_get $f DW_PORT)" || fails=$((fails + 1))
  else
    echo "  SKIP  backend: no $f"
  fi
  if [ -f "$c" ] && [ "$(env_get $c DB_ENGINE)" != "django.db.backends.sqlite3" ]; then
    try_login "Customer 360 (DB_*)" "$(env_get $c DB_USER)" "$(env_get $c DB_PASSWORD)" \
      "$(env_get $c DB_NAME)" "$(env_get $c DB_PORT)" || fails=$((fails + 1))
  fi
  for d in $ETL_DIRS; do
    [ -f "$d/app_settings.py" ] || continue
    mapfile -t C < <(etl_creds "$d")
    if [ "${#C[@]}" -lt 2 ]; then echo "  FAIL  ETLs $d: could not read its postgres settings"; fails=$((fails + 1)); continue; fi
    try_login "ETLs $d" "${C[0]}" "${C[1]}" "${C[2]:-datawarehouse}" "${C[3]:-5432}" || fails=$((fails + 1))
  done
  probe_off
  trap - EXIT
  return "$fails"
}

switch_to_md5() {  # addresses...
  [ -f "$BACKUP" ] || cp -p "$HBA" "$BACKUP"
  local tmp; tmp="$(mktemp)"
  awk -v want=" $* " '$1 ~ /^host/ && $2 != "replication" && $5 == "trust" && index(want, " "$4" ") {
      sub(/[[:space:]]trust/, " md5") } {print}' "$HBA" > "$tmp"
  cat "$tmp" > "$HBA"; rm -f "$tmp"            # cat keeps the file's owner and mode
  if [ "$(pg 'select count(*) from pg_hba_file_rules where error is not null')" != "0" ]; then
    cp -p "$BACKUP" "$HBA"
    echo "pg_hba.conf would not parse - put back as it was. Nothing changed."; exit 1
  fi
  pg 'select pg_reload_conf()' >/dev/null
  [ -f "$STAMP" ] || date +%s > "$STAMP"
}

case "${1:-check}" in
  check)
    echo "pg_hba.conf: $HBA"
    echo; echo "Trust entries (no password asked):"
    trust_lines | while read -r n addr; do
      echo "  line $n  $addr  - live connections now: $(live_from "$addr")"
    done
    echo; echo "Logins with NO password (cannot pass an md5 entry):"
    no_password_logins
    echo; echo "Do the apps' configured passwords really work?"
    if app_passwords; then echo; echo "All configured passwords work."
    else echo; echo "Fix the FAIL lines before apply-local."; fi
    echo "Not covered: Metabase (port 3000) and scripts with their own settings file - 'watch' shows them after apply-local."
    ;;
  apply)
    mapfile -t R < <(remote_trust)
    [ "${#R[@]}" -gt 0 ] || { echo "No remote trust entries."; exit 0; }
    for a in "${R[@]}"; do
      n="$(live_from "$a")"
      [ "$n" = "0" ] || { echo "REFUSED: $n live connection(s) from $a right now. Nothing changed."; exit 1; }
    done
    switch_to_md5 "${R[@]}"
    echo "Now asking for a password: ${R[*]}"
    echo "These logins have no password and can no longer connect from those ranges:"
    no_password_logins | grep -v "^  postgres  (superuser)$" || echo "  (none)"
    echo "Undo: bash $0 rollback"
    ;;
  apply-local)
    mapfile -t L < <(local_trust)
    [ "${#L[@]}" -gt 0 ] || { echo "No 127.0.0.1 trust entry."; exit 0; }
    echo "Testing every app's password first:"
    app_passwords || { echo; echo "REFUSED: fix the FAIL lines first. Nothing changed."; exit 1; }
    switch_to_md5 "${L[@]}"
    echo; echo "Now asking for a password: ${L[*]}"
    echo "Run 'bash $0 watch' a few times today and tomorrow morning after the night ETLs."
    echo "Undo: bash $0 rollback"
    ;;
  watch)
    dir="$(pg "select case when setting like '/%' then setting else current_setting('data_directory')||'/'||setting end from pg_settings where name = 'log_directory'")"
    [ "$(pg 'show logging_collector')" = "on" ] || { echo "logging_collector is off; look in: journalctl -u postgresql-12"; exit 0; }
    since="$(cat "$STAMP" 2>/dev/null || echo 0)"
    mapfile -t F < <(find "$dir" -type f -newermt "@$since" 2>/dev/null)
    [ "${#F[@]}" -gt 0 ] || { echo "No log written since the change."; exit 0; }
    n="$(cat "${F[@]}" | grep -cE 'password authentication failed|no password supplied')"
    echo "Failed password logins since the change: $n"
    cat "${F[@]}" | grep -E 'password authentication failed|no password supplied' \
      | sed -E 's/.*(FATAL.*)/\1/' | sort | uniq -c | sort -rn | head -20
    [ "$n" = "0" ] || echo "Something is failing: give it the right password, or undo with: bash $0 rollback"
    ;;
  rollback)
    [ -f "$BACKUP" ] || { echo "No backup at $BACKUP - nothing was changed by this script."; exit 1; }
    cp -p "$BACKUP" "$HBA" && pg 'select pg_reload_conf()' >/dev/null && rm -f "$STAMP"
    echo "pg_hba.conf restored from $BACKUP and reloaded."
    ;;
  *) echo "usage: bash $0 check|apply|apply-local|watch|rollback"; exit 2 ;;
esac
