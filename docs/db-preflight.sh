#!/bin/sh
# Preflight for moving PostgreSQL from 128.2.1.25 to 10.51.181.25 (Option B).
#
# Run on BOTH hosts and keep the output. It copies nothing and changes nothing —
# every command here is a read. It exists to answer the questions that decide
# whether the move is an evening or a fortnight, before anybody dumps a byte.
#
#   sh db-preflight.sh            # auto-detects which host it is on
#
# The single most dangerous unknown is question 5: who else in the bank connects
# to this instance. The migration doc's own warning is "assume something does" —
# ETLs, Metabase, the Sybase bridge, and anything a colleague wired up without
# telling us all resolve 128.2.1.25 by IP. Each one that is missed becomes an
# outage the morning after cutover, and it will not be obvious that we caused it.

echo "=========================================================="
echo " Host:    $(hostname) / $(hostname -I 2>/dev/null | awk '{print $1}')"
echo " Date:    $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=========================================================="

PSQL="psql -X -q -U postgres"
have_pg=0
if command -v psql >/dev/null 2>&1; then have_pg=1; fi

echo
echo "--- 1. PostgreSQL present, and which version -------------"
if [ "$have_pg" = 1 ]; then
  psql --version
  $PSQL -Atc "SHOW server_version;" 2>/dev/null \
    && echo "  (server reachable)" \
    || echo "  !! client installed but server did not answer"
else
  echo "  psql NOT installed on this host."
  echo "  If this is the NEW host, that is the first thing to fix — and the"
  echo "  major version must MATCH or EXCEED the old host, never trail it:"
  echo "  pg_restore cannot load a dump from a newer server."
fi

echo
echo "--- 2. Database sizes: the window is a function of this ---"
[ "$have_pg" = 1 ] && $PSQL -c "
  SELECT datname,
         pg_size_pretty(pg_database_size(datname)) AS size,
         pg_database_size(datname) AS bytes
  FROM pg_database WHERE NOT datistemplate
  ORDER BY pg_database_size(datname) DESC;" 2>/dev/null

echo
echo "--- 3. Disk headroom -------------------------------------"
df -h / /var /data 2>/dev/null | sort -u
echo "  Need, on the NEW host: the restored size PLUS the dump file."
echo "  A compressed -Fc dump is usually 20-50% of the live size, but that"
echo "  ratio is a guess until the dump exists. Do not cut it fine."

echo
echo "--- 4. Where this server keeps its data ------------------"
[ "$have_pg" = 1 ] && $PSQL -Atc "SHOW data_directory;" 2>/dev/null
[ "$have_pg" = 1 ] && $PSQL -c "
  SELECT spcname, pg_tablespace_location(oid) AS location
  FROM pg_tablespace WHERE spcname NOT IN ('pg_default','pg_global');" 2>/dev/null
echo "  A non-default tablespace does NOT travel in a dump automatically."

echo
echo "--- 5. WHO ELSE IS CONNECTED (the important one) ---------"
[ "$have_pg" = 1 ] && $PSQL -c "
  SELECT COALESCE(host(client_addr)::text,'local') AS client,
         datname, usename, count(*) AS conns,
         min(backend_start) AS oldest
  FROM pg_stat_activity
  WHERE backend_type = 'client backend'
  GROUP BY 1,2,3 ORDER BY conns DESC;" 2>/dev/null
echo "  This is a SNAPSHOT. A nightly ETL or a monthly report is invisible"
echo "  right now. Re-run it morning, midday and after 22:00 for several days"
echo "  before trusting the list, and cross-check pg_hba.conf below."

echo
echo "--- 6. Who is ALLOWED to connect (pg_hba) ----------------"
for f in /var/lib/pgsql/12/data/pg_hba.conf /var/lib/pgsql/data/pg_hba.conf \
         /etc/postgresql/12/main/pg_hba.conf; do
  [ -f "$f" ] && { echo "  $f"; grep -vE '^\s*#|^\s*$' "$f" | sed 's/^/    /'; }
done
echo "  Every non-local line here is a consumer somebody deliberately added."

echo
echo "--- 7. Roles that own things -----------------------------"
[ "$have_pg" = 1 ] && $PSQL -c "\du" 2>/dev/null
echo "  pg_restore --no-owner drops ownership. Roles must exist on the new"
echo "  host first, or permissions land wrong and only surface under load."

echo
echo "--- 8. Extensions ----------------------------------------"
[ "$have_pg" = 1 ] && for db in $($PSQL -Atc \
  "SELECT datname FROM pg_database WHERE NOT datistemplate;" 2>/dev/null); do
  echo "  $db: $($PSQL -d "$db" -Atc \
    "SELECT string_agg(extname||' '||extversion, ', ') FROM pg_extension;" 2>/dev/null)"
done
echo "  Each one must be INSTALLED on the new host before restore, not after."

echo
echo "--- 9. What runs on this host itself ---------------------"
command -v docker >/dev/null 2>&1 && docker ps --format '  {{.Names}}\t{{.Image}}\t{{.Ports}}'
echo "  cron jobs touching the database:"
crontab -l 2>/dev/null | grep -viE '^\s*#' | grep -iE 'psql|pg_|etl|python|\.sh' | sed 's/^/    /'
echo "  (Also check other users' crontabs: for u in \$(cut -d: -f1 /etc/passwd); do crontab -lu \$u; done)"

echo
echo "--- 10. Replication or backups already in place ----------"
[ "$have_pg" = 1 ] && $PSQL -c "SELECT * FROM pg_stat_replication;" 2>/dev/null
[ "$have_pg" = 1 ] && $PSQL -Atc "SHOW archive_mode;" 2>/dev/null | sed 's/^/  archive_mode: /'
echo "  If streaming replication is available, it beats dump/restore for a"
echo "  large warehouse: replicate first, then the window is a promotion,"
echo "  not a copy. Worth knowing before committing to a long outage."

echo
echo "=========================================================="
echo " Nothing was changed. Keep this output — it is the baseline"
echo " the post-cutover checks get compared against."
echo "=========================================================="
