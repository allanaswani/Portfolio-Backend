from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination
from core.search import DynamicColumnSearchListView
from apps.staff_management.views import BaseCsvUploadView
import django_filters.rest_framework

from .models import (
    CustomerEnrichment, RmTarget, CustomerAllocationBase, RmAllocationList,
    TeamLeaderMovementApprovers, CustomerTransferHistory,
)
from .serializers import (
    CustomerEnrichmentSerializer, RmTargetSerializer,
    CustomerAllocationBaseSerializer, RmAllocationListSerializer,
    TeamLeaderMovementApproversSerializer, CustomerTransferHistorySerializer,
)


@extend_schema(tags=["Portfolio Enrichment — Customers"])
class CustomerEnrichmentListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerEnrichmentSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["income_band", "employment_status", "risk_rating", "data_source"]
    queryset = CustomerEnrichment.objects.all()


@extend_schema(tags=["Portfolio Enrichment — Customers"])
class CustomerEnrichmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerEnrichmentSerializer
    queryset = CustomerEnrichment.objects.all()


@extend_schema(tags=["Portfolio Enrichment — RM Targets"])
class RmTargetListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RmTargetSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "month"]
    queryset = RmTarget.objects.all()


@extend_schema(tags=["Portfolio Enrichment — RM Targets"])
class RmTargetDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RmTargetSerializer
    queryset = RmTarget.objects.all()


# ── Customer–RM reallocation ───────────────────────────────────────────────────

@extend_schema(tags=["Reallocation — Customer Allocation Base"])
class CustomerAllocationBaseListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerAllocationBaseSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["segment", "main_segment", "rm_code", "cust_branch", "proposed_segment"]
    queryset = CustomerAllocationBase.objects.all()


@extend_schema(tags=["Reallocation — Customer Allocation Base"])
class CustomerAllocationBaseDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerAllocationBaseSerializer
    queryset = CustomerAllocationBase.objects.all()


@extend_schema(tags=["Reallocation — Customer Allocation Base"])
class CustomerAllocationBaseSearchAPIView(DynamicColumnSearchListView):
    serializer_class = CustomerAllocationBaseSerializer
    search_model = CustomerAllocationBase


@extend_schema(tags=["Reallocation — Customer Allocation Base"])
class CustomerAllocationBaseCSVUploadView(BaseCsvUploadView):
    serializer_class = CustomerAllocationBaseSerializer


@extend_schema(tags=["Reallocation — RM Allocation List"])
class RmAllocationListListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RmAllocationListSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["rm_code", "rm_role", "rm_segment", "rm_active_status"]
    queryset = RmAllocationList.objects.all()


@extend_schema(tags=["Reallocation — RM Allocation List"])
class RmAllocationListDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RmAllocationListSerializer
    queryset = RmAllocationList.objects.all()


@extend_schema(tags=["Reallocation — RM Allocation List"])
class RmAllocationListSearchAPIView(DynamicColumnSearchListView):
    serializer_class = RmAllocationListSerializer
    search_model = RmAllocationList


@extend_schema(tags=["Reallocation — RM Allocation List"])
class RmAllocationListCSVUploadView(BaseCsvUploadView):
    serializer_class = RmAllocationListSerializer


@extend_schema(tags=["Reallocation — Movement Approvers"])
class TeamLeaderMovementApproversListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeamLeaderMovementApproversSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["segment", "sales_code", "branch_code"]
    queryset = TeamLeaderMovementApprovers.objects.all()


@extend_schema(tags=["Reallocation — Movement Approvers"])
class TeamLeaderMovementApproversDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeamLeaderMovementApproversSerializer
    queryset = TeamLeaderMovementApprovers.objects.all()


@extend_schema(tags=["Reallocation — Movement Approvers"])
class TeamLeaderMovementApproversSearchAPIView(DynamicColumnSearchListView):
    serializer_class = TeamLeaderMovementApproversSerializer
    search_model = TeamLeaderMovementApprovers


@extend_schema(tags=["Reallocation — Movement Approvers"])
class TeamLeaderMovementApproversCSVUploadView(BaseCsvUploadView):
    serializer_class = TeamLeaderMovementApproversSerializer


@extend_schema(tags=["Reallocation — Transfer History"])
class CustomerTransferHistoryListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerTransferHistorySerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "from_rm_code", "to_rm_code", "approval_status"]
    queryset = CustomerTransferHistory.objects.all()


@extend_schema(tags=["Reallocation — Transfer History"])
class CustomerTransferHistoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerTransferHistorySerializer
    queryset = CustomerTransferHistory.objects.all()


@extend_schema(tags=["Reallocation — Transfer History"])
class CustomerTransferHistorySearchAPIView(DynamicColumnSearchListView):
    serializer_class = CustomerTransferHistorySerializer
    search_model = CustomerTransferHistory
