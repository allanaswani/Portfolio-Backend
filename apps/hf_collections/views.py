from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404

from core.pagination import StandardPagination
from core.permissions import TlCollectionPermissions, ExcoPermissions
from apps.portfolio.models import Profile
from .models import Collection
from .serializers import CollectionSerializer
from . import collections_core as cc
import django_filters.rest_framework


def _get_profile(user):
    return get_object_or_404(Profile, user_id=user.id)


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
            data = cc.total_collection_trends_summary()
        else:
            data = cc.delay_officer_collection_trends_summary(profile.sales_code)
        return Response(data)


@extend_schema(tags=["Collections — Dashboard"])
class CustomerCollectionDataCurrentBookView(APIView):
    """Per-customer current book collection data (all rows, as the old backend)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cc.customer_collection_data_current_book_data())


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
