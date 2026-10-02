#!/bin/bash
# ============================================================================
# server-benchmark.sh — what this machine is, and what it can actually do.
#
# Written for the converter-helper cutover. The question is not "is this a
# fast server" in the abstract; it is "can this machine carry a 441 GB
# PostgreSQL cluster and the app tier that reads it". Those are decided by
# three numbers, and throughput is not one of them:
#
#   1. fsync latency   — every COMMIT waits for one. A spinning disk doing
#                        10 ms fsyncs caps you at ~100 write transactions a
#                        second no matter how many cores you have.
#   2. RAM             — 441 GB will never be cached, but the working set
#                        should be. Once it is not, every query becomes a
#                        disk read and the CPU is irrelevant.
#   3. random read IOPS — index lookups are random, not sequential. A
#                        sequential dd number tells you almost nothing about
#                        how a warehouse query will feel.
#
# Run it on BOTH hosts and compare. A number on its own means very little;
# "the new box fsyncs 6x faster than the old one" is a decision.
#
#   sh docs/server-benchmark.sh                  # safe: no writes to /data
#   sh docs/server-benchmark.sh --dir /data/tmp  # test the DISK THAT MATTERS
#   sh docs/server-benchmark.sh --no-write       # inventory only
#   sh docs/server-benchmark.sh --size 4         # 4 GB test file (default 1)
#
# SAFETY
#   * The write test creates ONE file and deletes it, including on Ctrl-C.
#   * It writes to /tmp unless you say otherwise. /tmp is often a different
#     (and faster) device than /data, so the default tells you about the
#     wrong disk — pass --dir to a path on the database volume for the
#     number that actually matters, once you are happy to put load on it.
#   * It never drops the page cache unless you pass --drop-caches, because
#     doing so on a live database server evicts everything Postgres has
#     cached and makes the next few minutes slow for real users.
#   * Nothing here writes to a database, changes a setting, or restarts
#     anything.
# ============================================================================

set -u

DIR="/tmp"
SIZE_GB=1
DO_WRITE=1
DROP_CACHES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)          DIR="$2"; shift 2 ;;
    --size)         SIZE_GB="$2"; shift 2 ;;
    --no-write)     DO_WRITE=0; shift ;;
    --drop-caches)  DROP_CACHES=1; shift ;;
    -h|--help)      sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
done

TESTFILE="$DIR/.benchmark.$$"
cleanup() { rm -f "$TESTFILE" 2>/dev/null; }
trap cleanup EXIT INT TERM

