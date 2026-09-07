"""Tables behind the Audit Trail and Data Health dashboards.

Two things are recorded here that nothing else in the project records:

* :class:`RequestMetric` — one row per served HTTP request (path, status,
  duration). This is what the latency/throughput/error-rate graphs are drawn
  from. Django keeps no such record, and there is no Prometheus on the host.
* :class:`AppHeartbeat` — a "the app was alive at this minute" tick written by
  a cron'd management command. Uptime is measured from these, NOT from request
  traffic: a quiet night has no requests but is not downtime, and inferring one
  from the other would report a made-up number.

The audit trail itself is not stored here — ``simple_history`` already records
every create/update/delete on 35 models, with the acting user, and until now
nothing read it. :mod:`apps.observability.audit` reads those tables.
"""

from django.db import models
from django.utils import timezone


class RequestMetric(models.Model):
    """One served HTTP request.

    ``path`` is the *normalised* route (numeric ids collapsed), so
    ``/api/mortgages/leads/42/`` and ``/api/mortgages/leads/91/`` aggregate
    together instead of scattering into thousands of unique rows.
    """

    path = models.CharField(max_length=300)
    method = models.CharField(max_length=10)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField()
    # Deliberately NOT a ForeignKey: rows are buffered and flushed after the
    # request, so the insert can land after the account it names is gone, and a
    # constraint violation would throw away the whole batch. Telemetry records
    # what it saw; it does not police referential integrity.
    username = models.CharField(max_length=150, blank=True, default="")
    # Denormalised so the error-rate graph never needs a range scan on status.
    is_error = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "observability_request_metric"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["path", "created_at"]),
            models.Index(fields=["is_error", "created_at"]),
            models.Index(fields=["status_code", "created_at"]),
            models.Index(fields=["username", "created_at"]),
        ]

    def __str__(self):
        return f"{self.method} {self.path} {self.status_code} {self.duration_ms}ms"


class AppHeartbeat(models.Model):
    """One tick per minute from ``manage.py record_heartbeat`` (cron).

    Uptime for a window = minutes with a tick / minutes in the window. Without
    the cron entry there are no ticks, and the dashboard says uptime is not
    being measured rather than reporting 100%.
    """

    minute = models.DateTimeField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "observability_heartbeat"
        ordering = ["-minute"]
        indexes = [models.Index(fields=["minute"])]

    def __str__(self):
        return self.minute.isoformat()
