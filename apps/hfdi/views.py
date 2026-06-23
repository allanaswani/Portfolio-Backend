from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination, LargePagination
from core.search import DynamicColumnSearchListView
from apps.staff_management.views import BaseCsvUploadView
import django_filters.rest_framework

from . import services

from .models import (
    Project, Targets, Sales, ObligationSummary, CrmProject, CrmSalesRecord,
    LegacyProject, LegacySalesRecord, HfdiManualFinanceEntry, HfdiTargets,
    HfdiEmployeeData, HfdiEmployeeDataSalesRecord, HfdiScorecardPerformanceRecord,
    WeightedDashboardManualSales, HfdiCustomersHfcMortgages,
    HfdiProjectsDailyCollectionsData, HfdiProjectsInventorySalesData,
    AffordableHousingApplication, AffordableHousingRegistrations,
    AffordableHousingProjectsPipeline, AFHSellerMapping,
)
from .serializers import (
    ProjectSerializer, TargetsSerializer, SalesSerializer, ObligationSummarySerializer,
    CrmProjectSerializer, CrmSalesRecordSerializer, LegacyProjectSerializer,
    LegacySalesRecordSerializer, HfdiManualFinanceEntrySerializer, HfdiTargetsSerializer,
    HfdiEmployeeDataSerializer, HfdiEmployeeDataSalesRecordSerializer,
    HfdiScorecardPerformanceRecordSerializer, WeightedDashboardManualSalesSerializer,
    HfdiCustomersHfcMortgagesSerializer, HfdiProjectsDailyCollectionsDataSerializer,
    HfdiProjectsInventorySalesDataSerializer, AffordableHousingApplicationSerializer,
    AffordableHousingRegistrationsSerializer, AffordableHousingProjectsPipelineSerializer,
    AFHSellerMappingSerializer,
)


@extend_schema(tags=["HFDI — Projects"])
class ProjectListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()


@extend_schema(tags=["HFDI — Projects"])
class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()


@extend_schema(tags=["HFDI — Targets"])
class TargetsListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TargetsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project", "month", "pm"]
    queryset = Targets.objects.all()


@extend_schema(tags=["HFDI — Targets"])
class TargetsDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TargetsSerializer
    queryset = Targets.objects.all()


@extend_schema(tags=["HFDI — Sales"])
class SalesListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SalesSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project", "pm", "month"]
    queryset = Sales.objects.all()


@extend_schema(tags=["HFDI — Sales"])
class SalesDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SalesSerializer
    queryset = Sales.objects.all()


@extend_schema(tags=["HFDI — Obligations"])
class ObligationSummaryListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ObligationSummarySerializer
    pagination_class = StandardPagination
    queryset = ObligationSummary.objects.all()


@extend_schema(tags=["HFDI — Obligations"])
class ObligationSummaryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ObligationSummarySerializer
    queryset = ObligationSummary.objects.all()


@extend_schema(tags=["HFDI — CRM Projects"])
class CrmProjectListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmProjectSerializer
    queryset = CrmProject.objects.all()


@extend_schema(tags=["HFDI — CRM Projects"])
class CrmProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmProjectSerializer
    queryset = CrmProject.objects.all()


@extend_schema(tags=["HFDI — CRM Sales"])
class CrmSalesRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmSalesRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "sale_month"]
    queryset = CrmSalesRecord.objects.all()


@extend_schema(tags=["HFDI — CRM Sales"])
class CrmSalesRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CrmSalesRecordSerializer
    queryset = CrmSalesRecord.objects.all()


@extend_schema(tags=["HFDI — Legacy Projects"])
class LegacyProjectListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacyProjectSerializer
    queryset = LegacyProject.objects.all()


@extend_schema(tags=["HFDI — Legacy Projects"])
class LegacyProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacyProjectSerializer
    queryset = LegacyProject.objects.all()


@extend_schema(tags=["HFDI — Legacy Sales"])
class LegacySalesRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacySalesRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "sale_month"]
    queryset = LegacySalesRecord.objects.all()


