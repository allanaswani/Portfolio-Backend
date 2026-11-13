#!/bin/sh
# Daily scorecard archive (see apps/staff_management/scorecard_archive.py).
# Installed by one short line in /etc/cron.d (docs/DEPLOY.md Appendix E), so
# nothing long has to be pasted into a crontab.
PATH=/usr/local/bin:/usr/bin:/bin
LOG=/data/apps/datascience/logs/archive_scorecards.log
mkdir -p "$(dirname "$LOG")"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S')"
  docker exec hf-backend python manage.py archive_scorecards "$@"
} >> "$LOG" 2>&1
