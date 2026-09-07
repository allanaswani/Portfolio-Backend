"""Records how long every request took, without slowing requests down.

The obvious implementation — one INSERT per request — doubles the database
round-trips of the whole application, and this app has already been through one
round of "everything is slow" tuning. So rows are buffered per worker process
and flushed with a single ``bulk_create`` once the buffer is full or old enough.
A worker that dies loses at most a few seconds of metrics, which is the right
trade for a monitoring table.
"""

import re
import threading
import time

from django.db import DatabaseError
from django.utils import timezone

# Flush when either threshold is hit (whichever comes first).
BUFFER_LIMIT = 50
FLUSH_SECONDS = 10

# Never measure these: static assets, and the monitoring endpoints themselves
# (which would otherwise generate the traffic they are reporting on).
SKIP_PREFIXES = ("/static/", "/media/", "/favicon", "/observability/")

_buffer = []
_buffer_lock = threading.Lock()
_last_flush = time.monotonic()

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def normalise_path(path):
    """Collapse record ids so a route aggregates instead of scattering.

    ``/api/mortgages/leads/42/`` and ``/api/mortgages/leads/91/`` both become
    ``/api/mortgages/leads/:id``.
    """
    path = (path or "").split("?", 1)[0]
    parts = [p for p in path.split("/") if p]
    out = []
    for part in parts:
        if part.isdigit() or _UUID.match(part):
            out.append(":id")
        else:
            out.append(part)
    return "/" + "/".join(out) if out else "/"


def _flush_locked():
    """Write the buffer out. Caller holds ``_buffer_lock``."""
    global _last_flush
    if not _buffer:
        _last_flush = time.monotonic()
        return
    rows, _buffer[:] = list(_buffer), []
    _last_flush = time.monotonic()
    try:
        from .models import RequestMetric

        RequestMetric.objects.bulk_create(rows, ignore_conflicts=True)
    except DatabaseError:
        # Monitoring must never take the application down with it — a missing
        # table (migration not yet run) or a dead connection just drops metrics.
        pass


def flush(force=True):
    """Flush any buffered metrics. Used by the tests and at shutdown."""
    with _buffer_lock:
        if force or _buffer:
            _flush_locked()


class RequestMetricsMiddleware:
    """Times each request and buffers a :class:`RequestMetric` row."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"
        if path.startswith(SKIP_PREFIXES):
            return self.get_response(request)

        started = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self.record(request, response.status_code, elapsed_ms)
        return response

    def process_exception(self, request, exception):
        """An unhandled exception is a 500 the response hook never sees."""
        if not (request.path or "/").startswith(SKIP_PREFIXES):
            self.record(request, 500, 0)
        return None

    @staticmethod
    def record(request, status_code, duration_ms):
        from .models import RequestMetric

        user = getattr(request, "user", None)
        row = RequestMetric(
            path=normalise_path(request.path)[:300],
            method=(request.method or "")[:10],
            status_code=status_code,
            duration_ms=max(0, duration_ms),
            username=(user.username[:150]
                      if (user is not None and user.is_authenticated) else ""),
            is_error=status_code >= 500,
            created_at=timezone.now(),
        )
        with _buffer_lock:
            _buffer.append(row)
            due = (
                len(_buffer) >= BUFFER_LIMIT
                or (time.monotonic() - _last_flush) >= FLUSH_SECONDS
            )
            if due:
                _flush_locked()
