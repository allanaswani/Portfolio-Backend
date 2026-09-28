#!/bin/sh
# Is the standby actually current? Compares the newest row in several live
# tables on both servers, side by side.
#
#   [NEW] sh docs/db-freshness.sh
#
# Run it on converter-helper: it reads the local standby and the remote primary
# in one pass, so the two columns are seconds apart and a difference means
# something.
#
# "state = streaming" only says the connection is healthy. This says the data
# arrived — which is the question anybody actually has.
#
# The tables are chosen for how often they are written, not for importance:
#
#   observability_heartbeat  every minute by cron - the freshest thing there is
#   observability_request_metric  every page view
#   user_activity_events     every route change in the frontend
#   service_desk_ticket      whenever somebody raises a query
#   accounts                 nightly, by accounts_etl.py
#
# Most warehouse tables carry no row timestamp at all - daily_balance_movement
# is monthly balance COLUMNS, not dated rows - so "accounts" stands in for the
# ETL side of the check.
#
# A heartbeat matching to the minute proves replication is live right now. The
# ETL table matching proves last night's load arrived.

PRIMARY="${PRIMARY:-128.2.1.25}"
ENVFILE="${ENVFILE:-/etc/hf/prod.env}"
DB="${DB:-datawarehouse}"

PW="${PGPASSWORD:-$(grep -m1 '^DW_PASSWORD=' "$ENVFILE" 2>/dev/null | cut -d= -f2-)}"
RUSER="${RUSER:-$(grep -m1 '^DW_USER=' "$ENVFILE" 2>/dev/null | cut -d= -f2-)}"
RUSER="${RUSER:-datawarehouse}"

# Each line: label, table, timestamp column. A table that does not exist is
# reported as absent rather than failing the run - not every deployment has all
# of these, and a missing table is itself worth seeing.
ROWS="
heartbeat|observability_heartbeat|minute
requests|observability_request_metric|created_at
activity|user_activity_events|created_at
tickets|service_desk_ticket|created_at
accounts|accounts|date_created
"

ask() {   # ask <psql-args...> <table> <column>
  _t="$2"; _c="$3"
  _exists=$($1 -Atc "SELECT to_regclass('$_t');" 2>/dev/null)
  if [ -z "$_exists" ] || [ "$_exists" = "" ]; then echo "absent"; return; fi
  $1 -Atc "SELECT coalesce(max($_c)::text,'(no rows)') || '  n=' || count(*) FROM $_t;" 2>/dev/null \
    || echo "unreadable"
}

LOCAL="psql -X -q -h 127.0.0.1 -U postgres -d $DB"
REMOTE="psql -X -q -h $PRIMARY -U $RUSER -d $DB"
export PGPASSWORD="$PW"

echo "=========================================================="
echo " Freshness — primary $PRIMARY vs local standby"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=========================================================="
echo

printf '%-10s %-34s %-34s %s\n' "" "PRIMARY" "STANDBY" ""
printf '%-10s %-34s %-34s %s\n' "----------" "----------------------------------" "----------------------------------" "-----"

echo "$ROWS" | while IFS='|' read -r label table col; do
  [ -n "$label" ] || continue
  p=$(ask "$REMOTE" "$table" "$col")
  s=$(ask "$LOCAL" "$table" "$col")
  if [ "$p" = "$s" ]; then mark="same"; else mark="DIFFERS"; fi
  printf '%-10s %-34s %-34s %s\n' "$label" "$p" "$s" "$mark"
done

echo
echo "== replication =="
$REMOTE -x -c "
  SELECT client_addr, state, replay_lag,
         pg_current_wal_lsn() = replay_lsn AS fully_caught_up
  FROM pg_stat_replication;" 2>/dev/null

echo
echo "Reading this:"
echo "  DIFFERS on a table written every minute, when fully_caught_up is t,"
echo "  usually just means a row landed between the two reads - run it again."
echo "  DIFFERS that persists, or fully_caught_up = f, is a real gap."
echo "  'absent' on the standby but present on the primary means DDL has not"
echo "  replicated, which would be serious."