@extend_schema(tags=["HFDI — Legacy Sales"])
class LegacySalesRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LegacySalesRecordSerializer
    queryset = LegacySalesRecord.objects.all()


@extend_schema(tags=["HFDI — Manual Finance"])
class HfdiManualFinanceEntryListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiManualFinanceEntrySerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "sale_month"]
    queryset = HfdiManualFinanceEntry.objects.all()


@extend_schema(tags=["HFDI — Manual Finance"])
class HfdiManualFinanceEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiManualFinanceEntrySerializer
    queryset = HfdiManualFinanceEntry.objects.all()


@extend_schema(tags=["HFDI — Performance Targets"])
class HfdiTargetsListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiTargetsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_id", "pm", "rm", "is_active"]
    queryset = HfdiTargets.objects.all()


@extend_schema(tags=["HFDI — Performance Targets"])
class HfdiTargetsDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiTargetsSerializer
    queryset = HfdiTargets.objects.all()


@extend_schema(tags=["HFDI — Employees"])
class HfdiEmployeeDataListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["staff_pf_number", "staff_role", "primary_project", "active"]
    queryset = HfdiEmployeeData.objects.all()


@extend_schema(tags=["HFDI — Employees"])
class HfdiEmployeeDataDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSerializer
    queryset = HfdiEmployeeData.objects.all()


@extend_schema(tags=["HFDI — Employee Sales"])
class HfdiEmployeeDataSalesRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSalesRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["staff_pf_number", "sale_month"]
    queryset = HfdiEmployeeDataSalesRecord.objects.all()


@extend_schema(tags=["HFDI — Employee Sales"])
class HfdiEmployeeDataSalesRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiEmployeeDataSalesRecordSerializer
    queryset = HfdiEmployeeDataSalesRecord.objects.all()


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiScorecardPerformanceRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["staff_pf_number", "scorecard_month"]
    queryset = HfdiScorecardPerformanceRecord.objects.all()


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiScorecardPerformanceRecordSerializer
    queryset = HfdiScorecardPerformanceRecord.objects.all()


# ── Employees: search + CSV upload ─────────────────────────────────────────────

@extend_schema(tags=["HFDI — Employees"])
class HfdiEmployeeDataSearchAPIView(DynamicColumnSearchListView):
    serializer_class = HfdiEmployeeDataSerializer
    search_model = HfdiEmployeeData


@extend_schema(tags=["HFDI — Employees"])
class HfdiEmployeeDataCSVUploadView(BaseCsvUploadView):
    serializer_class = HfdiEmployeeDataSerializer


@extend_schema(tags=["HFDI — Employee Sales"])
class HfdiEmployeeDataSalesRecordSearchAPIView(DynamicColumnSearchListView):
    serializer_class = HfdiEmployeeDataSalesRecordSerializer
    search_model = HfdiEmployeeDataSalesRecord


@extend_schema(tags=["HFDI — Employee Sales"])
class HfdiEmployeeDataSalesRecordCSVUploadView(BaseCsvUploadView):
    serializer_class = HfdiEmployeeDataSalesRecordSerializer


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardSearchAPIView(DynamicColumnSearchListView):
    serializer_class = HfdiScorecardPerformanceRecordSerializer
    search_model = HfdiScorecardPerformanceRecord


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardCSVUploadView(BaseCsvUploadView):
    serializer_class = HfdiScorecardPerformanceRecordSerializer


@extend_schema(tags=["HFDI — Weighted Dashboard"])
class WeightedDashboardManualSalesListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WeightedDashboardManualSalesSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_name", "unit_status", "sale_month"]
    queryset = WeightedDashboardManualSales.objects.all()


@extend_schema(tags=["HFDI — Weighted Dashboard"])
class WeightedDashboardManualSalesDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WeightedDashboardManualSalesSerializer
    queryset = WeightedDashboardManualSales.objects.all()


@extend_schema(tags=["HFDI — Weighted Dashboard"])
class WeightedDashboardManualSalesSearchAPIView(DynamicColumnSearchListView):
    serializer_class = WeightedDashboardManualSalesSerializer
    search_model = WeightedDashboardManualSales


