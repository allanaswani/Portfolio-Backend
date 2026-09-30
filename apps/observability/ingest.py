"""Where another system posts its audit events and table health.

Customer 360 runs on the same host but is a separate resource server with its
own database. This backend can probe it from outside — that is
``probe_services`` — but probing cannot tell you who changed what inside it.

So it pushes. It authenticates with a shared token held on its
:class:`~apps.observability.models.MonitoredService` row, not with a user's JWT:
the sender is a service, and requiring a user token would mean either a service
account with a password somebody has to rotate, or a long-lived token belonging
to a real person.

Both payloads are idempotent. Audit events carry the sender's own id and are
inserted once; table health is keyed on (source, table) and replaced. A retry
after a timeout therefore cannot double-record anything.
"""

import hmac
from datetime import date, datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ExternalAuditEvent, ExternalTableHealth, ExternalUsageDay, MonitoredService

TAG = ["Observability — Ingest"]
MAX_EVENTS = 500
MAX_TABLES = 500
MAX_USAGE_DAYS = 500
USAGE_COUNTERS = ("requests", "page_views", "customer_views", "distinct_customers",
                  "searches", "exports", "errors", "sessions", "active_minutes")


def authenticate(request):
    """The service whose token this request carries, or None.

    Compared with ``compare_digest`` so a wrong token cannot be found one
    character at a time.
    """
    token = (request.headers.get("X-Observability-Token") or "").strip()
    if not token:
        return None
    for service in MonitoredService.objects.filter(is_active=True).exclude(ingest_token=""):
        if hmac.compare_digest(service.ingest_token, token):
            return service
    return None


def _when(value):
    """A timestamp from the payload, made timezone-aware, defaulting to now."""
    if not value:
        return timezone.now()
    parsed = parse_datetime(str(value)) if not isinstance(value, datetime) else value
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@extend_schema(tags=TAG)
class IngestView(APIView):
    """``POST observability/ingest/`` — audit events and/or table health.

    ```json
    {
      "audit_events": [
        {"id": "c360-8821", "action": "updated", "model_label": "Customer",
         "object_id": "778899", "object_label": "ACME LTD",
         "username": "jdoe", "occurred_at": "2026-09-11T08:14:00Z",
         "changes": [{"field": "segment", "old": "SME", "new": "BB"}]}
      ],
      "tables": [
        {"table": "c360_customer", "status": "ok", "rows": 331200,
         "last_seen": "2026-09-11T02:00:00Z"}
      ],
      "usage_days": [
        {"day": "2026-09-30", "username": "jdoe", "requests": 120,
         "customer_views": 14, "distinct_customers": 9, "searches": 11,
         "active_minutes": 42, "features": {"insights": 6}}
      ]
    }
    ```

    ``usage_days`` is keyed on (source, day, username): sending a day again
    replaces it, so the sender can push "today" every hour.
    """

    # Authenticated by the service token, not a user session — see authenticate().
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        service = authenticate(request)
        if service is None:
            return Response({"detail": "Unknown or missing service token."}, status=401)

        payload = request.data if isinstance(request.data, dict) else {}
        events = payload.get("audit_events") or []
        tables = payload.get("tables") or []
        usage = payload.get("usage_days") or []
        if not all(isinstance(x, list) for x in (events, tables, usage)):
            return Response(
                {"detail": "audit_events, tables and usage_days must be lists."}, status=400)
        if len(events) > MAX_EVENTS or len(tables) > MAX_TABLES or len(usage) > MAX_USAGE_DAYS:
            return Response(
                {"detail": f"Send at most {MAX_EVENTS} events, {MAX_TABLES} tables and "
                           f"{MAX_USAGE_DAYS} usage days per request."},
                status=400)

        stored_events = self._store_events(service, events)
        stored_tables = self._store_tables(service, tables)
        stored_usage = self._store_usage(service, usage)
        return Response({
            "source": service.slug,
            "audit_events_stored": stored_events,
            "audit_events_received": len(events),
            "tables_stored": stored_tables,
            "usage_days_stored": stored_usage,
        })

    def _store_usage(self, service, rows):
        stored = 0
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            username = str(raw.get("username") or "").strip().lower()[:150]
            try:
                day = date.fromisoformat(str(raw.get("day") or "")[:10])
            except ValueError:
                continue
            if not username:
                continue
            defaults = {}
            for key in USAGE_COUNTERS:
                try:
                    defaults[key] = max(0, int(raw.get(key) or 0))
                except (TypeError, ValueError):
                    defaults[key] = 0
            features = raw.get("features")
            defaults["features"] = (
                {str(k)[:60]: int(v) for k, v in features.items()
                 if isinstance(v, (int, float))}
                if isinstance(features, dict) else {})
            defaults["first_at"] = _when(raw.get("first_at")) if raw.get("first_at") else None
            defaults["last_at"] = _when(raw.get("last_at")) if raw.get("last_at") else None
            ExternalUsageDay.objects.update_or_create(
                source=service.slug, day=day, username=username, defaults=defaults)
            stored += 1
        return stored

    def _store_events(self, service, events):
        stored = 0
        for raw in events:
            if not isinstance(raw, dict):
                continue
            external_id = str(raw.get("id") or "")[:100]
            # An event carrying the sender's id is inserted once however many
            # times it is retried; one without is taken at face value, because
            # refusing it would lose a change nobody else recorded.
            if external_id and ExternalAuditEvent.objects.filter(
                source=service.slug, external_id=external_id
            ).exists():
                continue
            changes = raw.get("changes")
            ExternalAuditEvent.objects.create(
                source=service.slug,
                external_id=external_id,
                action=str(raw.get("action") or "")[:32],
                model_label=str(raw.get("model_label") or "")[:120],
                object_id=str(raw.get("object_id") or "")[:100],
                object_label=str(raw.get("object_label") or "")[:200],
                username=str(raw.get("username") or "")[:150],
                reason=str(raw.get("reason") or "")[:255],
                changes=changes if isinstance(changes, list) else [],
                occurred_at=_when(raw.get("occurred_at")),
            )
            stored += 1
        return stored

    def _store_tables(self, service, tables):
        stored = 0
        for raw in tables:
            if not isinstance(raw, dict) or not raw.get("table"):
                continue
            last_seen = raw.get("last_seen")
            ExternalTableHealth.objects.update_or_create(
                source=service.slug,
                table=str(raw["table"])[:200],
                defaults={
                    "label": str(raw.get("label") or "")[:200],
                    "status": str(raw.get("status") or "unknown")[:20],
                    "rows": int(raw.get("rows") or 0),
                    "rows_are_estimate": bool(raw.get("rows_are_estimate")),
                    "last_seen": _when(last_seen) if last_seen else None,
                    "age_days": raw.get("age_days"),
                    "error": str(raw.get("error") or "")[:300],
                },
            )
            stored += 1
        return stored
