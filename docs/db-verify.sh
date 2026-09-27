#!/bin/sh
# Snapshot a PostgreSQL cluster so two of them can be compared with `diff`.
#
#   [OLD] sh db-verify.sh > ~/verify-old-before-cutover.txt     # BEFORE stopping it
#   [NEW] sh db-verify.sh > ~/verify-new-after-promote.txt      # AFTER the promote
#         diff ~/verify-old-before-cutover.txt ~/verify-new-after-promote.txt
#
# A clean diff means every database, table, index, sequence, view, function and
# role arrived, and that the row counts agree.
#
# What actually proves the move, though, is the LSN check in the runbook's
# Phase 3 - with PHYSICAL replication the standby is byte-identical by
# construction, so the only real question is whether replay had caught up at
# the moment of the promote. These counts are a sanity check on top of that,
# not the proof itself.
#
# Exact count(*) is used below a size threshold and an estimate above it:
# counting accounts_history exactly means a full scan of 257 GB, which would
# add hours to a cutover window for no extra confidence. Estimated lines are
# marked and will differ slightly between hosts - only the exact lines must
# match.

THRESHOLD_GB="${THRESHOLD_GB:-5}"

# Defaults to the local server. Point it at the other host instead and no file
# has to be copied between the two - run it twice on ONE machine and diff there:
#
#   sh db-verify.sh > ~/standby.txt
#   PGHOST=128.2.1.25 PGUSER=datawarehouse #     PGPASSWORD=$(grep -m1 '^DW_PASSWORD=' /etc/hf/prod.env | cut -d= -f2-) #     sh db-verify.sh > ~/primary.txt
#   diff ~/primary.txt ~/standby.txt
#
# Reading the primary remotely uses the app's role, which pg_hba admits only to
# its own database - the other four will report as unreachable rather than
# silently missing. For the full picture at cutover, run it locally on each
# host as postgres.
PGHOST="${PGHOST:-127.0.0.1}"
PGUSER="${PGUSER:-postgres}"
export PGPASSWORD
PSQL="psql -X -q -h $PGHOST -U $PGUSER"

$PSQL -Atc "SELECT 1" -d postgres >/dev/null 2>&1   || $PSQL -Atc "SELECT 1" -d datawarehouse >/dev/null 2>&1   || { echo "!! cannot reach the server at $PGHOST as $PGUSER"; exit 1; }

echo "# cluster snapshot"
echo "# host is not printed on purpose: the two files must differ ONLY where"
echo "# the data differs, so that diff output means something."
echo

# -d is explicit from here on: the app's role may not be admitted to the
# "postgres" database, and psql would otherwise default to one we cannot open.
DB0=$($PSQL -Atc "SELECT current_database();" -d postgres 2>/dev/null || echo datawarehouse)

echo "== role =="
$PSQL -d "$DB0" -Atc "SELECT CASE WHEN pg_is_in_recovery() THEN 'standby' ELSE 'primary' END;"
echo

echo "== databases =="
$PSQL -d "$DB0" -Atc "
  SELECT datname || ' | ' || pg_size_pretty(pg_database_size(datname))
  FROM pg_database WHERE NOT datistemplate ORDER BY datname;"
echo

echo "== roles =="
$PSQL -d "$DB0" -Atc "SELECT rolname || ' | super=' || rolsuper || ' login=' || rolcanlogin
            FROM pg_roles WHERE rolname NOT LIKE 'pg\_%' ORDER BY rolname;"
echo

for db in $($PSQL -d "$DB0" -Atc "SELECT datname FROM pg_database WHERE NOT datistemplate AND datallowconn ORDER BY datname;"); do
  if ! $PSQL -d "$db" -Atc "SELECT 1" >/dev/null 2>&1; then
    echo "== $db : NOT READABLE from $PGHOST as $PGUSER =="
    echo
    continue
  fi

  echo "== $db : object counts =="
  $PSQL -d "$db" -Atc "
    SELECT 'tables    ' || count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE relkind='r' AND nspname NOT IN ('pg_catalog','information_schema')
    UNION ALL
    SELECT 'indexes   ' || count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE relkind='i' AND nspname NOT IN ('pg_catalog','information_schema')
    UNION ALL
    SELECT 'sequences ' || count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE relkind='S' AND nspname NOT IN ('pg_catalog','information_schema')
    UNION ALL
    SELECT 'views     ' || count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE relkind IN ('v','m') AND nspname NOT IN ('pg_catalog','information_schema')
    UNION ALL
    SELECT 'functions ' || count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE nspname NOT IN ('pg_catalog','information_schema')
    ORDER BY 1;"
  echo

  echo "== $db : row counts =="
  # Exact below the threshold, estimated above it. Sorted so diff is meaningful.
  $PSQL -d "$db" -Atc "
    SELECT n.nspname || '.' || c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind='r' AND n.nspname NOT IN ('pg_catalog','information_schema')
      AND pg_total_relation_size(c.oid) <= ${THRESHOLD_GB}::bigint * 1024*1024*1024
    ORDER BY 1;" | while read -r t; do
      [ -n "$t" ] || continue
      n=$($PSQL -d "$db" -Atc "SELECT count(*) FROM $t;" 2>/dev/null || echo "ERROR")
      echo "$t = $n"
    done

  $PSQL -d "$db" -Atc "
    SELECT n.nspname || '.' || c.relname || ' ~ ' || c.reltuples::bigint || '  (ESTIMATE, >${THRESHOLD_GB}GB)'
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind='r' AND n.nspname NOT IN ('pg_catalog','information_schema')
      AND pg_total_relation_size(c.oid) > ${THRESHOLD_GB}::bigint * 1024*1024*1024
    ORDER BY 1;"
  echo
done