@extend_schema(tags=["HFDI — Weighted Dashboard"])
class WeightedDashboardManualSalesCSVUploadView(BaseCsvUploadView):
    serializer_class = WeightedDashboardManualSalesSerializer


@extend_schema(tags=["HFDI — Mortgages"])
class HfdiCustomersHfcMortgagesListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiCustomersHfcMortgagesSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project", "status", "mortgage_stage", "payment_type"]
    queryset = HfdiCustomersHfcMortgages.objects.all()


@extend_schema(tags=["HFDI — Mortgages"])
class HfdiCustomersHfcMortgagesDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiCustomersHfcMortgagesSerializer
    queryset = HfdiCustomersHfcMortgages.objects.all()


@extend_schema(tags=["HFDI — Mortgages"])
class HfdiCustomersHfcMortgagesSearchAPIView(DynamicColumnSearchListView):
    serializer_class = HfdiCustomersHfcMortgagesSerializer
    search_model = HfdiCustomersHfcMortgages


@extend_schema(tags=["HFDI — Mortgages"])
class HfdiCustomersHfcMortgagesCSVUploadView(BaseCsvUploadView):
    serializer_class = HfdiCustomersHfcMortgagesSerializer


# Daily Collections and Inventory Sales are unmanaged warehouse tables
# (managed=False) — the DB router blocks writes, so they are read-only: list +
# dynamic search only (no create/upload).

@extend_schema(tags=["HFDI — Daily Collections"])
class HfdiProjectsDailyCollectionsDataListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiProjectsDailyCollectionsDataSerializer
    pagination_class = LargePagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_name", "sale_month", "paid_month"]
    queryset = HfdiProjectsDailyCollectionsData.objects.all()


@extend_schema(tags=["HFDI — Daily Collections"])
class HfdiProjectsDailyCollectionsDataSearchAPIView(DynamicColumnSearchListView):
    serializer_class = HfdiProjectsDailyCollectionsDataSerializer
    search_model = HfdiProjectsDailyCollectionsData
    pagination_class = LargePagination


@extend_schema(tags=["HFDI — Inventory Sales"])
class HfdiProjectsInventorySalesDataListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HfdiProjectsInventorySalesDataSerializer
    pagination_class = LargePagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_name", "unit_status", "sale_month"]
    queryset = HfdiProjectsInventorySalesData.objects.all()


@extend_schema(tags=["HFDI — Inventory Sales"])
class HfdiProjectsInventorySalesDataSearchAPIView(DynamicColumnSearchListView):
    serializer_class = HfdiProjectsInventorySalesDataSerializer
    search_model = HfdiProjectsInventorySalesData
    pagination_class = LargePagination


@extend_schema(tags=["HFDI — Affordable Housing"])
class AffordableHousingApplicationListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingApplicationSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["status", "typology", "mode_of_payment", "house_type"]
    queryset = AffordableHousingApplication.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing"])
class AffordableHousingApplicationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingApplicationSerializer
    queryset = AffordableHousingApplication.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing"])
class AffordableHousingApplicationSearchAPIView(DynamicColumnSearchListView):
    serializer_class = AffordableHousingApplicationSerializer
    search_model = AffordableHousingApplication

# TODO - Amend the below CSV upload as it has its own custom implementation for amendments on certain columns - reference the old codebase
@extend_schema(tags=["HFDI — Affordable Housing"])
class AffordableHousingApplicationCSVUploadView(BaseCsvUploadView):
    serializer_class = AffordableHousingApplicationSerializer


# ── Affordable Housing Registrations ───────────────────────────────────────────

@extend_schema(tags=["HFDI — Affordable Housing Registrations"])
class AffordableHousingRegistrationsListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingRegistrationsSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project", "typology", "house_type", "assisted_by"]
    queryset = AffordableHousingRegistrations.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing Registrations"])
class AffordableHousingRegistrationsDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingRegistrationsSerializer
    queryset = AffordableHousingRegistrations.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing Registrations"])
