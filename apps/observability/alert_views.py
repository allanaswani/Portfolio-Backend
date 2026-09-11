"""Administration for alerting: who is told, and what is being watched."""

import secrets
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsAdministrationUser

from . import alerts
from .models import AlertRecipient, AlertState, MonitoredService, ServiceProbe

TAG = ["Observability — Alerting"]
ADMIN = [IsAuthenticated, IsAdministrationUser]


class AlertRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRecipient
        fields = [
            "id", "email", "name", "downtime", "data_health",
            "sensitive_change", "daily_digest", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        """A recipient subscribed to nothing would silently receive nothing."""
        merged = {**(self.instance.__dict__ if self.instance else {}), **attrs}
        if not any(merged.get(kind) for kind, _ in AlertRecipient.KIND_CHOICES):
            raise serializers.ValidationError(
                "Choose at least one kind of alert, or this address is on the "
                "list but will never be written to."
            )
        return attrs


class MonitoredServiceSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    last_probe = serializers.SerializerMethodField()
    # The token is write-only: it authenticates the sender, and a screen that
    # displays it turns every viewer into somebody who can post as that service.
    ingest_token = serializers.CharField(write_only=True, required=False,
                                         allow_blank=True)
    has_ingest_token = serializers.SerializerMethodField()

    class Meta:
        model = MonitoredService
        fields = [
            "id", "slug", "name", "health_url", "expected_status",
            "timeout_seconds", "slow_ms", "is_active",
            "ingest_token", "has_ingest_token", "status", "last_probe",
        ]
        read_only_fields = ["id"]

    def get_has_ingest_token(self, obj):
        return bool(obj.ingest_token)

    def get_status(self, obj):
        state = AlertState.objects.filter(key=f"service:{obj.slug}").first()
        return state.state if state else "unknown"

    def get_last_probe(self, obj):
        probe = obj.probes.first()
        if probe is None:
            return None
        return {
            "ok": probe.ok, "status_code": probe.status_code,
            "duration_ms": probe.duration_ms, "error": probe.error,
            "when": probe.created_at,
        }


@extend_schema(tags=TAG)
class AlertRecipientListView(generics.ListCreateAPIView):
    permission_classes = ADMIN
    serializer_class = AlertRecipientSerializer
    pagination_class = None
    queryset = AlertRecipient.objects.all()


@extend_schema(tags=TAG)
class AlertRecipientDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = ADMIN
    serializer_class = AlertRecipientSerializer
    queryset = AlertRecipient.objects.all()


@extend_schema(tags=TAG)
class MonitoredServiceListView(generics.ListCreateAPIView):
    permission_classes = ADMIN
    serializer_class = MonitoredServiceSerializer
    pagination_class = None
    queryset = MonitoredService.objects.prefetch_related("probes")


@extend_schema(tags=TAG)
class MonitoredServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = ADMIN
    serializer_class = MonitoredServiceSerializer
    queryset = MonitoredService.objects.prefetch_related("probes")


@extend_schema(tags=TAG)
class MonitoredServiceTokenView(APIView):
    """Issue a fresh ingest token for a service.

    Shown ONCE, in the response. It is not readable afterwards — a token a
    screen will re-display is a token anyone who can open that screen can use
    to post as the service.
    """

    permission_classes = ADMIN

    def post(self, request, pk):
        service = MonitoredService.objects.filter(pk=pk).first()
        if service is None:
            return Response({"detail": "No such service."}, status=404)
        token = secrets.token_urlsafe(32)[:64]
        service.ingest_token = token
        service.save(update_fields=["ingest_token"])
        return Response({
            "slug": service.slug,
            "ingest_token": token,
            "detail": "Copy this now — it is not shown again.",
            "usage": (
                "POST to observability/ingest/ with header "
                "X-Observability-Token: <token>"
            ),
        })


@extend_schema(tags=TAG)
class ServiceStatusView(APIView):
    """How every watched service has been doing, for the dashboard."""

    permission_classes = ADMIN

    def get(self, request):
        try:
            hours = max(1, min(720, int(request.query_params.get("hours", 24))))
        except (TypeError, ValueError):
            hours = 24
        since = timezone.now() - timedelta(hours=hours)

        out = []
        for service in MonitoredService.objects.filter(is_active=True):
            probes = ServiceProbe.objects.filter(service=service, created_at__gte=since)
            totals = probes.aggregate(
                total=Count("id"),
                failed=Count("id", filter=Q(ok=False)),
                avg_ms=Avg("duration_ms", filter=Q(ok=True)),
            )
            total = totals["total"] or 0
            failed = totals["failed"] or 0
            latest = service.probes.first()
            state = AlertState.objects.filter(key=f"service:{service.slug}").first()
            out.append({
                "slug": service.slug,
                "name": service.name,
                "health_url": service.health_url,
                "probed": bool(service.health_url),
                "state": state.state if state else "unknown",
                "since": state.since if state else None,
                "checks": total,
                "failed": failed,
                # Reachability over the window, not "uptime" — a probe every two
                # minutes cannot see a thirty-second outage, and calling it
                # uptime would claim a precision this does not have.
                "reachable_percent": (
                    round((total - failed) / total * 100, 2) if total else None
                ),
                "avg_ms": round(totals["avg_ms"]) if totals["avg_ms"] else None,
                "last_probe": {
                    "ok": latest.ok, "status_code": latest.status_code,
                    "duration_ms": latest.duration_ms, "error": latest.error,
                    "when": latest.created_at,
                } if latest else None,
            })
        return Response({"hours": hours, "services": out})


@extend_schema(tags=TAG)
class AlertTestView(APIView):
    """Send a test message, so the mail path is proven before it is needed.

    Discovering that SMTP was misconfigured during an actual outage is the worst
    possible time to discover it.
    """

    permission_classes = ADMIN

    def post(self, request):
        kind = (request.data.get("kind") or "").strip()
        if kind not in dict(AlertRecipient.KIND_CHOICES):
            return Response(
                {"detail": f"kind must be one of: "
                           f"{', '.join(dict(AlertRecipient.KIND_CHOICES))}"},
                status=400)
        count = alerts.send(
            kind,
            "Test alert",
            "This is a test from the Portfolio observability alerts.\n\n"
            f"Requested by {request.user.username} at {timezone.now()}.\n"
            "If this arrived, the mail path works.\n",
        )
        if count == 0:
            return Response({
                "sent": 0,
                "detail": "Nobody is subscribed to that alert, or the mail "
                          "server refused it. Check the backend log.",
            })
        return Response({"sent": count, "detail": f"Sent to {count} recipient(s)."})


@extend_schema(tags=TAG)
class AlertStateListView(APIView):
    """What each watched condition currently looks like.

    Useful on its own: it is the difference between "nothing has alerted" and
    "nothing is being watched".
    """

    permission_classes = ADMIN

    def get(self, request):
        return Response({
            "states": [
                {
                    "key": row.key, "state": row.state, "detail": row.detail,
                    "since": row.since, "last_notified_at": row.last_notified_at,
                }
                for row in AlertState.objects.all()
            ],
            "recipients": {
                kind: len(AlertRecipient.for_kind(kind))
                for kind in dict(AlertRecipient.KIND_CHOICES)
            },
        })
