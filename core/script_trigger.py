"""
ETL report trigger endpoint (ported from the legacy backend's ScriptTriggerAPIView).

WHY THIS IS A QUEUE, NOT A RUNNER
---------------------------------
The ETL report scripts are owned by the data team (the ``datawarehouse-etls``
repo) and live on the host at ``/data/apps/datascience/etls/``. The OLD backend
ran on that same host, so it could just shell out and run them with the host's
``python3.6``. This backend runs inside a container that is isolated from the
host filesystem/processes, so it cannot run those scripts itself — and we do NOT
bake the data team's code into this image.

Instead the button drops a small request file into a queue directory that is
bind-mounted from the host (``ETL_REQUEST_DIR`` -> host
``/data/apps/datascience/etl_requests``). A host-side watcher (cron) picks the
request up and runs the real report with the host's python3.6 via the data team's
``initiate_automation_report.sh`` — exactly as before. The report emails its own
output, so the button doesn't need to wait for it.

See docs/DEPLOY.md ("ETL report triggers") and deploy/host/etl_request_watcher.sh.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# Script names are turned into filenames and consumed by a host shell script, so
# restrict them hard: letters, digits, underscore, hyphen only. This blocks path
# traversal and shell-metacharacter injection at the boundary.
_SAFE_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _queue_dir() -> Path:
    configured = getattr(settings, "ETL_REQUEST_DIR", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "etl_requests"


class ScriptTriggerAPIView(APIView):
    """Queue an ETL report to run on the host (POST {"script_name": "..."})."""

    permission_classes = [IsAuthenticated]
    # Subclasses may hard-code the script so the frontend can POST with no body.
    default_script_name = None

    def post(self, request, *args, **kwargs):
        script_name = request.data.get("script_name") or self.default_script_name
        if not script_name:
            return Response(
                {"error": "Script name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not _SAFE_SCRIPT_NAME.match(str(script_name)):
            return Response(
                {"error": "Invalid script name. Use letters, digits, underscore or hyphen only."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queue_dir = _queue_dir()
        try:
            queue_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return Response(
                {"error": f"ETL request queue is not available ({queue_dir}): {exc}. "
                          f"Bind-mount the host's /data/apps/datascience/etl_requests "
                          f"to this path and ensure it is writable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        requested_by = getattr(request.user, "username", None) or "unknown"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        request_path = queue_dir / f"{script_name}__{stamp}.request"
        payload = {
            "script_name": script_name,
            "requested_by": requested_by,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # Write to a temp name then rename so the host watcher never sees a
            # half-written request file (rename is atomic on the same filesystem).
            tmp_path = request_path.with_suffix(".request.tmp")
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.rename(request_path)
        except OSError as exc:
            return Response(
                {"error": f"Could not queue the ETL request: {exc}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "status": "queued",
                "script_name": script_name,
                "message": "Report queued. It runs on the host and emails its output; "
                           "allow a couple of minutes for the email to arrive.",
            },
            status=status.HTTP_202_ACCEPTED,
        )