class AffordableHousingRegistrationsSearchAPIView(DynamicColumnSearchListView):
    serializer_class = AffordableHousingRegistrationsSerializer
    search_model = AffordableHousingRegistrations


# TODO - Amend the below CSV upload as it has its own custom implementation for amendments on certain columns - reference the old codebase
@extend_schema(tags=["HFDI — Affordable Housing Registrations"])
class AffordableHousingRegistrationsCSVUploadView(BaseCsvUploadView):
    serializer_class = AffordableHousingRegistrationsSerializer


# ── Affordable Housing Projects Pipeline ───────────────────────────────────────

@extend_schema(tags=["HFDI — Affordable Housing Pipeline"])
class AffordableHousingProjectsPipelineListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingProjectsPipelineSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["project_name", "region", "county"]
    queryset = AffordableHousingProjectsPipeline.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing Pipeline"])
class AffordableHousingProjectsPipelineDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AffordableHousingProjectsPipelineSerializer
    queryset = AffordableHousingProjectsPipeline.objects.all()


@extend_schema(tags=["HFDI — Affordable Housing Pipeline"])
class AffordableHousingProjectsPipelineSearchAPIView(DynamicColumnSearchListView):
    serializer_class = AffordableHousingProjectsPipelineSerializer
    search_model = AffordableHousingProjectsPipeline


@extend_schema(tags=["HFDI — Affordable Housing Pipeline"])
class AffordableHousingProjectsPipelineCSVUploadView(BaseCsvUploadView):
    serializer_class = AffordableHousingProjectsPipelineSerializer


# ── AFH Seller Mapping ─────────────────────────────────────────────────────────

@extend_schema(tags=["HFDI — AFH Seller Mapping"])
class AFHSellerMappingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AFHSellerMappingSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["staff_id", "staff_unit", "org_unit"]
    queryset = AFHSellerMapping.objects.all()


@extend_schema(tags=["HFDI — AFH Seller Mapping"])
class AFHSellerMappingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AFHSellerMappingSerializer
    queryset = AFHSellerMapping.objects.all()


@extend_schema(tags=["HFDI — AFH Seller Mapping"])
class AFHSellerMappingSearchAPIView(DynamicColumnSearchListView):
    serializer_class = AFHSellerMappingSerializer
    search_model = AFHSellerMapping


@extend_schema(tags=["HFDI — AFH Seller Mapping"])
class AFHSellerMappingCSVUploadView(BaseCsvUploadView):
    serializer_class = AFHSellerMappingSerializer


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard aggregations / chart endpoints (raw SQL via apps.hfdi.services)
# ══════════════════════════════════════════════════════════════════════════════

@extend_schema(tags=["HFDI — Dashboards"])
class HfdiSalesMonthsRecordedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.months_already_entered())


@extend_schema(tags=["HFDI — Dashboards"])
class ProjectsMonthlyPerformanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.projects_monthly_performance())


@extend_schema(tags=["HFDI — Dashboards"])
class HfdiMonthlyVolumeSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.monthly_pivot_summary("mtd_volume"))


@extend_schema(tags=["HFDI — Dashboards"])
class HfdiMonthlyValueSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.monthly_pivot_summary("mtd_value"))


@extend_schema(tags=["HFDI — Dashboards"])
class HfdiMonthlyYtdIncomeSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.monthly_pivot_summary("ytd_income"))


@extend_schema(tags=["HFDI — Dashboards"])
class HfdiYtdPerformanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.revenue_point_ytd())


@extend_schema(tags=["HFDI — Dashboards"])
class HfdiYtdPerformancePerProjectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.revenue_point_ytd_by_project())


@extend_schema(tags=["HFDI — Projects"])
class CombinedProjectsView(APIView):
    """CRM projects + legacy projects, combined (for project pickers)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        crm = CrmProjectSerializer(CrmProject.objects.all(), many=True).data
        legacy = LegacyProjectSerializer(LegacyProject.objects.all(), many=True).data
        return Response(list(crm) + list(legacy))
