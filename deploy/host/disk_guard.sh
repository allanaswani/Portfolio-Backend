#!/usr/bin/env bash
# Keeps the database disk from filling up - RUNS ON THE HOST, every 10 minutes:
#
#   */10 * * * * /data/apps/datascience/portfolio_tool_v2/Portfolio-Backend/deploy/host/disk_guard.sh >> /var/log/hfcb_disk_guard.log 2>&1
#
# On 3 Nov 2026 /data reached 100% and PostgreSQL stopped. 149 GB of it was
# Metabase's H2 trace file: a text log of errors, which nothing reads.
#
# What it does by itself, and tells nobody until the morning digest:
#   - empties that trace file once it passes TRACE_MAX_GB. The last 20 MB is kept
#     on /var first. Emptied rather than deleted, because Metabase holds it open
#     and deleting an open file frees no space until Metabase restarts.
#
# What it mails a person about, because the choice is theirs:
#   - /data still past DISK_WARN_PERCENT after that
#   - WAL held back for the replica past WAL_WARN_GB. It never drops the
#     replication slot: that would free the space and cost a full re-copy of the
#     replica, which is not a decision for a script.
#
# It only ever touches the one trace file. Nothing under the data directory.
# Each mail goes once per episode; the marker clears when the condition does.

set -u

DATA_MOUNT="${DATA_MOUNT:-/data}"
WAREHOUSE_DB="${WAREHOUSE_DB:-datawarehouse}"
TRACE_FILE="${TRACE_FILE:-/data/apps/datascience/metabase.db.trace.db}"
TRACE_MAX_GB="${TRACE_MAX_GB:-5}"
TRACE_KEEP_DIR="${TRACE_KEEP_DIR:-/var/tmp}"
DISK_WARN_PERCENT="${DISK_WARN_PERCENT:-85}"
WAL_WARN_GB="${WAL_WARN_GB:-100}"
STATE_DIR="${STATE_DIR:-/var/tmp/hfcb_disk_guard}"
BACKEND="${BACKEND:-hf-backend}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "$STATE_DIR"
stamp() { date '+%Y-%m-%d %H:%M:%S'; }
GB=$((1024 * 1024 * 1024))

report() { # report <arguments for manage.py host_alert>
    if [ "$DRY_RUN" = "1" ]; then
        echo "$(stamp) would report: $*"
    else
        docker exec "$BACKEND" python manage.py host_alert "$@"
    fi
}

used_percent() { df -P "$DATA_MOUNT" | awk 'NR==2 {gsub("%","",$5); print $5}'; }

# ── the trace file ───────────────────────────────────────────────────────────
if [ -f "$TRACE_FILE" ]; then
    size=$(stat -c %s "$TRACE_FILE")
    if [ "$size" -gt $((TRACE_MAX_GB * GB)) ]; then
        before=$(used_percent)
        keep="$TRACE_KEEP_DIR/metabase-trace-tail.log"
        tail -c 20M "$TRACE_FILE" > "$keep"
        : > "$TRACE_FILE"
        message="Emptied the Metabase trace file, which had reached $((size / GB)) GB. /data went from ${before}% to $(used_percent)% used. Its last 20 MB is kept at $keep."
        echo "$(stamp) $message"
        report --fixed "$message"
    fi
fi

# ── the disk ─────────────────────────────────────────────────────────────────
percent=$(used_percent)
marker="$STATE_DIR/disk_warned"
if [ "$percent" -ge "$DISK_WARN_PERCENT" ]; then
    if [ ! -f "$marker" ]; then
        big=$(du -xsh "$DATA_MOUNT"/* 2>/dev/null | sort -h | tail -6)
        wal=$(du -sh "$DATA_MOUNT"/db_data/pgsql/12/data/data/pg_wal 2>/dev/null)
        databases=$(cd / && sudo -n -u postgres psql -At -c \
            "SELECT pg_size_pretty(pg_database_size(datname)) || '  ' || datname FROM pg_database WHERE NOT datistemplate ORDER BY pg_database_size(datname) DESC" 2>/dev/null)
        tables=$(cd / && sudo -n -u postgres psql -d "$WAREHOUSE_DB" -At -c \
            "SELECT pg_size_pretty(pg_total_relation_size(c.oid)) || '  ' || n.nspname || '.' || c.relname || '  dead rows: ' || coalesce(s.n_dead_tup, 0) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid WHERE c.relkind IN ('r', 'm') AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast') ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 15" 2>/dev/null)
        body="What happened:
$DATA_MOUNT is ${percent}% full on $(hostname).

Impact:
At 100% PostgreSQL stops and nobody can log in, as on 3 Nov 2026.

What the system did:
It keeps the Metabase trace file empty. What is left is not something it can safely remove.

What you need to do:
Free space, or extend the volume. Do not delete anything in pg_wal or base.

The largest folders:
$big

WAL:
$wal

The databases:
${databases:-could not be read}

The largest tables in $WAREHOUSE_DB:
${tables:-could not be read}"
        echo "$(stamp) /data at ${percent}%, reporting"
        report --subject "ACTION NEEDED: /data is ${percent}% full" --body "$body" && touch "$marker"
    fi
else
    rm -f "$marker"
fi

# ── WAL held for the replica ─────────────────────────────────────────────────
if command -v psql >/dev/null 2>&1; then
    held=$(cd / && sudo -n -u postgres psql -At -c \
        "SELECT COALESCE(max(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)),0)::bigint FROM pg_replication_slots" 2>/dev/null)
    marker="$STATE_DIR/wal_warned"
    if [ -n "${held:-}" ] && [ "$held" -gt $((WAL_WARN_GB * GB)) ]; then
        if [ ! -f "$marker" ]; then
            slots=$(cd / && sudo -n -u postgres psql -c \
                "SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS wal_held FROM pg_replication_slots" 2>/dev/null)
            body="What happened:
The replica has not confirmed $((held / GB)) GB of WAL, so the primary is keeping it on $DATA_MOUNT.

Impact:
If it keeps growing $DATA_MOUNT fills and PostgreSQL stops. PostgreSQL 12 has no setting that caps this.

What the system did:
Nothing. Only a person should choose between the options below.

What you need to do:
Check the replica on 10.51.181.25 is streaming (pg_stat_wal_receiver) and why it is behind. If $DATA_MOUNT is close to full and it cannot catch up, the last resort is dropping the slot, which saves production but means copying the whole replica again.

$slots"
            echo "$(stamp) WAL held $((held / GB)) GB, reporting"
            report --subject "ACTION NEEDED: $((held / GB)) GB of WAL held for the replica" --body "$body" && touch "$marker"
        fi
    else
        rm -f "$marker"
    fi
fi
