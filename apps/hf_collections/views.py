from rest_framework import generics, status
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
    """The collections diary.

    Filtered, and scoped. Both had to be fixed together.

    The customer page asked for ``?account_no=<id>``. There is no
    ``account_no`` on this model - it is ``loan_account_no`` - and it was not
    a declared filter either, so django-filter ignored it and the request
    came back with every collections entry in the bank, shown on one
    customer's page as their own contact history.

    So an unrecognised filter is refused rather than ignored. A list endpoint
    that quietly drops a filter and returns the whole table turns a typo into
    a disclosure, and the caller gets no hint that anything went wrong.

    And the queryset is the officer's own book. This view read
    ``Collection.objects.all()`` for anybody authenticated, while its five
    siblings in this module all scoped on ``_is_team_level``.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CollectionSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "loan_account_no",
                        "collection_officer_code", "collection_status",
                        "recording_date"]
    queryset = Collection.objects.all()

    #: Query parameters that are not filters. Everything else must be a
    #: declared filter or the request is refused.
    NOT_FILTERS = {"page", "page_size", "limit", "offset", "ordering",
                   "format", "search"}

    def list(self, request, *args, **kwargs):
        unknown = sorted(
            set(request.query_params) - set(self.filterset_fields)
            - self.NOT_FILTERS)
        if unknown:
            return Response(
                {"detail": (
                    f"Not a filter on the collections diary: "
                    f"{', '.join(unknown)}. This is refused rather than "
                    f"ignored, because ignoring it would return every entry "
                    f"in the bank. The filters are: "
                    f"{', '.join(self.filterset_fields)}."),
                 "unknown_filters": unknown,
                 "filters": list(self.filterset_fields)},
                status=status.HTTP_400_BAD_REQUEST)
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        rows = Collection.objects.all()
        if _is_team_level(self.request, self):
            return rows
        code = (_get_profile(self.request.user).sales_code or "").strip()
        if not code:
            # No sales code means no book. An empty diary is the honest
            # answer; the whole bank's is not.
            return rows.none()
        return rows.filter(collection_officer_code__iexact=code)


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


def _a_date(value):
    """``YYYY-MM-DD`` from a query string → date, or None.

    None rather than an error: a malformed date in a filter should fall back
    to the default window, not refuse to show the page.
    """
    import datetime

    try:
        return datetime.date.fromisoformat(str(value).strip())
    except Exception:  # noqa: BLE001
        return None


# ── The customer page ────────────────────────────────────────────────────────

@extend_schema(tags=["Collections"])
class CustomerProfileView(APIView):
    """Everything about one customer, in one read.

    The page was showing a dash for product, loan type, branch and bucket -
    the front end read those keys and the API returned none of them - and
    "# Contacts 0", where that count was the number of DIARY entries rather
    than the customer's phone numbers. A customer nobody has called is not a
    customer with no number.

    Scoped: an officer sees a customer who is on their own book, by core
    banking's assignment or by an allocation made here. A team leader sees
    anybody. Without this an officer could read any customer in the bank by
    changing the number in the URL.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cust_id):
        from . import customer_profile
        from .models import CollectionAllocation

        data = customer_profile.profile(cust_id)

        if not _is_team_level(request, self):
            code = (_get_profile(request.user).sales_code or "").strip()
            mine = {o.lower() for o in data["delay_officers"]}
            allocated = CollectionAllocation.objects.filter(
                cust_id=cust_id, is_active=True,
                collection_officer_code__iexact=code).exists()
            if not code or (code.lower() not in mine and not allocated):
                return Response(
                    {"detail": "That customer is not on your book."},
                    status=status.HTTP_403_FORBIDDEN)

        return Response(data)


# ── What an officer is carrying, and what they brought in ────────────────────

