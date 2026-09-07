"""Observability API — Audit Trail and Data Health.

Everything here is administrator-only: it exposes who changed what across the
whole application, and the shape of the warehouse behind it.
"""

import json
import logging
import traceback
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, Max
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsAdministrationUser

from . import audit, health, metrics

TAG_AUDIT = ["Observability — Audit Trail"]
TAG_HEALTH = ["Observability — Data Health"]
TAG_PERF = ["Observability — Performance"]

# Superuser, is_staff, OR the staff_mgt group — the same set the
# Administration menu is shown to. Gating on is_staff alone meant an
# administrator saw the menu item and got 403s behind it.
ADMIN = [IsAuthenticated, IsAdministrationUser]

logger = logging.getLogger(__name__)


def _int(request, name, default, low, high):
    try:
        return max(low, min(high, int(request.query_params.get(name, default))))
    except (TypeError, ValueError):
        return default


# ── Audit trail ──────────────────────────────────────────────────────────────

@extend_schema(tags=TAG_AUDIT)
class AuditFeedView(APIView):
    """Merged create/update/delete feed across every history-tracked model.

    Query: ``?days=&app=&model=&user=&action=+|~|-&search=&limit=&changes=0``
    """

    permission_classes = ADMIN

    def get(self, request):
        days = _int(request, "days", 7, 1, 365)
        limit = _int(request, "limit", 100, 1, 500)
        since = timezone.now() - timedelta(days=days)
        action = (request.query_params.get("action") or "").strip() or None
        if action not in (None, "+", "~", "-"):
            action = None
        rows = audit.feed(
            since=since,
            app_label=(request.query_params.get("app") or "").strip() or None,
            model=(request.query_params.get("model") or "").strip().lower() or None,
            username=(request.query_params.get("user") or "").strip() or None,
            action=action,
            search=(request.query_params.get("search") or "").strip() or None,
            limit=limit,
            with_changes=request.query_params.get("changes") != "0",
        )
        return Response({"days": days, "count": len(rows), "results": rows})


@extend_schema(tags=TAG_AUDIT)
class AuditModelsView(APIView):
    """Which models are audited, and how many changes each holds in the window."""

    permission_classes = ADMIN

    def get(self, request):
        days = _int(request, "days", 30, 1, 365)
        since = timezone.now() - timedelta(days=days)
        out = []
        for entry in audit.auditable_models():
            history_model = entry["history_model"]
            try:
                qs = history_model.objects.filter(history_date__gte=since)
                counts = qs.aggregate(
                    total=Count("history_id"),
                    last=Max("history_date"),
                )
                by_action = dict(
                    qs.values_list("history_type")
                    .annotate(c=Count("history_id"))
                    .values_list("history_type", "c")
                )
            except Exception:  # noqa: BLE001 — an unmigrated history table
                continue
            out.append({
                "app_label": entry["app_label"],
                "model": entry["model"],
                "label": entry["verbose"],
                "table": history_model._meta.db_table,
                "changes": counts["total"] or 0,
                "created": by_action.get("+", 0),
                "updated": by_action.get("~", 0),
                "deleted": by_action.get("-", 0),
                "last_change": counts["last"],
            })
        out.sort(key=lambda r: r["changes"], reverse=True)
        return Response({"days": days, "models": out})


@extend_schema(tags=TAG_AUDIT)
class AuditSummaryView(APIView):
    """Headline audit numbers: volume, who is changing things, daily trend."""

    permission_classes = ADMIN

    def get(self, request):
        days = _int(request, "days", 30, 1, 365)
        since = timezone.now() - timedelta(days=days)

        total = created = updated = deleted = 0
        per_user = {}
        per_day = {}
        for entry in audit.auditable_models():
            try:
                rows = (
                    entry["history_model"].objects
                    .filter(history_date__gte=since)
                    .values_list("history_type", "history_user__username", "history_date")
                )
                rows = list(rows)
            except Exception:  # noqa: BLE001
                continue
            for kind, username, when in rows:
                total += 1
                if kind == "+":
                    created += 1
                elif kind == "~":
                    updated += 1
                elif kind == "-":
                    deleted += 1
                key = username or "system"
                per_user[key] = per_user.get(key, 0) + 1
                day = timezone.localtime(when).date() if when else None
                if day is not None:
                    per_day[day] = per_day.get(day, 0) + 1

        top_users = sorted(per_user.items(), key=lambda kv: kv[1], reverse=True)[:15]
        trend = [{"day": d, "changes": c} for d, c in sorted(per_day.items())]
        return Response({
            "days": days,
            "total_changes": total,
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "tracked_models": len(audit.auditable_models()),
            "top_users": [{"username": u, "changes": c} for u, c in top_users],
            "trend": trend,
        })


@extend_schema(tags=TAG_AUDIT)
class AuditRecordHistoryView(APIView):
    """The full change timeline of one record: ``?app=&model=&id=``."""

    permission_classes = ADMIN

    def get(self, request):
        app_label = (request.query_params.get("app") or "").strip()
        model_name = (request.query_params.get("model") or "").strip().lower()
        object_id = (request.query_params.get("id") or "").strip()
        if not (app_label and model_name and object_id):
            return Response({"detail": "app, model and id are required."}, status=400)

        entry = next(
            (e for e in audit.auditable_models()
             if e["app_label"] == app_label and e["model"] == model_name),
            None,
        )
        if entry is None:
            return Response({"detail": "That model is not audited."}, status=404)

        pk_name = entry["model_class"]._meta.pk.attname
        rows = list(
            entry["history_model"].objects
            .filter(**{pk_name: object_id})
            .select_related("history_user")
            .order_by("-history_date")[:200]
        )
        return Response({
            "app_label": app_label,
            "model": model_name,
            "object_id": object_id,
            "results": [audit.serialise(r, entry) for r in rows],
        })


