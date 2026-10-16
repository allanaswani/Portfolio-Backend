from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404

from core.pagination import StandardPagination
from core.permissions import TlCollectionPermissions, ExcoPermissions
from apps.portfolio.models import Profile
from .models import Collection, PromiseToPay
from .serializers import CollectionSerializer, PromiseToPaySerializer
from . import collections_core as cc
import django_filters.rest_framework


def _get_profile(user):
    return get_object_or_404(Profile, user_id=user.id)


_TREND_TTL = 30 * 60


def _cached(key, compute, ttl=_TREND_TTL):
    """The month-by-month trend scans a year of loans_history and is slow enough
    that the proxy gives up on it (502) before Django answers. The numbers only
    change when the nightly ETL lands, so half an hour of cache costs nothing."""
    value = cache.get(key)
    if value is None:
        value = compute()
        cache.set(key, value, ttl)
    return value


def _is_team_level(request, view):
    """TL / Exco see the whole collections book; everyone else sees their own."""
    return (
        TlCollectionPermissions().has_permission(request, view)
        or ExcoPermissions().has_permission(request, view)
    )


@extend_schema(tags=["Collections"])
class CollectionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CollectionSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "collection_officer_code", "collection_status", "recording_date"]
    queryset = Collection.objects.all()


@extend_schema(tags=["Collections"])
class CollectionsFeedbackSummaryView(APIView):
    """KPI tiles for the Collections Diary — computed server-side.

    The diary page used to pull the ENTIRE feedback table into the browser just to
    show three counts (total / contacted / not-contacted) and to page a table
    client-side. Now the table loads one page at a time, so these tiles need their
    own tiny aggregate. Honours the same optional filters as the list view so the
    tiles stay consistent if the page filters by officer / status. Matches the old
    client logic: "contacted" == contactibility is exactly 'contacted' or
    'reachable' (case-insensitive)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Collection.objects.all()
        officer = request.query_params.get("collection_officer_code")
        if officer:
            qs = qs.filter(collection_officer_code=officer)
        status_filter = request.query_params.get("collection_status")
        if status_filter:
            qs = qs.filter(collection_status=status_filter)

        total = qs.count()
        contacted = qs.filter(
            Q(contactibility__iexact="contacted") | Q(contactibility__iexact="reachable")
        ).count()
        return Response({
            "total": total,
            "contacted": contacted,
            "not_contacted": total - contacted,
        })


@extend_schema(tags=["Collections"])
class CollectionDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CollectionSerializer
    queryset = Collection.objects.all()


@extend_schema(tags=["Collections"])
class CollectionSearchView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CollectionSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "loan_account_no", "collection_officer_code", "collection_status"]
    queryset = Collection.objects.all()


# ── Collections dashboard (ported from the old backend) ─────────────────────

@extend_schema(tags=["Collections — Dashboard"])
class CurrentBookCollectionSummaryView(APIView):
    """Current book by delay officer. Agent → own book; TL/Exco → whole book."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if _is_team_level(request, self):
            data = cc.all_current_book_summary()
        else:
            data = cc.current_book_summary(profile.sales_code)
        return Response(data)


@extend_schema(tags=["Collections — Dashboard"])
class TotalBookMonthByMonthView(APIView):
    """Month-by-month collection book trend. Agent → own; TL/Exco → whole book."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if _is_team_level(request, self):
            data = _cached("collections:trends:book",
                           cc.total_collection_trends_summary)
        else:
            code = profile.sales_code or ""
            data = _cached(f"collections:trends:{code}",
                           lambda: cc.delay_officer_collection_trends_summary(code))
        return Response(data)


@extend_schema(tags=["Collections — Dashboard"])
class CustomerCollectionDataCurrentBookView(APIView):
    """Per-customer current book. Agent -> own book; TL/Exco -> whole book.

    This was the one view in this module that ignored the user entirely and
    returned every customer in the book to anyone logged in, while its five
    siblings all scoped on ``_is_team_level``. The scoped query it needed was
    already written - ``customer_collection_data_current_book_data_not_rm`` in
    ``collections_core`` - and was called from nowhere. Both queries return
    identical keys, so this is a straight swap.

    Pagination is opt-in: pass ``?page=`` and the response is a paginated
    envelope, otherwise it stays the bare list the frontend already parses.
    Changing the shape unconditionally would break every existing caller, and a
    page cap applied silently would make any client-side total under-count -
    which is the trap this codebase has hit before.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if _is_team_level(request, self):
            rows = _cached("collections:custbook:all",
                           cc.customer_collection_data_current_book_data)
        else:
            code = _get_profile(request.user).sales_code or ""
            rows = _cached(
                f"collections:custbook:{code}",
                lambda: cc.customer_collection_data_current_book_data_not_rm(code),
            )

        if "page" in request.query_params:
            paginator = StandardPagination()
            page = paginator.paginate_queryset(rows, request, view=self)
            return paginator.get_paginated_response(page)
        return Response(rows)


@extend_schema(tags=["Collections — Dashboard"])
class CollectionsContactibilitySummaryView(APIView):
    """YTD contactibility breakdown for the logged-in collection officer."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                select 1 as id, contactibility, count(*)
                from hf_collections_feedback
                where lower(trim(collection_officer_code)) = lower(%s)
                  and date_trunc('year', recording_date) >= date_trunc('year', now())
                group by contactibility
            """, [profile.sales_code])
            rows = [{"contactibility": r[1], "count": r[2]} for r in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Collections — Dashboard"])
class CollectionsOfficerFeedbackByStatusView(APIView):
    """YTD feedback counts grouped by collection status, for the logged-in officer."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                select 1 as id, pmf.collection_status, COUNT(*) AS total_leads
                from hf_collections_feedback pmf
                where date_trunc('year', pmf.recording_date) >= date_trunc('year', now())
                  and pmf.collection_officer_code = %s
                group by pmf.collection_status
            """, [profile.sales_code])
            rows = [{"id": r[0], "collection_status": r[1], "total_leads": r[2]} for r in cur.fetchall()]
        return Response(rows)