@extend_schema(tags=["Collections"])
class OfficerContributionView(APIView):
    """One officer's book, collections, promises and diary.

    Defaults to the signed-in officer. A team leader may ask for anybody by
    passing ``collection_officer_code``; an officer asking for somebody else
    is given their own, rather than an error - the question "how am I doing"
    has an answer either way.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import officer as officer_module

        asked = str(request.query_params.get("collection_officer_code")
                    or "").strip()
        own = (_get_profile(request.user).sales_code or "").strip()
        code = asked if (asked and _is_team_level(request, self)) else own

        if not code:
            return Response(
                {"detail": "Your profile has no sales code, so there is no "
                           "book to report on."},
                status=status.HTTP_400_BAD_REQUEST)

        return Response(officer_module.contribution(
            code,
            since=_a_date(request.query_params.get("from")),
            until=_a_date(request.query_params.get("to"))))


@extend_schema(tags=["Collections"])
class OfficerLeaderboardView(APIView):
    """Every officer holding delinquent loans, by what came in.

    Team leaders only. An officer comparing themselves against named
    colleagues is a different conversation from a team leader running a desk,
    and this screen is the second one.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import officer as officer_module

        if not _is_team_level(request, self):
            return Response(
                {"detail": "Only a team leader can see the whole desk."},
                status=status.HTTP_403_FORBIDDEN)

        return Response(officer_module.leaderboard(
            since=_a_date(request.query_params.get("from")),
            until=_a_date(request.query_params.get("to"))))


# ── Allocation ───────────────────────────────────────────────────────────────

@extend_schema(tags=["Collections"])
class CollectionAllocationView(APIView):
    """Hand the customers nobody is calling to the officers who can.

    GET  lists who is waiting, and what a run would do.
    POST does it, and only with ``confirm``.

    Never touches ``loans``: that table is rewritten from core banking every
    night, so a write there is gone by morning. Allocations live in
    ``hf_collections_allocation`` and an officer's book is the union of the
    two. A customer core banking HAS assigned is never moved - that is
    another system making a decision, and overriding it quietly is how two
    desks end up believing different things about who is calling whom.
    """

    permission_classes = [IsAuthenticated]

    def _officers(self, request):
        """Who to allocate to.

        Named in the request, or every officer who already holds delinquent
        loans - which is the team, as core banking understands it.
        """
        from . import officer as officer_module

        given = request.data.get("officers") or request.query_params.get(
            "officers") or []
        if isinstance(given, str):
            given = [part.strip() for part in given.split(",") if part.strip()]
        if given:
            return given

        return [row["collection_officer_code"]
                for row in officer_module.leaderboard()]

    def get(self, request):
        from . import allocation

        if not _is_team_level(request, self):
            return Response(
                {"detail": "Only a team leader can allocate customers."},
                status=status.HTTP_403_FORBIDDEN)

        limit = request.query_params.get("limit")
        assignments, report = allocation.plan(
            self._officers(request),
            limit=int(limit) if limit else None,
            branch=request.query_params.get("branch") or None)
        return Response({
            "allocated": False, "report": report,
            "would_assign": assignments[:200],
            "detail": (
                f"{report['unallocated']} customer(s) are on nobody's book. "
                f"{report['assigned']} would be shared across "
                f"{report['officers']} officer(s). Nothing has been written - "
                f"send it again with confirm."),
        })

    def post(self, request):
        from . import allocation

        if not _is_team_level(request, self):
            return Response(
                {"detail": "Only a team leader can allocate customers."},
                status=status.HTTP_403_FORBIDDEN)

        if str(request.data.get("confirm", "")).lower() not in ("1", "true",
                                                                 "yes"):
            return self.get(request)

        limit = request.data.get("limit")
        assignments, report = allocation.plan(
            self._officers(request),
            limit=int(limit) if limit else None,
            branch=request.data.get("branch") or None)
        if not assignments:
            return Response({
                "allocated": False, "report": report,
                "detail": "There is nobody waiting to be allocated."})

        written = allocation.save(
            assignments,
            who=(getattr(request.user, "get_full_name", lambda: "")()
                 or getattr(request.user, "username", "")),
            note=str(request.data.get("note") or ""))
        return Response({
            "allocated": True, "written": written, "report": report,
            "detail": (f"{written} customer(s) allocated. They show on the "
                       f"officers' own screens straight away."),
        })