# ── Data health ──────────────────────────────────────────────────────────────

@extend_schema(tags=TAG_HEALTH)
class DataHealthView(APIView):
    """Every warehouse table: does it exist, how big is it, how fresh is it."""

    permission_classes = ADMIN

    def get(self, request):
        # This endpoint must not be capable of a 500. Its entire purpose is to
        # report that something could not be read — answering with an opaque
        # server error is the one failure mode it cannot have, and a 500 here
        # tells the reader nothing they can act on. So the scan, the summary
        # and the serialisation all happen inside one guard, and anything that
        # still gets through is returned AS THE ANSWER: 200, with the exception
        # named, so the page can show it.
        scan_error = ""
        rows = []
        summary = {}
        try:
            rows = health.table_health(
                app_label=(request.query_params.get("app") or "").strip() or None,
                # The Retry button means "actually go and look again".
                use_cache=request.query_params.get("refresh") != "1",
            )
            summary = health.summarise(rows)
            status_filter = (request.query_params.get("status") or "").strip()
            if status_filter:
                rows = [r for r in rows if r["status"] == status_filter]
            # Force the payload through the JSON encoder here, where the failure
            # is still attributable, rather than in the renderer where it would
            # surface as a bare 500 with no context.
            json.dumps(rows, cls=DjangoJSONEncoder)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Data health scan failed")
            scan_error = (
                f"{type(exc).__name__}: {exc}\n"
                + "".join(traceback.format_tb(exc.__traceback__)[-3:])
            )[:2000]
            rows = []
            summary = health.summarise([])

        return Response({
            "summary": summary,
            "thresholds": {
                "warning_days": health.WARN_DAYS,
                "stale_days": health.STALE_DAYS,
                "probe_timeout_ms": health.PROBE_TIMEOUT_MS,
                "cache_seconds": health.CACHE_SECONDS,
            },
            "scan_error": scan_error,
            "tables": rows,
        })


# ── Performance / uptime ─────────────────────────────────────────────────────

@extend_schema(tags=TAG_PERF)
class PerformanceOverviewView(APIView):
    """Headline latency, throughput, error rate and uptime for the window."""

    permission_classes = ADMIN

    def get(self, request):
        return Response(metrics.overview(hours=_int(request, "hours", 24, 1, 720)))


@extend_schema(tags=TAG_PERF)
class PerformanceSeriesView(APIView):
    """Bucketed traffic + latency series for the monitoring graphs."""

    permission_classes = ADMIN

    def get(self, request):
        hours = _int(request, "hours", 24, 1, 720)
        buckets = _int(request, "buckets", 48, 6, 288)
        return Response({
            "hours": hours,
            "buckets": buckets,
            "series": metrics.timeseries(hours=hours, buckets=buckets),
        })


@extend_schema(tags=TAG_PERF)
class PerformanceEndpointsView(APIView):
    """Slowest endpoints by p95, plus their error rates."""

    permission_classes = ADMIN

    def get(self, request):
        hours = _int(request, "hours", 24, 1, 720)
        return Response({
            "hours": hours,
            "endpoints": metrics.endpoints(hours=hours, limit=_int(request, "limit", 40, 1, 200)),
            "status_codes": metrics.status_codes(hours=hours),
        })


@extend_schema(tags=TAG_PERF)
class PerformanceErrorsView(APIView):
    """Recent failing requests (4xx and 5xx)."""

    permission_classes = ADMIN

    def get(self, request):
        hours = _int(request, "hours", 24, 1, 720)
        return Response({
            "hours": hours,
            "errors": metrics.recent_errors(hours=hours, limit=_int(request, "limit", 100, 1, 500)),
        })


@extend_schema(tags=TAG_PERF)
class UptimeView(APIView):
    """Uptime for the window and a per-day availability strip."""

    permission_classes = ADMIN

    def get(self, request):
        hours = _int(request, "hours", 24, 1, 720)
        days = _int(request, "days", 14, 1, 90)
        return Response({
            "window": metrics.uptime(hours=hours),
            "by_day": metrics.uptime_by_day(days=days),
        })


@extend_schema(tags=TAG_PERF)
class ActiveUsersView(APIView):
    """Who is on the system right now, by request traffic (last ?minutes)."""

    permission_classes = ADMIN

    def get(self, request):
        minutes = _int(request, "minutes", 15, 1, 1440)
        since = timezone.now() - timedelta(minutes=minutes)
        User = get_user_model()
        rows = (
            metrics.RequestMetric.objects.using(metrics.METRIC_DB)
            .filter(created_at__gte=since).exclude(username="")
            .values("username")
            .annotate(requests=Count("id"), last_seen=Max("created_at"))
            .order_by("-last_seen")[:100]
        )
        # Real names in one lookup rather than a join the metrics table cannot make.
        names = dict(
            User.objects.filter(username__in=[r["username"] for r in rows])
            .values_list("username", "first_name")
        )
        return Response({
            "minutes": minutes,
            "users": [
                {
                    "username": r["username"],
                    "name": (names.get(r["username"]) or "").strip() or r["username"],
                    "requests": r["requests"],
                    "last_seen": r["last_seen"],
                }
                for r in rows
            ],
            "total_users": User.objects.filter(is_active=True).count(),
        })
