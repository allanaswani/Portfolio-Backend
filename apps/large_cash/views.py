"""Large Cash Transactions dashboard: cash deposits and withdrawals of
KES 500,000 and above, day by day. See lake.py for the rules."""
import datetime

from django.db.models import Count, Max, Q, Sum
from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.search import DynamicColumnSearchListView

from . import lake
from .models import LargeCashDay, LargeCashTransaction

#: Customer-level cash movements: administrators, and whoever an
#: administrator puts in this group on the Users screen.
VIEW_GROUP = "large_cash_viewer"


def may_view(user):
    return bool(user and user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=VIEW_GROUP).exists()))


class MayView(BasePermission):
    message = ("The Large Cash Transactions dashboard is for administrators and "
               "the large_cash_viewer group.")

    def has_permission(self, request, view):
        return may_view(request.user)


def _day(text):
    try:
        return datetime.date.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _span(request):
    """(start, end) from ?date= or ?start=&end=; default the newest day read."""
    day = _day(request.query_params.get("date"))
    start = _day(request.query_params.get("start")) or day
    end = _day(request.query_params.get("end")) or day
    if start is None or end is None:
        newest = LargeCashDay.objects.order_by("-day").values_list("day", flat=True).first()
        start = start or end or newest
        end = end or start
    if start and end and start > end:
        start, end = end, start
    return start, end


def _f(v):
    return float(v or 0)


class SummaryView(APIView):
    """One day (or a span): totals, by branch, by type, the customers with the
    most, the days read and how fresh the copy is."""

    permission_classes = [IsAuthenticated, MayView]

    def get(self, request):
        status = lake.refresh_in_background()
        start, end = _span(request)
        days = list(LargeCashDay.objects.order_by("-day")[:62])
        base = {
            "threshold_kes": lake.THRESHOLD_KES,
            "refresh": status,
            "refresh_error": lake.last_error(),
            "days": [{"day": d.day.isoformat(), "transactions": d.transactions,
                      "total_kes": _f(d.total_kes),
                      "loaded_at": d.loaded_at.isoformat()} for d in days],
            "loaded_at": max((d.loaded_at for d in days), default=None),
        }
        if start is None:
            return Response({**base, "start": None, "end": None, "read": False,
                             "detail": "Nothing has been read from the lake yet. "
                                       "The first read has started; reload in a "
                                       "few minutes."})
        read = LargeCashDay.objects.filter(day__range=(start, end)).count()
        rows = LargeCashTransaction.objects.filter(trx_date__range=(start, end))
        live = rows.filter(reversed=False)

        def totals(qs):
            got = qs.aggregate(n=Count("id"), kes=Sum("amount_kes"))
            return {"transactions": got["n"] or 0, "total_kes": _f(got["kes"])}

        by_branch = [
            {"branch": r["branch"] or "(no branch)",
             "deposits": r["dn"], "deposits_kes": _f(r["dk"]),
             "withdrawals": r["wn"], "withdrawals_kes": _f(r["wk"]),
             "transactions": r["n"], "total_kes": _f(r["kes"])}
            for r in live.values("branch").annotate(
                n=Count("id"), kes=Sum("amount_kes"),
                dn=Count("id", filter=Q(direction="deposit")),
                dk=Sum("amount_kes", filter=Q(direction="deposit")),
                wn=Count("id", filter=Q(direction="withdrawal")),
                wk=Sum("amount_kes", filter=Q(direction="withdrawal")),
            ).order_by("-kes")]
        by_type = [
            {"type": r["transaction_type"], "direction": r["direction"],
             "transactions": r["n"], "total_kes": _f(r["kes"])}
            for r in live.values("transaction_type", "direction").annotate(
                n=Count("id"), kes=Sum("amount_kes")).order_by("-kes")]
        customers = [
            {"customer_id": r["customer_id"], "account_name": r["name"],
             "transactions": r["n"], "total_kes": _f(r["kes"]),
             "deposits_kes": _f(r["dk"]), "withdrawals_kes": _f(r["wk"])}
            for r in live.values("customer_id").annotate(
                name=Max("account_name"), n=Count("id"), kes=Sum("amount_kes"),
                dk=Sum("amount_kes", filter=Q(direction="deposit")),
                wk=Sum("amount_kes", filter=Q(direction="withdrawal")),
            ).order_by("-kes")[:20]]
        span_days = (end - start).days + 1
        return Response({
            **base,
            "start": start.isoformat(), "end": end.isoformat(),
            "read": read == span_days, "days_read": read, "days_in_span": span_days,
            "all": totals(live),
            "deposits": totals(live.filter(direction="deposit")),
            "withdrawals": totals(live.filter(direction="withdrawal")),
            "reversed": totals(rows.filter(reversed=True)),
            "foreign_currency": totals(live.exclude(currency__in=("", "KENYAN SHILLING"))),
            "branches": len(by_branch),
            "customers": live.values("customer_id").distinct().count(),
            "by_branch": by_branch, "by_type": by_type, "top_customers": customers,
        })


class LargeCashTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LargeCashTransaction
        fields = ("id", "trx_date", "posted_at", "branch", "transaction_type",
                  "direction", "account_number", "customer_id", "account_name",
                  "currency", "amount", "amount_kes", "teller", "teller_name",
                  "channel", "comments", "reversed")


class TransactionListView(DynamicColumnSearchListView):
    """The transactions behind the summary, filterable by any column, and
    downloadable whole (?download=csv|xlsx)."""

    permission_classes = [IsAuthenticated, MayView]
    serializer_class = LargeCashTransactionSerializer
    search_model = LargeCashTransaction
    IGNORED_PARAMS = DynamicColumnSearchListView.IGNORED_PARAMS | {"date", "start", "end"}

    def get_base_queryset(self):
        start, end = _span(self.request)
        qs = LargeCashTransaction.objects.all()
        if start and end:
            qs = qs.filter(trx_date__range=(start, end))
        return qs.order_by("-trx_date", "-amount_kes")


class RefreshView(APIView):
    """Read the lake again now, behind the page (administrators)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_superuser:
            return Response({"detail": "Only an administrator can refresh."}, status=403)
        lake.forget_recent()
        return Response({"refresh": lake.refresh_in_background()})
