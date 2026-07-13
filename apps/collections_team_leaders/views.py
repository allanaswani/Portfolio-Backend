from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
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


@extend_schema(tags=["Collections TL — Repayments"])
class LoanRepaymentsListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoanRepaymentsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "loan_account_number", "channel_id", "product_id"]
    queryset = LoanRepayments.objects.all()


# ── Collections-TL dashboard (ported from the old backend, TL-scoped) ───────

@extend_schema(tags=["Collections TL — Dashboard"])
class TLCurrentBookRmSummaryView(APIView):
    """Whole collections book by delay officer (TL view)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cc.all_current_book_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLTeamLeaderCurrentBookRmSummaryView(APIView):
    """Per-delay-officer current book with arrears/overdue detail (TL officer list)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cc.team_leader_current_book_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLTotalBookMonthByMonthView(APIView):
    """Whole-book month-by-month collection trend (TL view)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cc.team_leader_delay_officer_collection_trends_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLTotalBookByBucketSummaryView(APIView):
    """Whole book grouped by arrears bucket (TL view)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cc.total_accounts_by_bucket_book_summary())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLCustomerCollectionDataView(APIView):
    """Per-customer current book collection data (all rows)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cc.customer_collection_data_current_book_data())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLRepaymentDataEomView(APIView):
    """EOM repayment summary across the team's book (TL view)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cc.Repayment_data_eom_summary_data())


@extend_schema(tags=["Collections TL — Dashboard"])
class TLCollectionsFeedbackView(APIView):
    """Collections feedback summary for the TL's book."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(CollectionSerializer(cc.CollectionsTLSummary(), many=True).data)


@extend_schema(tags=["Collections TL — Repayments"])
class LoanRepaymentsDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoanRepaymentsSerializer
    queryset = LoanRepayments.objects.all()
