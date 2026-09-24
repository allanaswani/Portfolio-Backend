#!/bin/sh
# Rehearse the database move on one small database, measuring as it goes.
#
# RUN ON THE NEW HOST (10.51.181.25). It reads from the old host over the
# network and writes only to a NEW database named <db>_pilot — nothing existing
# is touched, and the pilot is dropped at the end unless you pass -k.
#
#   sh db-pilot-migrate.sh metabase
#   sh db-pilot-migrate.sh virtual_accounts_activation -k
#
# Why this shape:
#
# * It streams pg_dump straight into pg_restore. No dump file ever lands on
#   disk, which matters: /data on this host has ~63 GB free against a 439 GB
#   warehouse, and a file-based dump would need room for BOTH the dump and the
#   restore. Piping removes half that requirement.
# * The new host already reaches the old server on 5432 (the app tier has been
#   querying it across the network since the Option A move), so there is no scp
#   step and no root-login problem to solve.
# * It prints bytes/second. That number, applied to 439 GB, is the only honest
#   way to size the maintenance window - every estimate before it is a guess.
#
# What it does NOT prove: that a 439 GB pipe survives for hours. A stream that
# breaks at 80% has to start again, so for the warehouse itself compare this
# against pg_basebackup or a file-based dump with a resumable transfer.

set -e

DB="$1"
[ -n "$DB" ] || {
  echo "usage: sh db-pilot-migrate.sh <database> [-k] [-t table [-t table ...]]"
  echo
  echo "  -k          keep the pilot database instead of dropping it"
  echo "  -t table    rehearse on these tables only, not the whole database"
  echo
  echo "  The role the app uses can open the warehouse but not the other"
  echo "  databases on that server, and the old host will not admit postgres"
  echo "  from here - so rehearse on a few warehouse tables instead:"
  echo "    sh db-pilot-migrate.sh datawarehouse -t daily_balance_movement"
  exit 1
}
shift
KEEP=0
TABLE_ARGS=""
TABLE_LIST=""
while [ $# -gt 0 ]; do
  case "$1" in
    -k) KEEP=1 ;;
    -t) shift; [ -n "$1" ] || { echo "-t needs a table name"; exit 1; }
        TABLE_ARGS="$TABLE_ARGS -t $1"
        TABLE_LIST="$TABLE_LIST $1" ;;
    *)  echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

OLD_HOST="${OLD_HOST:-128.2.1.25}"
NEW_HOST="${NEW_HOST:-127.0.0.1}"
# The old server does not admit "postgres" from this host - its pg_hba only
# knows the role the app connects with. Take that role and its password from
# the env file rather than have anyone retype a production password.
# grep, not `. prod.env`: one line in these files carries unquoted spaces and a
# "<", which bash reads as a redirect before abandoning the rest of the file.
ENVFILE="${ENVFILE:-/etc/hf/prod.env}"
envget() { [ -f "$ENVFILE" ] && grep -m1 "^$1=" "$ENVFILE" | cut -d= -f2- ; }
PGUSER_OLD="${PGUSER_OLD:-$(envget DW_USER)}"
PGUSER_OLD="${PGUSER_OLD:-datawarehouse}"
[ -z "$PGPASSWORD" ] && PGPASSWORD="$(envget DW_PASSWORD)"
export PGPASSWORD
PGUSER_NEW="${PGUSER_NEW:-postgres}"
PILOT="${DB}_pilot"

say() { printf '%s\n' "$*"; }
rule() { say "----------------------------------------------------------"; }

rule
say " Pilot restore: $DB  ->  $PILOT"
say " From $OLD_HOST  to  $NEW_HOST"
say " $(date '+%Y-%m-%d %H:%M:%S %Z')"
rule

# ── 1. can we see both ends ────────────────────────────────────────────
if ! psql -X -Atc "SELECT 1" -h "$OLD_HOST" -U "$PGUSER_OLD" -d "$DB" >/dev/null 2>&1; then
  say "!! cannot read $DB on $OLD_HOST as '$PGUSER_OLD'."
  say "   The old server's pg_hba decides this, and it is NOT the file under"
  say "   /var/lib/pgsql. See the live one, on the OLD host:"
  say "     psql -h 127.0.0.1 -U postgres -Atc 'SHOW hba_file;'"
  say "   Override with: PGUSER_OLD=x PGPASSWORD=y sh $0 $DB"
  exit 1
fi

psql -X -Atc "SELECT 1" -h "$NEW_HOST" -U "$PGUSER_NEW" -d postgres >/dev/null \
  || { say "!! cannot reach the local server"; exit 1; }

if [ -n "$TABLE_LIST" ]; then
  # Measure what is actually being copied, not the whole database.
  SUM="0"
  for t in $TABLE_LIST; do SUM="$SUM + pg_total_relation_size('$t')"; done
  SRC_BYTES=$(psql -X -Atc "SELECT $SUM;" -h "$OLD_HOST" -U "$PGUSER_OLD" -d "$DB")
  say "Rehearsing on tables:$TABLE_LIST"