hr()  { printf '\n%s\n' "────────────────────────────────────────────────────────────────"; }
sec() { hr; printf '  %s\n' "$1"; hr; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "=============================================================="
echo "  $(hostname) — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=============================================================="

# ── 1. Identity ─────────────────────────────────────────────────────────────
sec "1. Machine"
if have hostnamectl; then hostnamectl 2>/dev/null | sed 's/^/  /'; fi
printf '  Kernel      : %s\n' "$(uname -r)"
printf '  Uptime      : %s\n' "$(uptime -p 2>/dev/null || uptime)"
if have dmidecode; then
  printf '  Hardware    : %s %s\n' \
    "$(dmidecode -s system-manufacturer 2>/dev/null)" \
    "$(dmidecode -s system-product-name 2>/dev/null)"
fi
# A VM shares its spindles with neighbours you cannot see, which is the usual
# explanation for a benchmark that is excellent on Monday and poor on Friday.
if have systemd-detect-virt; then
  printf '  Virtualised : %s\n' "$(systemd-detect-virt 2>/dev/null || echo none)"
fi

# ── 2. CPU ──────────────────────────────────────────────────────────────────
sec "2. CPU"
if have lscpu; then
  lscpu | grep -Ei 'model name|^cpu\(s\)|core\(s\) per socket|socket|thread|mhz|cache|numa node\(s\)' \
    | sed 's/^/  /'
else
  grep -E 'model name|cpu MHz' /proc/cpuinfo | head -4 | sed 's/^/  /'
  printf '  Cores: %s\n' "$(grep -c ^processor /proc/cpuinfo)"
fi
CORES=$(getconf _NPROCESSORS_ONLN 2>/dev/null || grep -c ^processor /proc/cpuinfo)
printf '\n  Load average: %s\n' "$(cut -d' ' -f1-3 /proc/loadavg)"
printf '  (vs %s cores — sustained load above that means CPU is the queue)\n' "$CORES"

# ── 3. Memory ───────────────────────────────────────────────────────────────
sec "3. Memory"
free -h 2>/dev/null | sed 's/^/  /'
echo
# "available" is the honest number: "free" looks alarmingly small on any
# healthy database server because the kernel is caching the data files, which
# is exactly what you want it to do.
awk '/MemTotal|MemAvailable|SwapTotal|SwapFree|Dirty|Writeback:/ \
     {printf "  %-14s %10.1f GB\n", $1, $2/1048576}' /proc/meminfo
SWAPPINESS=$(cat /proc/sys/vm/swappiness 2>/dev/null)
printf '\n  vm.swappiness = %s' "$SWAPPINESS"
[ "${SWAPPINESS:-60}" -gt 10 ] 2>/dev/null \
  && printf '   <-- high for a DB host; 1-10 is usual, so Postgres pages\n                       are not swapped out in favour of file cache\n' \
  || printf '\n'
# Transparent huge pages are a known source of latency spikes on Postgres.
THP=/sys/kernel/mm/transparent_hugepage/enabled
[ -r "$THP" ] && printf '  THP           : %s   (never/madvise preferred for Postgres)\n' "$(cat $THP)"

# ── 4. Storage inventory ────────────────────────────────────────────────────
sec "4. Storage"
if have lsblk; then
  lsblk -o NAME,SIZE,TYPE,ROTA,MOUNTPOINT,FSTYPE 2>/dev/null | sed 's/^/  /'
  echo
  echo "  ROTA=1 is a spinning disk, ROTA=0 is flash. For a database this is"
  echo "  the single most important line in this whole report."
fi
echo
df -hT -x tmpfs -x devtmpfs 2>/dev/null | sed 's/^/  /'
echo
echo "  Mount options on the data volume (look for noatime; 'barrier=0' or"
echo "  'nobarrier' would be fast and unsafe — it risks corruption on power loss):"
awk '$2 ~ /^\/(data|var)/ {printf "    %s on %s (%s)\n", $1, $2, $4}' /proc/mounts

# ── 5. What is using it right now ───────────────────────────────────────────
sec "5. Current load"
if have vmstat; then
  echo "  vmstat, 5 samples at 1s (watch 'wa' — time the CPU spent waiting on"
  echo "  disk. Consistently above ~10 means storage is the bottleneck):"
  vmstat 1 5 | sed 's/^/    /'
fi
echo
echo "  Top 5 by memory:"
ps -eo pid,comm,%cpu,%mem,rss --sort=-rss 2>/dev/null | head -6 | sed 's/^/    /'

# ── 6. PostgreSQL's own view ────────────────────────────────────────────────
sec "6. PostgreSQL"
PSQL=""
if sudo -n -u postgres psql -X -Atc "SELECT 1" >/dev/null 2>&1; then
  PSQL="sudo -n -u postgres psql -X"
elif psql -X -Atc "SELECT 1" -h 127.0.0.1 -U postgres >/dev/null 2>&1; then
  PSQL="psql -X -h 127.0.0.1 -U postgres"
fi
if [ -n "$PSQL" ]; then
  $PSQL -c "SELECT version();" 2>/dev/null | sed 's/^/  /'
  $PSQL -c "
    SELECT name, setting, unit
    FROM   pg_settings
    WHERE  name IN ('shared_buffers','effective_cache_size','work_mem',
                    'maintenance_work_mem','max_connections','wal_buffers',
                    'checkpoint_timeout','max_wal_size','random_page_cost',
                    'effective_io_concurrency','synchronous_commit')
    ORDER  BY name;" 2>/dev/null | sed 's/^/  /'
  echo
  echo "  Rules of thumb: shared_buffers ~25% of RAM, effective_cache_size"
  echo "  ~50-75% of RAM, and random_page_cost 1.1 on flash (the default 4.0"
  echo "  assumes a spinning disk and will push the planner to seq scans)."
  $PSQL -c "
    SELECT pg_size_pretty(sum(pg_database_size(datname))) AS all_databases
    FROM   pg_database WHERE datistemplate = false;" 2>/dev/null | sed 's/^/  /'
else
  echo "  psql not reachable as postgres here — skipping."
fi

# ── 7. fsync: the number that decides a database host ───────────────────────
sec "7. fsync latency  (the one that matters most)"
PGTF=$(command -v pg_test_fsync 2>/dev/null \
       || ls /usr/pgsql-*/bin/pg_test_fsync 2>/dev/null | head -1)
if [ -n "${PGTF:-}" ] && [ "$DO_WRITE" -eq 1 ]; then
  echo "  Running pg_test_fsync in $DIR (about 20s)..."
  echo "  Read 'fdatasync' — ops/sec there is roughly your ceiling on write"
  echo "  transactions per second, because every COMMIT waits for one."
  ( cd "$DIR" && "$PGTF" -s 5 2>&1 ) | sed 's/^/    /'
elif [ "$DO_WRITE" -eq 0 ]; then
  echo "  Skipped (--no-write)."
else
  echo "  pg_test_fsync not installed. It ships with postgresql-contrib and is"
  echo "  the single most useful disk test for a database host:"
  echo "      yum install -y postgresql12-contrib     # or the matching version"
  echo "  Falling back to a crude dd fsync timing below."
fi

# ── 8. Sequential throughput ────────────────────────────────────────────────
sec "8. Sequential throughput  (bulk restore, pg_basebackup, backups)"
if [ "$DO_WRITE" -eq 1 ]; then
  if [ ! -d "$DIR" ] || [ ! -w "$DIR" ]; then
    echo "  $DIR is not a writable directory — skipping."
  else
    AVAIL_MB=$(df -Pm "$DIR" | awk 'NR==2{print $4}')
    NEED_MB=$((SIZE_GB * 1024))
    if [ "$AVAIL_MB" -lt $((NEED_MB + 2048)) ]; then
      echo "  Only ${AVAIL_MB} MB free in $DIR; need ${NEED_MB} MB plus headroom."
      echo "  Use --size with a smaller number, or --dir elsewhere."
    else
      echo "  Target : $DIR  (device: $(df -P "$DIR" | awk 'NR==2{print $1}'))"
      echo "  Size   : ${SIZE_GB} GB"
      echo
      # conv=fdatasync is essential: without it dd reports the speed of
      # writing into RAM and the figure is meaningless.
      echo "  WRITE (conv=fdatasync — real, not cached):"
      dd if=/dev/zero of="$TESTFILE" bs=1M count=$((SIZE_GB * 1024)) \
         conv=fdatasync 2>&1 | tail -1 | sed 's/^/    /'

      if [ "$DROP_CACHES" -eq 1 ]; then
        echo "  Dropping page cache (you asked for it — this will slow the box"
        echo "  briefly for everyone, including Postgres)."
        sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
        echo "  READ (cold cache — a true disk read):"
      else
        echo "  READ (page cache NOT dropped, so this is inflated — it is"
        echo "        partly measuring RAM. Pass --drop-caches for the real"
        echo "        figure, but not during business hours):"
      fi
      dd if="$TESTFILE" of=/dev/null bs=1M 2>&1 | tail -1 | sed 's/^/    /'
      rm -f "$TESTFILE"
    fi
  fi
else
  echo "  Skipped (--no-write)."
fi

# ── 9. Random I/O ───────────────────────────────────────────────────────────
sec "9. Random I/O  (index lookups — what a query actually does)"
if have fio && [ "$DO_WRITE" -eq 1 ]; then
  echo "  fio, 4k random read, 30s, queue depth 16:"
  fio --name=randread --directory="$DIR" --size=512M --bs=4k --rw=randread \
      --ioengine=libaio --iodepth=16 --direct=1 --runtime=30 --time_based \
      --group_reporting --minimal 2>/dev/null \
    | awk -F';' '{printf "    read IOPS: %s   bw: %s KB/s   lat avg: %s us\n", $8, $7, $16}'
  rm -f "$DIR"/randread.*.0 2>/dev/null
elif ! have fio; then
  echo "  fio is not installed — this is the most informative storage test"
  echo "  there is for a database, and it is worth installing:"
  echo "      yum install -y fio"
  echo
  echo "  Rough expectations for 4k random read:"
  echo "    spinning disk   ~100-200 IOPS"
  echo "    SATA SSD        ~20,000-90,000 IOPS"
  echo "    NVMe            ~200,000+ IOPS"
  echo "    SAN/virtual     entirely dependent on the array and its neighbours"
else
  echo "  Skipped (--no-write)."
fi

# ── 10. CPU throughput ──────────────────────────────────────────────────────
sec "10. CPU throughput"
if have openssl; then
  echo "  openssl AES-256-CBC (single core, higher is better):"
  openssl speed -elapsed -evp aes-256-cbc 2>/dev/null | tail -2 | sed 's/^/    /'
fi
echo
echo "  Single-core integer loop (lower seconds is better; comparable only"
echo "  between machines running this same script):"
START=$(date +%s.%N)
awk 'BEGIN{x=0; for(i=0;i<20000000;i++) x+=i%7; print "    checksum", x}' 2>/dev/null
END=$(date +%s.%N)
echo "    elapsed: $(echo "$END $START" | awk '{printf "%.2f s", $1-$2}')"

# ── 11. Network ─────────────────────────────────────────────────────────────
sec "11. Network"
if have ip; then
  ip -br addr 2>/dev/null | sed 's/^/  /'
fi
for IFACE in $(ls /sys/class/net 2>/dev/null | grep -v lo); do
  SPEED=$(cat "/sys/class/net/$IFACE/speed" 2>/dev/null)
  [ -n "$SPEED" ] && printf '  %-10s link speed: %s Mb/s\n' "$IFACE" "$SPEED"
done
echo
echo "  Latency to the other host and to the lake:"
for H in 128.2.1.25 10.51.181.25 10.21.18.65; do
  [ "$(hostname -I 2>/dev/null | grep -c "$H")" -gt 0 ] && continue
  R=$(ping -c 3 -W 2 "$H" 2>/dev/null | tail -1)
  printf '    %-15s %s\n' "$H" "${R:-unreachable}"
done

# ── 12. What to look at ─────────────────────────────────────────────────────
sec "12. Reading this report"
cat <<'NOTE'
  In order of how much they matter for the database cutover:

  1. ROTA in section 4. Flash or spinning. Nothing else compensates.
  2. fdatasync ops/sec in section 7. That is your write-transaction ceiling.
     Under ~1,000 on a bank's warehouse is worth a conversation.
  3. MemAvailable in section 3, against the size of the working set — not
     against the 441 GB total, which will never be cached.
  4. Random read IOPS in section 9. Sequential throughput is the number
     everyone quotes and the least relevant to query latency.
  5. 'wa' in the vmstat output. High iowait with idle CPU means you are
     waiting on storage, and more cores will not help.

  Run this on BOTH hosts, keep both outputs, and compare like for like:

      sh docs/server-benchmark.sh --dir /data/tmp --size 4 | tee ~/bench-$(hostname)-$(date +%F).txt

  A single machine's numbers are hard to judge. The ratio between the old
  host and the new one is the thing that answers "is this an upgrade".
NOTE

echo
echo "Done. Test file removed."
