#!/bin/bash
# ETL request watcher — RUNS ON THE HOST (not in the container).
#
# The containerized backend cannot run the data team's ETL reports itself (it is
# isolated from the host and does not carry that code). Instead the trigger
# buttons drop a request file into a queue directory that is bind-mounted into
# the container. This script — scheduled by host cron — picks those requests up
# and runs the real report with the host's python3.6, exactly as the old backend
# did, via the data team's initiate_automation_report.sh. Each report emails its
# own output.
#
# INSTALL (on the host):
#   1. Create the queue + logs dirs (once):
#        mkdir -p /data/apps/datascience/etl_requests
#        mkdir -p /data/apps/datascience/logs
#   2. Bind-mount the queue into the container (docker run):
#        -v /data/apps/datascience/etl_requests:/app/etl_requests
#   3. Copy this script AND the failure notifier to the host, side by side, and
#      make the watcher executable:
#        install -m 0755 etl_request_watcher.sh /data/apps/datascience/etl_request_watcher.sh
#        install -m 0644 etl_failure_notify.py  /data/apps/datascience/etl_failure_notify.py
#      (the notifier is resolved next to this script by default; override with
#       ETL_NOTIFY=/path/to/etl_failure_notify.py)
#   4. Add a cron entry (runs every minute; flock stops overlap). Failure alerts
#      go to a baked-in default list (see etl_failure_notify.py); override per
#      -run with ETL_ALERT_RECIPIENTS="a@x,b@y" if needed:
#        * * * * * /data/apps/datascience/etl_request_watcher.sh >> /data/apps/datascience/logs/etl_request_watcher.log 2>&1
#
# The button returns immediately ("queued"); on SUCCESS the report emails its own
# output (a couple of minutes). On FAILURE (report crashes, or the host script is
# missing) etl_failure_notify.py emails the captured error to ETL_ALERT_RECIPIENTS
# so a broken trigger is never silent. The notifier reuses the reports' own SMTP
# config from app_settings — no separate mail setup.

set -uo pipefail

QUEUE_DIR="${ETL_QUEUE_DIR:-/data/apps/datascience/etl_requests}"
ETL_DIR="${ETL_DIR:-/data/apps/datascience/etls}"
RUNNER="${ETL_RUNNER:-$ETL_DIR/initiate_automation_report.sh}"
LOCK_FILE="${ETL_WATCHER_LOCK:-/tmp/etl_request_watcher.lock}"
LOG_DIR="${ETL_LOG_DIR:-/data/apps/datascience/logs}"
# Failure-alert emailer (reuses the reports' own SMTP via app_settings).
NOTIFY="${ETL_NOTIFY:-$(dirname "$0")/etl_failure_notify.py}"
# Match the interpreter the reports themselves run under on this host.
NOTIFY_PY="${ETL_NOTIFY_PYTHON:-python3.6}"

mkdir -p "$LOG_DIR" 2>/dev/null || true

# Email a failure alert; never let a notifier problem abort the watcher loop.
notify_failure() {
    local script_name="$1" log_file="$2" exit_code="$3"
    if [ -f "$NOTIFY" ]; then
        ETL_DIR="$ETL_DIR" "$NOTIFY_PY" "$NOTIFY" "$script_name" "$log_file" "$exit_code" \
            || echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: failure notifier errored for $script_name"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: no notifier at $NOTIFY — cannot email alert"
    fi
}

# Only one watcher at a time — a long report must not be started twice by
# back-to-back cron ticks. Exit quietly if another run holds the lock.
exec 9>"$LOCK_FILE" || exit 0
flock -n 9 || exit 0

[ -d "$QUEUE_DIR" ] || exit 0

shopt -s nullglob
for req in "$QUEUE_DIR"/*.request; do
    # Claim the request atomically so a future tick can't re-run it.
    running="${req%.request}.running"
    mv -n "$req" "$running" 2>/dev/null || continue
    [ -f "$running" ] || continue

    # The sanitized script name is the filename prefix before the "__timestamp".
    base="$(basename "$running")"
    script_name="${base%%__*}"

    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] Running ETL report: $script_name (from $base)"

    # Per-run log capturing the report's stdout+stderr, so a failure alert can
    # carry the actual traceback.
    run_log="$LOG_DIR/${base%.running}.log"

    if [ -z "$script_name" ] || [ ! -f "$ETL_DIR/$script_name.py" ]; then
        echo "[$ts] SKIP: no host script $ETL_DIR/$script_name.py"
        echo "No host script found at $ETL_DIR/$script_name.py — the report cannot run." > "$run_log"
        mv "$running" "${running%.running}.failed"
        notify_failure "$script_name" "$run_log" "missing-script"
        continue
    fi

    # Capture output while still echoing it to the watcher log (tee).
    if bash "$RUNNER" "$script_name" > "$run_log" 2>&1; then
        rc=0
    else
        rc=$?
    fi
    cat "$run_log"

    if [ "$rc" -eq 0 ]; then
        echo "[$ts] OK: $script_name"
        mv "$running" "${running%.running}.done"
    else
        echo "[$ts] FAILED: $script_name (exit $rc)"
        mv "$running" "${running%.running}.failed"
        notify_failure "$script_name" "$run_log" "$rc"
    fi
done
