#!/bin/bash
# Container-side ETL report runner.
#
# Replaces the host's /data/apps/datascience/etls/initiate_automation_report.sh.
# The old backend ran the reports on the host with python3.6; the new backend runs
# them INSIDE the container with the image's Python + deps (the reports are baked
# into the image under /app/etls). Invoked by core.script_trigger.ScriptTriggerAPIView
# as:  bash run_report.sh <script_name>
#
# The secret app_settings.py (bank-wide DB creds + SMTP password) is NOT baked in —
# it is bind-mounted at runtime to /app/etls/app_settings.py (see docs/DEPLOY.md).
#
# Output goes to stdout/stderr so the API captures and returns it to the caller.
set -uo pipefail

SCRIPT_NAME="${1:-}"
if [ -z "$SCRIPT_NAME" ]; then
  echo "Error: no script name provided." >&2
  exit 1
fi

# Run from the etls dir so the report's relative paths (attachments/, imports,
# `import app_settings`) resolve, and so it finds the mounted app_settings.py.
cd "$(dirname "$0")" || { echo "Cannot cd to etls dir." >&2; exit 1; }

SCRIPT_FILE="./${SCRIPT_NAME}.py"
if [ ! -f "$SCRIPT_FILE" ]; then
  echo "Error: report '${SCRIPT_NAME}' is not baked into this image ($SCRIPT_FILE not found)." >&2
  exit 1
fi

if [ ! -f "./app_settings.py" ]; then
  echo "Error: app_settings.py is not mounted. Bind-mount the host's" \
       "/data/apps/datascience/etls/app_settings.py to /app/etls/app_settings.py." >&2
  exit 1
fi

echo "Running report: ${SCRIPT_NAME}"
exec python "$SCRIPT_FILE"