@extend_schema(tags=["Collections — Dashboard"])
class CollectionsOfficerFeedbackContactabilityView(APIView):
    """YTD contactability (allocation / contacted / not_contacted / percent) for
    the logged-in officer, over their allocated loans book."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        with connection.cursor() as cur:
            cur.execute("""
                with collection_officer_feedback as (
                    select
                        l.cust_id,
                        l.delay_officer,
                        count(distinct hf_collections_feedback.cust_id) filter (
                            where date_trunc('year', hf_collections_feedback.recording_date) >= date_trunc('year', now())
                              and l.delay_officer = hf_collections_feedback.collection_officer_code) as ytd
                    from loans l
                    left join hf_collections_feedback on hf_collections_feedback.cust_id = l.cust_id
                    where lower(trim(l.delay_officer)) = lower(%s)
                    group by l.cust_id, l.delay_officer
                )
                select
                    1 id,
                    delay_officer,
                    count(cust_id) as allocation,
                    sum(ytd) as contacted,
                    count(cust_id) - sum(ytd) as not_contacted,
                    sum(ytd)::numeric / NULLIF(count(cust_id), 0) as percent_contacted
                from collection_officer_feedback
                group by delay_officer
            """, [profile.sales_code])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return Response(rows)


# ── PTP: Promise To Pay ──────────────────────────────────────────────────────
# The unit of work on a collections desk, and the one number that matters
# about it is not the promise but whether the money came. See
# ``apps.hf_collections.ptp``.

@extend_schema(tags=["Collections"])
class PromiseToPayListCreateView(generics.ListCreateAPIView):
    """Promises, newest due date first.

    ``status`` is not writable here. It is settled against
    ``loan_repayments`` - a collector cannot mark their own promise kept,
    because the kept rate is what the desk is measured on.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PromiseToPaySerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "loan_account_no", "status",
                        "collection_officer_code", "promised_date", "source"]
    queryset = PromiseToPay.objects.all()


@extend_schema(tags=["Collections"])
class PromiseToPayDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PromiseToPaySerializer
    queryset = PromiseToPay.objects.all()


@extend_schema(tags=["Collections"])
class PromiseToPaySummaryView(APIView):
    """The kept rate, and the counts behind it.

    Over DECIDED promises only. A promise that is not yet due is reported
    beside the rate and excluded from it: a desk whose score dropped every
    time a collector booked a promise would learn to stop booking them.

    Part-kept is not rolled into kept. A borrower who promised 50,000 and
    paid 5,000 did not keep their promise, and both numbers are given so the
    desk can see the difference rather than have it averaged away.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import ptp

        rows = PromiseToPay.objects.all()
        officer = request.query_params.get("collection_officer_code")
        if officer:
            rows = rows.filter(collection_officer_code=officer)
        since = request.query_params.get("promised_date_after")
        if since:
            rows = rows.filter(promised_date__gte=since)
        until = request.query_params.get("promised_date_before")
        if until:
            rows = rows.filter(promised_date__lte=until)

        summary = ptp.kept_rate(rows)

        # Per officer, which is what a team leader opens this for.
        by_officer = {}
        for row in rows.values("collection_officer_code",
                               "collection_officer_name", "status"):
            key = row["collection_officer_code"] or "(unassigned)"
            bucket = by_officer.setdefault(key, {
                "collection_officer_code": key,
                "collection_officer_name": row["collection_officer_name"] or "",
                "kept": 0, "part_kept": 0, "broken": 0, "open": 0})
            bucket[row["status"]] = bucket.get(row["status"], 0) + 1
        for bucket in by_officer.values():
            decided = bucket["kept"] + bucket["part_kept"] + bucket["broken"]
            bucket["decided"] = decided
            bucket["kept_rate"] = (round(bucket["kept"] / decided, 4)
                                   if decided else None)

        summary["by_officer"] = sorted(
            by_officer.values(),
            key=lambda b: (b["kept_rate"] is None, -(b["kept_rate"] or 0)))
        return Response(summary)


@extend_schema(tags=["Collections"])
class PromiseToPayRefreshView(APIView):
    """Re-settle the promises against the repayments feed.

    Two things, both idempotent: build promises out of the diary entries that
    already carry a PTP amount and a date, then re-settle everything that
    could still change. Safe to run as often as the feed lands - a kept
    promise is never revisited, because money that arrived cannot un-arrive.

    Also available as ``manage.py settle_ptp`` for the nightly run. This
    endpoint exists so the desk is not waiting on a cron to see today's
    payments reflected.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from . import ptp

        made, read = 0, 0
        if str(request.data.get("from_feedback", "true")).lower() not in (
                "0", "false", "no"):
            made, read = ptp.from_feedback()
        moved = ptp.settle_all()
        return Response({
            "promises_made_from_diary": made,
            "diary_rows_with_a_promise": read,
            "promises_resettled": moved,
            "detail": (
                f"{made} new promise(s) taken from {read} diary entr(ies); "
                f"{moved} promise(s) changed status against the repayments "
                f"feed."),
            **ptp.kept_rate(),
        })
