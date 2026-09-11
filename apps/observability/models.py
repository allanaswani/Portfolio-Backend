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
from simple_history.models import HistoricalRecords
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


# ══════════════════════════════════════════════════════════════════════════
# Other systems, and telling somebody when things break
# ══════════════════════════════════════════════════════════════════════════

class MonitoredService(models.Model):
    """Another system this one watches — Customer 360 to begin with.

    Customer 360 is a separate resource server: it trusts the JWT this backend
    mints, but it has no Django app here and its database is not ours to read.
    So it is covered two ways, and this row carries both:

    * **Probed** — a scheduled request to ``health_url`` from this server,
      recording whether it answered and how long it took. Needs nothing from
      the other codebase and measures what a user would actually experience.
    * **Pushed** — the service posts its own audit events and table health to
      ``observability/ingest/`` using ``ingest_token``, and they appear in the
      same dashboards labelled with this service's name.
    """

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    health_url = models.URLField(
        blank=True,
        help_text="Probed on a schedule. Leave blank for a push-only service.",
    )
    expected_status = models.PositiveSmallIntegerField(default=200)
    timeout_seconds = models.PositiveSmallIntegerField(default=10)
    # A service answering slower than this is reported as degraded — up but not
    # usable is still worth knowing about, and only a threshold can say which.
    slow_ms = models.PositiveIntegerField(default=3000)

    ingest_token = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="Shared secret the service sends as X-Observability-Token.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "observability_monitored_service"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ServiceProbe(models.Model):
    """One attempt to reach a monitored service."""

    service = models.ForeignKey(
        MonitoredService, on_delete=models.CASCADE, related_name="probes",
    )
    ok = models.BooleanField(default=False)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "observability_service_probe"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["service", "created_at"]),
            models.Index(fields=["ok", "created_at"]),
        ]

    def __str__(self):
        return f"{self.service_id} {'ok' if self.ok else 'FAILED'} @ {self.created_at}"


class AlertRecipient(models.Model):
    """Who gets told, and about what.

    A list in the database rather than an environment variable, so adding
    somebody is an edit in Administration and not a deploy plus a restart.
    """

    KIND_DOWNTIME = "downtime"
    KIND_DATA_HEALTH = "data_health"
    KIND_SENSITIVE_CHANGE = "sensitive_change"
    KIND_DAILY_DIGEST = "daily_digest"
    KIND_CHOICES = [
        (KIND_DOWNTIME, "Downtime and error spikes"),
        (KIND_DATA_HEALTH, "Data health — missing, empty or newly stale tables"),
        (KIND_SENSITIVE_CHANGE, "Sensitive changes — deletions, roles, rates"),
        (KIND_DAILY_DIGEST, "Daily digest"),
    ]

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120, blank=True)
    downtime = models.BooleanField(default=True)
    data_health = models.BooleanField(default=True)
    sensitive_change = models.BooleanField(default=False)
    daily_digest = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "observability_alert_recipient"
        ordering = ["email"]

    def __str__(self):
        return self.email

    @classmethod
    def for_kind(cls, kind):
        """Active addresses subscribed to one kind of alert."""
        if kind not in dict(cls.KIND_CHOICES):
            return []
        return list(
            cls.objects.filter(is_active=True, **{kind: True})
            .values_list("email", flat=True)
        )


class AlertState(models.Model):
    """What each condition looked like the last time it was checked.

    Alerts fire on a CHANGE of state, never on a state persisting. A table that
    has been empty for a month is not news every five minutes, and an outage
    that mails every tick is an outage nobody reads about. This row is what
    makes "started" and "recovered" distinguishable from "still".
    """

    key = models.CharField(max_length=200, unique=True)
    state = models.CharField(max_length=32)
    detail = models.TextField(blank=True)
    since = models.DateTimeField(default=timezone.now)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "observability_alert_state"
        ordering = ["key"]

    def __str__(self):
        return f"{self.key}={self.state}"


class ExternalAuditEvent(models.Model):
    """A change made in another system, pushed here.

    Customer 360 keeps its own history in its own database. Rather than reach
    into it, it posts its events here and they merge into the same feed — the
    point of an audit trail is that one screen answers "who changed what",
    across systems rather than one screen per system.
    """

    source = models.CharField(max_length=50, db_index=True)
    action = models.CharField(max_length=32, blank=True)
    model_label = models.CharField(max_length=120, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    object_label = models.CharField(max_length=200, blank=True)
    username = models.CharField(max_length=150, blank=True)
    changes = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)
    # The sender's own id for the event, so a retry cannot double-record it.
    external_id = models.CharField(max_length=100, blank=True, db_index=True)

    class Meta:
        managed = True
        db_table = "observability_external_audit_event"
        ordering = ["-occurred_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=models.Q(external_id__gt=""),
                name="uniq_external_audit_event",
            ),
        ]

    def __str__(self):
        return f"{self.source}: {self.action} {self.model_label}"


class ExternalTableHealth(models.Model):
    """A table in another system, as that system last reported it."""

    source = models.CharField(max_length=50, db_index=True)
    table = models.CharField(max_length=200)
    label = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, default="unknown")
    rows = models.BigIntegerField(default=0)
    rows_are_estimate = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    age_days = models.IntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    reported_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "observability_external_table_health"
        ordering = ["source", "table"]
        constraints = [
            models.UniqueConstraint(fields=["source", "table"],
                                    name="uniq_external_table_health"),
        ]

    def __str__(self):
        return f"{self.source}.{self.table}"
