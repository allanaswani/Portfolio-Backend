#!/bin/sh
# Can the whole cluster land on this host? Run on BOTH, compare.
#
# Everything is moving - all five databases, ~441 GB - so the question is no
# longer "does the dump fit" but "does the entire PostgreSQL data directory
# fit". This reads only; it changes nothing.
#
#   sh db-space-audit.sh
#
# Three ways the space can be found, in the order they should be considered:
#
#   1. Unallocated extents in the volume group. Extending an LV is minutes and
#      costs nothing - always check this before deleting anything.
#   2. The existing 382 GB datawarehouse copy on the new host. Dropping it
#      frees the most, but it is unexplained, so it must be identified first.
#   3. Non-database files under /data. On these hosts that is ETL output and
#      logs, which belong to the data team, not to us.

echo "=========================================================="
echo " Space audit — $(hostname) / $(hostname -I 2>/dev/null | awk '{print $1}')"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=========================================================="

PSQL=""
if psql -X -Atc "SELECT 1" -h 127.0.0.1 -U postgres >/dev/null 2>&1; then
  PSQL="psql -X -q -h 127.0.0.1 -U postgres"
fi

echo
echo "--- 1. Filesystems ---------------------------------------"
df -Ph / /var /data 2>/dev/null | sort -u

echo
echo "--- 2. UNALLOCATED SPACE IN THE VOLUME GROUP -------------"
echo "  The cheapest space there is: if VFree is non-zero, the LV can be"
echo "  extended in minutes with no deletion and no risk."
if command -v vgs >/dev/null 2>&1; then
  vgs -o vg_name,vg_size,vg_free --units g 2>/dev/null | sed 's/^/  /'
  echo
  lvs -o lv_name,vg_name,lv_size --units g 2>/dev/null | sed 's/^/  /'
  echo
  echo "  To extend (example, once you know VFree):"
  echo "    lvextend -L +200G /dev/mapper/vgdata-lvol0 && xfs_growfs /data"
  echo "    (resize2fs instead of xfs_growfs on ext4 - check with: df -T /data)"
else
  echo "  lvm tools not present; this may not be LVM-backed."
fi

echo
echo "--- 3. How big is the PostgreSQL cluster on disk ---------"
if [ -n "$PSQL" ]; then
  DATA_DIR=$($PSQL -Atc "SHOW data_directory;")
  echo "  data_directory: $DATA_DIR"
  du -sh "$DATA_DIR" 2>/dev/null | sed 's/^/  on disk: /'
  $PSQL -c "
    SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size
    FROM pg_database WHERE NOT datistemplate
    ORDER BY pg_database_size(datname) DESC;"
  $PSQL -Atc "SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;" \
    | sed 's/^/  all databases together: /'
else
  echo "  !! could not reach the server; cluster size unknown."
fi

echo
echo "--- 4. What ELSE is eating /data -------------------------"
echo "  Anything large here that is not the database is a candidate for"
echo "  moving rather than deleting — most of it belongs to the data team."
du -h --max-depth=2 /data 2>/dev/null | sort -rh | head -20 | sed 's/^/  /'

echo
echo "--- 5. The arithmetic ------------------------------------"
if [ -n "$PSQL" ]; then
  CLUSTER_KB=$(du -sk "$DATA_DIR" 2>/dev/null | awk '{print $1}')
  AVAIL_KB=$(df -Pk "$DATA_DIR" | awk 'NR==2 {print $4}')
  echo "  cluster on this host : $((CLUSTER_KB / 1024 / 1024)) GB"
  echo "  free on its filesystem: $((AVAIL_KB / 1024 / 1024)) GB"
  echo
  echo "  For the NEW host the test is:"
  echo "    free + (space reclaimed by dropping the old copy) >= 441 GB"
  echo "  and leave 15-20% headroom on top — a PostgreSQL filesystem that"
  echo "  fills stops accepting writes, and recovering from that is worse"
  echo "  than any migration delay."
fi

echo
echo "--- 6. Who would notice an outage ------------------------"
[ -n "$PSQL" ] && $PSQL -c "
  SELECT COALESCE(host(client_addr)::text,'local') AS client,
         datname, usename, count(*) AS conns
  FROM pg_stat_activity WHERE backend_type='client backend'
  GROUP BY 1,2,3 ORDER BY conns DESC;"
echo "  A physical copy needs every writer stopped, not just the app:"
echo "  the ETLs, Metabase, airflow, and anything holding these connections."

echo
echo "=========================================================="
echo " Nothing was changed."
echo "=========================================================="
