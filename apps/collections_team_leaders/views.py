from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.pagination import StandardPagination
from apps.hf_collections import collections_core as cc
from apps.hf_collections.models import Collection
from apps.hf_collections.serializers import CollectionSerializer
from .models import LoanRepayments
from .serializers import LoanRepaymentsSerializer
import django_filters.rest_framework

from core.permissions import InGroup

# Every endpoint in this app returns the WHOLE collections book - all delay
# officers, every customer. All nine were open to any authenticated user, while
# apps/hf_collections scoped the same dashboard per user, so calling the TL URL
# simply bypassed that scoping.
#
# The group set mirrors _is_team_level() in apps/hf_collections/views.py (TL or
# Exco) rather than inventing a new rule, plus "ceo". Gating on tl_collection
# alone would lock out Exco users who can see this dashboard today. InGroup
# admits superusers itself, which is also why this gap stayed invisible to
# anyone testing as one.
TeamLevelCollections = InGroup("tl_collection", "exco", "ceo")


@extend_schema(tags=["Collections TL — Repayments"])
class LoanRepaymentsListView(generics.ListAPIView):
    permission_classes = [TeamLevelCollections]
    serializer_class = LoanRepaymentsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "loan_account_number", "channel_id", "product_id"]
    queryset = LoanRepayments.objects.all()


# ── Collections-TL dashboard (ported from the old backend, TL-scoped) ───────

@extend_schema(tags=["Collections TL — Dashboard"])
class TLCurrentBookRmSummaryView(APIView):
    """Whole collections book by delay officer (TL view)."""
    permission_classes = [TeamLevelCollections]

    def get(self, request):
        return Response(cc.all_current_book_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLTeamLeaderCurrentBookRmSummaryView(APIView):
    """Per-delay-officer current book with arrears/overdue detail (TL officer list)."""
    permission_classes = [TeamLevelCollections]

    def get(self, request):
        return Response(cc.team_leader_current_book_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLTotalBookMonthByMonthView(APIView):
    """Whole-book month-by-month collection trend (TL view)."""
    permission_classes = [TeamLevelCollections]

    def get(self, request):
        return Response(cc.team_leader_delay_officer_collection_trends_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLTotalBookByBucketSummaryView(APIView):
    """Whole book grouped by arrears bucket (TL view)."""
    permission_classes = [TeamLevelCollections]

    def get(self, request):
        return Response(cc.total_accounts_by_bucket_book_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLCustomerCollectionDataView(APIView):
    """Per-customer current book collection data (all rows)."""
    permission_classes = [TeamLevelCollections]

    def get(self, request):
        return Response(cc.customer_collection_data_current_book_data())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLRepaymentDataEomView(APIView):
    """EOM repayment summary across the team's book (TL view)."""
    permission_classes = [TeamLevelCollections]

    def get(self, request):
        return Response(cc.Repayment_data_eom_summary_data())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLCollectionsFeedbackView(APIView):
    """Collections feedback summary for the TL's book."""
    permission_classes = [TeamLevelCollections]

    def get(self, request):
        return Response(CollectionSerializer(cc.CollectionsTLSummary(), many=True).data)


@extend_schema(tags=["Collections TL — Repayments"])
class LoanRepaymentsDetailView(generics.RetrieveAPIView):
    permission_classes = [TeamLevelCollections]
    serializer_class = LoanRepaymentsSerializer
    queryset = LoanRepayments.objects.all()
