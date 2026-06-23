from datetime import datetime

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination, LargePagination
from core.search import DynamicColumnSearchListView
from core.csv_upload import AmendingCsvUploadView
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


def _first_of_month(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(day=1).strftime("%Y-%m-%d")
    except ValueError:
        return None


class _ManualMonthlyUploadView(AmendingCsvUploadView):
    """
    Shared base for the two employee monthly uploads (sales & scorecard). Both:
    stamp ``input_user`` from the request user, normalise the month column to the 1st,
    reject rows whose staff_pf_number isn't a known employee, and skip duplicates for
    the (staff_pf_number, month) pair. Ported from legacy. Insert-only (no upsert).
    """

    excluded_columns = ("id", "input_user")
    month_field = None  # set by subclass

    def _input_user(self):
        u = self.request.user
        return f"{u.first_name} {u.last_name}".strip()

    def amend_row(self, row):
        row["input_user"] = self._input_user()
        row[self.month_field] = _first_of_month(row.get(self.month_field))

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        pf = data.get("staff_pf_number")
        if not pf or not HfdiEmployeeData.objects.filter(staff_pf_number=pf).exists():
            return "Invalid or non-existent staff_pf_number in employee table"
        month = data.get(self.month_field)
        if self.model.objects.filter(staff_pf_number=pf, **{self.month_field: month}).exists():
            return f"Duplicate record: staff_pf_number and {self.month_field} combination already exists"
        serializer.save()
        return None


@extend_schema(tags=["HFDI — Employee Sales"])
class HfdiEmployeeDataSalesRecordCSVUploadView(_ManualMonthlyUploadView):
    model = HfdiEmployeeDataSalesRecord
    serializer_class = HfdiEmployeeDataSalesRecordSerializer
    result_filename = "hfdi_manual_sales_upload_results"
    month_field = "sale_month"


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardSearchAPIView(DynamicColumnSearchListView):
    serializer_class = HfdiScorecardPerformanceRecordSerializer
    search_model = HfdiScorecardPerformanceRecord


@extend_schema(tags=["HFDI — Scorecard"])
class HfdiScorecardCSVUploadView(_ManualMonthlyUploadView):
    model = HfdiScorecardPerformanceRecord
    serializer_class = HfdiScorecardPerformanceRecordSerializer
    result_filename = "hfdi_scorecard_performance_upload_results"
    month_field = "scorecard_month"


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
class WeightedDashboardManualSalesCSVUploadView(AmendingCsvUploadView):
    """Upsert on (project_name, unit_name, sale_month) — ported from legacy."""

    model = WeightedDashboardManualSales
    serializer_class = WeightedDashboardManualSalesSerializer
    result_filename = "weighted_dashboard_manual_sales_upload_results"

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        WeightedDashboardManualSales.objects.update_or_create(
            project_name=data.get("project_name"),
            unit_name=data.get("unit_name"),
            sale_month=data.get("sale_month"),
            defaults=data,
        )
        return None


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
class HfdiCustomersHfcMortgagesCSVUploadView(AmendingCsvUploadView):
    """Upsert on (project, unit) — ported from legacy."""

    model = HfdiCustomersHfcMortgages
    serializer_class = HfdiCustomersHfcMortgagesSerializer
    result_filename = "hfdi_customers_hfc_mortgages_upload_results"

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        HfdiCustomersHfcMortgages.objects.update_or_create(
            project=data.get("project"),
            unit=data.get("unit"),
            defaults=data,
        )
        return None


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

@extend_schema(tags=["HFDI — Affordable Housing"])
class AffordableHousingApplicationCSVUploadView(AmendingCsvUploadView):
    """Upsert by (phone_number, timestamp); house_type derived from preferred_typology."""

    model = AffordableHousingApplication
    serializer_class = AffordableHousingApplicationSerializer
    result_filename = "affordable_housing_applications_upload_results"
    excluded_columns = ("id", "house_type")

    def amend_row(self, row):
        row["house_type"] = self.derive_parenthesised(row.get("preferred_typology"))
        row["timestamp"] = self.parse_date(row.get("timestamp"), "%d, %B %Y %H:%M")
        for field in ("unit_price", "deposits"):
            row[field] = self.clean_number(row.get(field))

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        AffordableHousingApplication.objects.update_or_create(
            phone_number=data.get("phone_number"),
            timestamp=data.get("timestamp"),
            defaults=data,
        )
        return None


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


@extend_schema(tags=["HFDI — Affordable Housing Registrations"])
class AffordableHousingRegistrationsCSVUploadView(AmendingCsvUploadView):
    """Upsert keyed on phone_number (instance-based); house_type derived from typology."""

    model = AffordableHousingRegistrations
    serializer_class = AffordableHousingRegistrationsSerializer
    result_filename = "affordable_housing_registrations_upload_results"
    excluded_columns = ("id", "house_type")

    def amend_row(self, row):
        row["house_type"] = self.derive_parenthesised(row.get("typology"))
        row["timestamp"] = self.parse_date(row.get("timestamp"), "%d, %B %Y %H:%M")
        for field in ("unit_price", "user_deposits"):
            row[field] = self.clean_number(row.get(field), dash_to_zero=True)

    def build_serializer(self, row):
        phone_number_raw = (row.get("phone_number") or "").strip()
        existing = (
            AffordableHousingRegistrations.objects.filter(phone_number=phone_number_raw).first()
            if phone_number_raw
            else None
        )
        return self.serializer_class(instance=existing, data=row)

    def save_valid(self, row, serializer):
        if not serializer.validated_data.get("phone_number"):
            return {"phone_number": "This field is required for upsert."}
        serializer.save()
        return None


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
class AffordableHousingProjectsPipelineCSVUploadView(AmendingCsvUploadView):
    """Upsert on project_name; cleans the comma-grouped ``units`` column. Ported from legacy."""

    model = AffordableHousingProjectsPipeline
    serializer_class = AffordableHousingProjectsPipelineSerializer
    result_filename = "affordable_housing_projects_pipeline_upload_results"

    def amend_row(self, row):
        row["units"] = self.clean_number(row.get("units"))
        row["completion_date"] = (row.get("completion_date") or "").strip() or None

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        if not data.get("project_name"):
            return {"project_name": "This field is required for upsert."}
        AffordableHousingProjectsPipeline.objects.update_or_create(
            project_name=data.get("project_name"),
            defaults=data,
        )
        return None


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
class AFHSellerMappingCSVUploadView(AmendingCsvUploadView):
    """Upsert on staff_id — ported from legacy."""

    model = AFHSellerMapping
    serializer_class = AFHSellerMappingSerializer
    result_filename = "afh_seller_mapping_upload_results"

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        AFHSellerMapping.objects.update_or_create(
            staff_id=data.get("staff_id"),
            defaults=data,
        )
        return None


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
