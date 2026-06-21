"""
Reusable ETL script-trigger endpoint (ported from the legacy backend's
ScriptTriggerAPIView).

Runs a bash ETL script and returns its result. The script lives outside the
repo (legacy layout: ``<repo>/../etls/initiate_automation_report.sh``) and is
invoked as ``bash <script> <script_name>``. The path is overridable via the
``ETL_SCRIPT_PATH`` setting/env so each deploy host can point at its own copy.

NOTE: this only succeeds where the ETL script actually exists on the host. On
hosts without it, it returns 404 with a clear message rather than 500.
"""
import subprocess
from pathlib import Path

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def _etl_script_path() -> Path:
    configured = getattr(settings, "ETL_SCRIPT_PATH", None)
    if configured:
        return Path(configured).resolve()
    # Legacy default: a sibling `etls/` dir next to the repo root.
    return (Path(settings.BASE_DIR).parent / "etls" / "initiate_automation_report.sh").resolve()


class ScriptTriggerAPIView(APIView):
    """Trigger a Python/ETL refresh script by name (POST {"script_name": "..."})."""

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

        bash_script_path = _etl_script_path()
        if not bash_script_path.is_file():
            return Response(
                {"error": f"ETL script not found at {bash_script_path}. "
                          f"Set ETL_SCRIPT_PATH for this host."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = subprocess.run(
                ["bash", str(bash_script_path), script_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=120,
            )
            return Response({
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "return_code": result.returncode,
            })
        except FileNotFoundError:
            return Response(
                {"error": "Bash executable not found. Ensure Bash is installed and on PATH."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except subprocess.TimeoutExpired:
            return Response(
                {"error": "Script took longer than 2 minutes. Check whether the output email was sent."},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 - surface any runner error as JSON
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
