"""Check that the other systems are answering — Customer 360 to begin with.

    */2 * * * * docker exec hf-backend python manage.py probe_services

Customer 360 is a separate resource server with its own database, so this
backend cannot read its internals. What it CAN do is call it the way a user's
browser would and record whether it answered and how fast — which is the part
users actually feel, and it needs no change to that codebase at all.

A probe is written whether it succeeds or fails; ``alerts.check_services``
decides when a run of failures amounts to an outage worth an email.
"""

import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.observability.models import MonitoredService, ServiceProbe


class Command(BaseCommand):
    help = "Probe each active monitored service and record the result."

    def add_arguments(self, parser):
        parser.add_argument("--slug", help="Probe only this service.")
        parser.add_argument(
            "--prune-days", type=int, default=30,
            help="Delete probes older than this (0 to keep all).",
        )

    def handle(self, *args, **options):
        services = MonitoredService.objects.filter(is_active=True).exclude(health_url="")
        if options["slug"]:
            services = services.filter(slug=options["slug"])

        for service in services:
            ok, status, error = False, None, ""
            started = time.perf_counter()
            try:
                request = Request(
                    service.health_url,
                    headers={"User-Agent": "hf-portfolio-observability/1.0"},
                )
                with urlopen(request, timeout=service.timeout_seconds) as response:
                    status = response.status
                    response.read(2048)   # drain a little so the socket closes cleanly
                ok = status == service.expected_status
                if not ok:
                    error = f"expected HTTP {service.expected_status}, got {status}"
            except HTTPError as exc:
                # An HTTP error is still an answer — a 401 from a health URL that
                # needs auth means the service is UP, so the expected status is
                # what decides, not the exception.
                status = exc.code
                ok = exc.code == service.expected_status
                if not ok:
                    error = f"HTTP {exc.code}"
            except URLError as exc:
                error = f"unreachable: {exc.reason}"[:300]
            except Exception as exc:  # noqa: BLE001 — a probe must never crash the run
                error = f"{type(exc).__name__}: {exc}"[:300]

            duration_ms = int((time.perf_counter() - started) * 1000)
            ServiceProbe.objects.create(
                service=service, ok=ok, status_code=status,
                duration_ms=duration_ms, error=error,
            )
            self.stdout.write(
                f"{service.slug}: {'ok' if ok else 'FAILED'} "
                f"{status or '-'} {duration_ms}ms {error}"
            )

        days = options["prune_days"]
        if days:
            cutoff = timezone.now() - timedelta(days=days)
            deleted, _ = ServiceProbe.objects.filter(created_at__lt=cutoff).delete()
            if deleted:
                self.stdout.write(f"pruned {deleted} old probes")
