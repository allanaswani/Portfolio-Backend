from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Avg
from core.pagination import StandardPagination
import django_filters.rest_framework

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db.models import Max
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.portfolio.models import HfCustomer, Loans, Accounts
from apps.gceo_dashboard.models import EmployeeTable
from apps.authentication.views import IsAdministrator
from .models import AnalyticsSnapshot, UserActivityEvent
from .serializers import AnalyticsSnapshotSerializer


@extend_schema(tags=["Analytics — Snapshots"])
class AnalyticsSnapshotListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AnalyticsSnapshotSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["category", "segment", "branch"]
    queryset = AnalyticsSnapshot.objects.all()


@extend_schema(tags=["Analytics — Summary"])
class PortfolioSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total_customers = HfCustomer.objects.count()
        active_customers = HfCustomer.objects.filter(active=True).count()
        total_deposits = Accounts.objects.aggregate(total=Sum("current_balance"))["total"] or 0
        total_loans = Loans.objects.aggregate(total=Sum("euro_book_balance"))["total"] or 0
        total_arrears = Loans.objects.filter(
            days_in_arrears__gt=0
        ).aggregate(total=Sum("total_arrears"))["total"] or 0
        return Response({
            "total_customers": total_customers,
            "active_customers": active_customers,
            "total_deposits": total_deposits,
            "total_loans": total_loans,
            "total_arrears": total_arrears,
        })


@extend_schema(tags=["Analytics — Deposits"])
class DepositsBySegmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            HfCustomer.objects.values("banking_segment")
            .annotate(
                count=Count("cust_id"),
                total_deposits=Sum("total_depost_balance"),
            )
        )
        return Response(list(data))


@extend_schema(tags=["Analytics — Loans"])
class LoansByProductView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            Loans.objects.values("loan_product")
            .annotate(
                count=Count("id"),
                total_balance=Sum("euro_book_balance"),
                total_arrears=Sum("total_arrears"),
            )
        )
        return Response(list(data))


@extend_schema(tags=["Analytics — Staff"])
class StaffSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = EmployeeTable.objects.count()
        exited = EmployeeTable.objects.filter(exit=1).count()
        new = EmployeeTable.objects.filter(new=1).count()
        by_division = list(
            EmployeeTable.objects.values("division").annotate(count=Count("id"))
        )
        return Response({
            "total_staff": total,
            "active_staff": total - exited,
            "exited_staff": exited,
            "new_staff": new,
            "by_division": by_division,
        })


# ══════════════════════════════════════════════════════════════════════════
# Usage Analytics (Administration) — last login + most-used areas of the app
# ──────────────────────────────────────────────────────────────────────────
# The SPA POSTs a lightweight event on each route change to /activity/track/.
# The admin screens read the aggregates below. Login timestamps come from
# auth_user.last_login (SIMPLE_JWT UPDATE_LAST_LOGIN=True). See models.UserActivityEvent.
# ══════════════════════════════════════════════════════════════════════════

# Collapse deep/parametrised routes to the section that matters, so
# "/bm-portfolio/customers" and "/mortgages/leads/42" roll up into their area
# instead of scattering into hundreds of near-unique paths.
def _normalise_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        return ""
    path = path.split("?", 1)[0].split("#", 1)[0]
    # Drop trailing numeric id segments (e.g. /leads/42 → /leads).
    parts = [p for p in path.split("/") if p != ""]
    parts = [p for p in parts if not p.isdigit()]
    return "/" + "/".join(parts) if parts else "/"


@extend_schema(tags=["Analytics — Usage"])
class ActivityTrackView(APIView):
    """Record one usage event for the current user (POST {path, label?, event_type?})."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        path = _normalise_path(request.data.get("path", ""))
        if not path:
            return Response({"status": "ignored"}, status=204)
        event_type = request.data.get("event_type") or "pageview"
        if event_type not in dict(UserActivityEvent.EVENT_CHOICES):
            event_type = "pageview"
        UserActivityEvent.objects.create(
            user=request.user,
            path=path[:300],
            label=str(request.data.get("label") or "")[:150],
            event_type=event_type,
        )
        return Response({"status": "ok"}, status=201)


@extend_schema(tags=["Analytics — Usage"])
class ActivityLastLoginsView(APIView):
    """Per-user last login + last activity + event count (admin only)."""

    permission_classes = [IsAuthenticated, IsAdministrator]

    def get(self, request):
        User = get_user_model()
        users = (
            User.objects.all()
            .annotate(last_activity=Max("activity_events__created_at"))
            .prefetch_related("groups")
            .order_by("-last_login")
        )
        # Event counts in one grouped query, then zipped in (avoids a per-user COUNT).
        counts = dict(
            UserActivityEvent.objects.values_list("user_id")
            .annotate(c=Count("id")).values_list("user_id", "c")
        )
        rows = [
            {
                "id": u.id,
                "username": u.username,
                "name": u.get_full_name() or u.username,
                "email": u.email or "",
                "is_active": u.is_active,
                "roles": list(u.groups.values_list("name", flat=True)),
                "last_login": u.last_login,
                "last_activity": u.last_activity,
                "total_events": counts.get(u.id, 0),
            }
            for u in users
        ]
        return Response(rows)


@extend_schema(tags=["Analytics — Usage"])
class ActivityTopPagesView(APIView):
    """Most-used areas of the app over the last ?days (default 30), admin only."""

    permission_classes = [IsAuthenticated, IsAdministrator]

    def get(self, request):
        try:
            days = min(365, max(1, int(request.query_params.get("days", 30))))
        except (TypeError, ValueError):
            days = 30
        since = timezone.now() - timedelta(days=days)
        rows = (
            UserActivityEvent.objects.filter(created_at__gte=since)
            .values("path")
            .annotate(events=Count("id"), users=Count("user", distinct=True), last_seen=Max("created_at"))
            .order_by("-events")[:100]
        )
        return Response([
            {
                "path": r["path"],
                "events": r["events"],
                "users": r["users"],
                "last_seen": r["last_seen"],
            }
            for r in rows
        ])


@extend_schema(tags=["Analytics — Usage"])
class ActivitySummaryView(APIView):
    """Headline usage KPIs + a 14-day event trend (admin only)."""

    permission_classes = [IsAuthenticated, IsAdministrator]

    def get(self, request):
        now = timezone.now()
        today = now.date()
        d7 = now - timedelta(days=7)
        d14 = now - timedelta(days=14)
        qs = UserActivityEvent.objects.all()
        trend = (
            qs.filter(created_at__gte=d14)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(events=Count("id")).order_by("day")
        )
        return Response({
            "total_events": qs.count(),
            "events_today": qs.filter(created_at__date=today).count(),
            "active_users_today": qs.filter(created_at__date=today).values("user").distinct().count(),
            "active_users_7d": qs.filter(created_at__gte=d7).values("user").distinct().count(),
            "tracked_users": qs.values("user").distinct().count(),
            "trend": [{"day": t["day"], "events": t["events"]} for t in trend],
        })


@extend_schema(tags=["Analytics — Usage"])
class ActivityRecentView(APIView):
    """Most recent 100 usage events across all users (admin only)."""

    permission_classes = [IsAuthenticated, IsAdministrator]

    def get(self, request):
        events = (
            UserActivityEvent.objects.select_related("user").order_by("-created_at")[:100]
        )
        return Response([
            {
                "username": e.user.username,
                "name": e.user.get_full_name() or e.user.username,
                "path": e.path,
                "label": e.label,
                "event_type": e.event_type,
                "created_at": e.created_at,
            }
            for e in events
        ])