else
  # Ask from inside $DB: the app's role may not be admitted to postgres.
  SRC_BYTES=$(psql -X -Atc "SELECT pg_database_size('$DB');" -h "$OLD_HOST" -U "$PGUSER_OLD" -d "$DB")
fi
SRC_PRETTY=$(psql -X -Atc "SELECT pg_size_pretty($SRC_BYTES::bigint);" -h "$NEW_HOST" -U "$PGUSER_NEW" -d postgres)
say "Source size: $SRC_PRETTY ($SRC_BYTES bytes)"

# ── 2. refuse rather than fill the disk ────────────────────────────────
DATA_DIR=$(psql -X -Atc "SHOW data_directory;" -h "$NEW_HOST" -U "$PGUSER_NEW" -d postgres)
AVAIL_KB=$(df -Pk "$DATA_DIR" | awk 'NR==2 {print $4}')
AVAIL_BYTES=$((AVAIL_KB * 1024))
say "Free where PostgreSQL stores data ($DATA_DIR): $(df -Ph "$DATA_DIR" | awk 'NR==2 {print $4}')"
if [ "$AVAIL_BYTES" -lt $((SRC_BYTES * 2)) ]; then
  say "!! Less than 2x the source size free. Refusing."
  say "   A restore needs the data plus indexes rebuilt alongside it; 2x is"
  say "   the floor, not the target. Free space or pick a smaller database."
  exit 1
fi

# ── 3. the rehearsal itself ────────────────────────────────────────────
psql -X -q -h "$NEW_HOST" -U "$PGUSER_NEW" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$PILOT\";" \
  -c "CREATE DATABASE \"$PILOT\";"

say ""
say "Streaming... (no dump file is written to disk)"
START=$(date +%s)
pg_dump -h "$OLD_HOST" -U "$PGUSER_OLD" -Fc --no-owner --no-privileges $TABLE_ARGS "$DB" \
  | pg_restore -h "$NEW_HOST" -U "$PGUSER_NEW" -d "$PILOT" \
      --no-owner --no-privileges --exit-on-error
END=$(date +%s)
SECS=$((END - START))
[ "$SECS" -lt 1 ] && SECS=1

# ── 4. did it actually arrive ──────────────────────────────────────────
rule
say "Verification"

SRC_TABLES=$(psql -X -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');" -h "$OLD_HOST" -U "$PGUSER_OLD" -d "$DB")
DST_TABLES=$(psql -X -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');" -h "$NEW_HOST" -U "$PGUSER_NEW" -d "$PILOT")
say "  tables   source $SRC_TABLES   restored $DST_TABLES"
if [ -z "$TABLE_LIST" ] && [ "$SRC_TABLES" != "$DST_TABLES" ]; then
  say "  !! TABLE COUNT DIFFERS - the restore is incomplete."
fi

# Row counts on the five largest tables. Reltuples is an estimate, so this is a
# smell test, not a proof; the real check is per-table count(*) before cutover.
if [ -n "$TABLE_LIST" ]; then
  say "  (subset rehearsal - comparing only the tables named)"
  BIGGEST="$TABLE_LIST"
else
  BIGGEST=$(psql -X -Atc "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE relkind='r' AND nspname='public' ORDER BY reltuples DESC LIMIT 5;" -h "$OLD_HOST" -U "$PGUSER_OLD" -d "$DB")
  say "  five largest tables:"
fi
for t in $BIGGEST; do
  S=$(psql -X -Atc "SELECT count(*) FROM \"$t\";" -h "$OLD_HOST" -U "$PGUSER_OLD" -d "$DB" 2>/dev/null || echo "?")
  D=$(psql -X -Atc "SELECT count(*) FROM \"$t\";" -h "$NEW_HOST" -U "$PGUSER_NEW" -d "$PILOT" 2>/dev/null || echo "?")
  if [ "$S" = "$D" ]; then say "    $t: $S  OK"; else say "    $t: source $S / restored $D  !! MISMATCH"; fi
done

# ── 5. the number the window is built from ─────────────────────────────
RATE=$((SRC_BYTES / SECS))
rule
say "Throughput"
say "  $SRC_PRETTY in ${SECS}s = $((RATE / 1024 / 1024)) MB/s"
WAREHOUSE=471788503919
EST=$((WAREHOUSE / RATE))
say ""
say "  At that rate the 439 GB warehouse would take about"
say "  $((EST / 3600))h $(((EST % 3600) / 60))m of pure transfer."
say "  Add index rebuild, ANALYZE, and verification - in practice assume"
say "  at least double, and that a small database streams faster than a"
say "  large one, so treat this as a floor rather than a forecast."

# ── 6. clean up ────────────────────────────────────────────────────────
if [ "$KEEP" = 1 ]; then
  say ""
  say "Kept as \"$PILOT\". Drop it when finished:"
  say "  psql -h $NEW_HOST -U $PGUSER_NEW -d postgres -c 'DROP DATABASE \"$PILOT\";'"
else
  psql -X -q -h "$NEW_HOST" -U "$PGUSER_NEW" -d postgres -c "DROP DATABASE \"$PILOT\";"
  say ""
  say "Pilot dropped. Nothing was left behind."
fi
rule
