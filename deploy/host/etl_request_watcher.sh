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
#   3. Copy this script to the host and make it executable:
#        install -m 0755 etl_request_watcher.sh /data/apps/datascience/etl_request_watcher.sh
#   4. Add a cron entry (runs every minute; flock stops overlap):
#        * * * * * /data/apps/datascience/etl_request_watcher.sh >> /data/apps/datascience/logs/etl_request_watcher.log 2>&1
#
# The button returns immediately ("queued"); the email arrives once the report
# finishes (typically a couple of minutes).

set -uo pipefail

QUEUE_DIR="${ETL_QUEUE_DIR:-/data/apps/datascience/etl_requests}"
ETL_DIR="${ETL_DIR:-/data/apps/datascience/etls}"
RUNNER="${ETL_RUNNER:-$ETL_DIR/initiate_automation_report.sh}"
LOCK_FILE="${ETL_WATCHER_LOCK:-/tmp/etl_request_watcher.lock}"

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

    if [ -z "$script_name" ] || [ ! -f "$ETL_DIR/$script_name.py" ]; then
        echo "[$ts] SKIP: no host script $ETL_DIR/$script_name.py"
        mv "$running" "${running%.running}.failed"
        continue
    fi

    if bash "$RUNNER" "$script_name"; then
        echo "[$ts] OK: $script_name"
        mv "$running" "${running%.running}.done"
    else
        echo "[$ts] FAILED: $script_name (exit $?)"
        mv "$running" "${running%.running}.failed"
    fi
done
