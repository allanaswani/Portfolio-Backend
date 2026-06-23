"""
Views for the legacy staff_management tables ported from hf_group_project-master.

- managed=True tables → full CRUD (list/create, retrieve/update/destroy) + CSV upload.
- managed=False tables → read-only (list/retrieve) because they live in the
  datawarehouse and the DB router blocks writes to them. ETL populates them.
- Manual CSV uploads of those warehouse datasets (merchant tills, weighted-sales
  daily accounts/dormancy, retail-allocated-portfolio) write to MANAGED *_upload
  mirror tables instead (same columns, default DB) — see the mirror views at the
  bottom of this module. The warehouse read endpoints (ETL data) are untouched.
"""

import django_filters.rest_framework
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from core.csv_upload import AmendingCsvUploadView

from . import rm_kpi_base_summary_service
from .views import BaseCsvUploadView
from .models import (
    BranchEmployeeDmcData, BranchFinalEmployeeDmcData, Drawdown, DrawdownDaily,
    InsurancePolicy, TradeFinanceData, CustMonthlyFtp, DailySalesAccountsWithCto,
    DailyDormancyConvertedAccount, MerchantBankTillManualData, IapplyLoanApproval,
    Product, StaffEmployeeData, LeaveRecord, EmployeeRoleHistory, RmKPIBaseSummary,
    MissingEmployeeActual, TelesalesStaff, TelesalesDormantTillsAllocation,
    DailySalesAccountsWithCtoUpload, DailyDormancyConvertedAccountUpload,
    MerchantBankTillManualUpload,
)
from apps.portfolio.models import RetailAllocatedPortfolioUpload
from .serializers import (
    BranchEmployeeDmcDataSerializer, BranchFinalEmployeeDmcDataSerializer,
    DrawdownSerializer, DrawdownDailySerializer, InsurancePolicySerializer,
    TradeFinanceDataSerializer, CustMonthlyFtpSerializer,
    DailySalesAccountsWithCtoSerializer, DailyDormancyConvertedAccountSerializer,
    MerchantBankTillManualDataSerializer, IapplyLoanApprovalSerializer,
    ProductSerializer, StaffEmployeeDataSerializer, LeaveRecordSerializer,
    EmployeeRoleHistorySerializer, RmKPIBaseSummarySerializer,
    MissingEmployeeActualSerializer, TelesalesStaffSerializer,
    TelesalesDormantTillsAllocationSerializer,
    DailySalesAccountsWithCtoUploadSerializer, DailyDormancyConvertedAccountUploadSerializer,
    MerchantBankTillManualUploadSerializer, RetailAllocatedPortfolioUploadSerializer,
)

TAG = ["Staff Management — Legacy Data"]
DjangoFilterBackend = django_filters.rest_framework.DjangoFilterBackend


# ── Branch DMC target data (managed) ──────────────────────────────────────────

@extend_schema(tags=TAG)
class BranchEmployeeDmcListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchEmployeeDmcDataSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "brn_code", "staff_branch", "staff_zone", "team_leader", "active"]
    queryset = BranchEmployeeDmcData.objects.all()


@extend_schema(tags=TAG)
class BranchEmployeeDmcDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchEmployeeDmcDataSerializer
    queryset = BranchEmployeeDmcData.objects.all()


@extend_schema(tags=TAG)
class BranchEmployeeDmcCsvUploadView(AmendingCsvUploadView):
    """Upsert on (staff_pf_number, sales_code, staff_role) — ported from legacy."""

    model = BranchEmployeeDmcData
    serializer_class = BranchEmployeeDmcDataSerializer
    result_filename = "branch_employee_dmc_data_upload_results"
    excluded_columns = ("id", "updated_at")

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        BranchEmployeeDmcData.objects.update_or_create(
            staff_pf_number=data.get("staff_pf_number"),
            sales_code=data.get("sales_code"),
            staff_role=data.get("staff_role"),
            defaults=data,
        )
        return None


@extend_schema(tags=TAG)
class BranchFinalEmployeeDmcListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchFinalEmployeeDmcDataSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "brn_code", "staff_branch", "staff_zone", "team_leader", "active"]
    queryset = BranchFinalEmployeeDmcData.objects.all()


@extend_schema(tags=TAG)
class BranchFinalEmployeeDmcDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchFinalEmployeeDmcDataSerializer
    queryset = BranchFinalEmployeeDmcData.objects.all()


@extend_schema(tags=TAG)
class BranchFinalEmployeeDmcCsvUploadView(AmendingCsvUploadView):
    """Upsert on staff_branch — ported from legacy."""

    model = BranchFinalEmployeeDmcData
    serializer_class = BranchFinalEmployeeDmcDataSerializer
    result_filename = "branch_final_employee_dmc_data_upload_results"
    excluded_columns = ("id", "updated_at", "date_update_etl")

    def save_valid(self, row, serializer):
        data = serializer.validated_data
        BranchFinalEmployeeDmcData.objects.update_or_create(
            staff_branch=data.get("staff_branch"),
            defaults=data,
        )
        return None


# ── Drawdown (managed) + DrawdownDaily (warehouse, read-only) ──────────────────

@extend_schema(tags=TAG)
class DrawdownListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DrawdownSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_id", "branch", "segment", "year_month", "unit_code"]
    queryset = Drawdown.objects.all()


@extend_schema(tags=TAG)
class DrawdownDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DrawdownSerializer
    queryset = Drawdown.objects.all()


@extend_schema(tags=TAG)
class DrawdownCsvUploadView(BaseCsvUploadView):
    serializer_class = DrawdownSerializer


@extend_schema(tags=TAG)
class DrawdownDailyListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DrawdownDailySerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_id", "unit_code", "id_product", "customer_segment"]
    queryset = DrawdownDaily.objects.all()


@extend_schema(tags=TAG)
class DrawdownDailyDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DrawdownDailySerializer
    queryset = DrawdownDaily.objects.all()


# ── Insurance policies (managed) ──────────────────────────────────────────────

@extend_schema(tags=TAG)
class InsurancePolicyListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InsurancePolicySerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["branch", "code", "rm", "month", "year", "product", "underwriter"]
    queryset = InsurancePolicy.objects.all()


@extend_schema(tags=TAG)
class InsurancePolicyDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InsurancePolicySerializer
    queryset = InsurancePolicy.objects.all()


@extend_schema(tags=TAG)
class InsurancePolicyCsvUploadView(AmendingCsvUploadView):
    """
    Replace-by-year load: delete existing rows for the upload's year, then insert.
    Parses dd/mm/YYYY dates and coerces money columns (blank → 0). Ported from legacy.

    Faithfulness note: the legacy view consumed the first data row via ``next(reader)``
    just to read its year, silently dropping it. ``before_rows`` reads the year from
    the full list, so every row is now imported.
    """

    model = InsurancePolicy
    serializer_class = InsurancePolicySerializer
    result_filename = "insurance_policy_upload_results"
    excluded_columns = ("id", "updated_at")
    _MONEY = ("sum_insured", "premiums", "paid", "balance", "commission")

    def before_rows(self, rows):
        if rows and rows[0].get("year"):
            InsurancePolicy.objects.filter(year=rows[0]["year"]).delete()

    def amend_row(self, row):
        row["starting_date"] = self.parse_date(row.get("starting_date"), "%d/%m/%Y", "%Y-%m-%d")
        row["ending_date"] = self.parse_date(row.get("ending_date"), "%d/%m/%Y", "%Y-%m-%d")
        for field in self._MONEY:
            row[field] = self.to_float(row.get(field))


# ── Trade finance (managed) ───────────────────────────────────────────────────

@extend_schema(tags=TAG)
class TradeFinanceListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TradeFinanceDataSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["originating_branch", "rm_code", "product_type", "segment", "month", "year", "currency"]
    queryset = TradeFinanceData.objects.all()


@extend_schema(tags=TAG)
class TradeFinanceDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TradeFinanceDataSerializer
    queryset = TradeFinanceData.objects.all()


@extend_schema(tags=TAG)
class TradeFinanceCsvUploadView(AmendingCsvUploadView):
    """
    Replace-by-year load: delete rows for the upload's year, then insert. Coerces
    money/rate columns (blank → 0, fx_rate blank → 1). Ported from legacy.
    (Same first-row fix as InsurancePolicyCsvUploadView.)
    """

    model = TradeFinanceData
    serializer_class = TradeFinanceDataSerializer
    result_filename = "trade_finance_data_upload_results"
    excluded_columns = ("id", "updated_at")
    _MONEY = ("amount_fcy", "commission_lcy", "cash_cover_amount", "cash_cover_percentage")

    def before_rows(self, rows):
        if rows and rows[0].get("year"):
            TradeFinanceData.objects.filter(year=rows[0]["year"]).delete()

    def amend_row(self, row):
        for field in self._MONEY:
            row[field] = self.to_float(row.get(field))
        row["fx_rate"] = self.to_float(row.get("fx_rate"), default=1.0)


# ── Customer monthly FTP (managed) ────────────────────────────────────────────

@extend_schema(tags=TAG)
class CustMonthlyFtpListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustMonthlyFtpSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_cif", "current_year"]
    queryset = CustMonthlyFtp.objects.all()


@extend_schema(tags=TAG)
class CustMonthlyFtpDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustMonthlyFtpSerializer
    queryset = CustMonthlyFtp.objects.all()


@extend_schema(tags=TAG)
class CustMonthlyFtpCsvUploadView(BaseCsvUploadView):
    serializer_class = CustMonthlyFtpSerializer


# ── Weighted-sales warehouse reads (read-only) ────────────────────────────────

@extend_schema(tags=TAG)
class DailySalesAccountsWithCtoListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DailySalesAccountsWithCtoSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_cif", "brn_code", "sale_code", "customer_segment", "account_status"]
    queryset = DailySalesAccountsWithCto.objects.all()


@extend_schema(tags=TAG)
class DailyDormancyConvertedAccountListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DailyDormancyConvertedAccountSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_cif", "brn_code", "customer_segment", "current_status"]
    queryset = DailyDormancyConvertedAccount.objects.all()


@extend_schema(tags=TAG)
class MerchantBankTillManualListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MerchantBankTillManualDataSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["seller_code", "sellercode", "current_branch", "brn_zone", "staff_role"]
    queryset = MerchantBankTillManualData.objects.all()


@extend_schema(tags=TAG)
class MerchantBankTillManualDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MerchantBankTillManualDataSerializer
    queryset = MerchantBankTillManualData.objects.all()


@extend_schema(tags=TAG)
class IapplyLoanApprovalListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = IapplyLoanApprovalSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["branch", "product_category", "customer_id", "segment", "month", "open_closed"]
    queryset = IapplyLoanApproval.objects.all()


@extend_schema(tags=TAG)
class ProductListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["code", "product_map", "focus", "sme_pb"]
    queryset = Product.objects.all()


@extend_schema(tags=TAG)
class ProductDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer
    queryset = Product.objects.all()


# ── Staff master / leave / role history (managed) ─────────────────────────────

@extend_schema(tags=TAG)
class StaffEmployeeListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StaffEmployeeDataSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "department", "staff_unit", "staff_org_unit", "employee_category", "is_active"]
    queryset = StaffEmployeeData.objects.all()


@extend_schema(tags=TAG)
class StaffEmployeeDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StaffEmployeeDataSerializer
    queryset = StaffEmployeeData.objects.all()


@extend_schema(tags=TAG)
class StaffEmployeeCsvUploadView(BaseCsvUploadView):
    serializer_class = StaffEmployeeDataSerializer


@extend_schema(tags=TAG)
class LeaveRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LeaveRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "leave_type"]
    queryset = LeaveRecord.objects.all()


@extend_schema(tags=TAG)
class LeaveRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LeaveRecordSerializer
    queryset = LeaveRecord.objects.all()


@extend_schema(tags=TAG)
class LeaveRecordCsvUploadView(BaseCsvUploadView):
    serializer_class = LeaveRecordSerializer


@extend_schema(tags=TAG)
class EmployeeRoleHistoryListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmployeeRoleHistorySerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "role_code", "role_status"]
    queryset = EmployeeRoleHistory.objects.all()


@extend_schema(tags=TAG)
class EmployeeRoleHistoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmployeeRoleHistorySerializer
    queryset = EmployeeRoleHistory.objects.all()


@extend_schema(tags=TAG)
class EmployeeRoleHistoryCsvUploadView(BaseCsvUploadView):
    serializer_class = EmployeeRoleHistorySerializer


# ── RM KPI base summary (managed) ─────────────────────────────────────────────

@extend_schema(tags=TAG)
class RmKPIBaseSummaryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RmKPIBaseSummarySerializer
    queryset = RmKPIBaseSummary.objects.all()


@extend_schema(tags=TAG)
class RmKPIBaseSummaryCsvUploadView(AmendingCsvUploadView):
    """
    Upsert RM KPIs from a long-form CSV (one row per KPI), keyed on
    (sales_code, eom_date, kpi_code). Ported from the legacy upsert uploader.
    """

    model = RmKPIBaseSummary
    serializer_class = RmKPIBaseSummarySerializer
    result_filename = "rm_kpi_base_summary_upload_results"

    def save_valid(self, row, serializer):
        rm_kpi_base_summary_service.upsert_rm_kpi_base_summary(serializer.validated_data)
        return None


@extend_schema(tags=TAG)
class RmKPIBaseSummaryRefreshView(APIView):
    """
    Recompute ``rm_kpi_base_summary`` from ``customer_allocation_base`` — the legacy
    pivot that derives six RM KPIs per rm_code and upserts them as long-form rows.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        result = rm_kpi_base_summary_service.bulk_insert_from_kpi_query()
        return Response({
            "status": "completed",
            "message": "RM KPI base summary recomputed from customer_allocation_base.",
            "inserted": result["inserted"],
            "error_count": len(result["errors"]),
            "errors": result["errors"][:50],
            "rows": RmKPIBaseSummary.objects.count(),
            "triggered_at": timezone.now().isoformat(),
        })


# ── Missing actuals (managed) ─────────────────────────────────────────────────

@extend_schema(tags=TAG)
class MissingEmployeeActualListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MissingEmployeeActualSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "role_code", "kpi_code", "eom_date"]
    queryset = MissingEmployeeActual.objects.all()


# ── Employee summary (StaffEmployeeData aggregate) ────────────────────────────

@extend_schema(tags=TAG)
class EmployeeSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        qs = StaffEmployeeData.objects.all()
        total = qs.count()
        active = qs.filter(is_active=True).count()
        by_dept = list(
            qs.values("department").annotate(count=Count("id")).order_by("-count")
        )
        by_category = list(
            qs.values("employee_category").annotate(count=Count("id")).order_by("-count")
        )
        return Response({
            "total": total,
            "active": active,
            "inactive": total - active,
            "by_department": by_dept,
            "by_category": by_category,
        })


# ── Telesales (managed) ───────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class TelesalesStaffListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TelesalesStaffSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "branch", "role", "team_leader"]
    queryset = TelesalesStaff.objects.all()


@extend_schema(tags=TAG)
class TelesalesStaffDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TelesalesStaffSerializer
    queryset = TelesalesStaff.objects.all()


@extend_schema(tags=TAG)
class TelesalesStaffCsvUploadView(BaseCsvUploadView):
    serializer_class = TelesalesStaffSerializer


@extend_schema(tags=TAG)
class TelesalesDormantTillsListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TelesalesDormantTillsAllocationSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sellercode", "code", "branch", "allocated_seller_person"]
    queryset = TelesalesDormantTillsAllocation.objects.all()


@extend_schema(tags=TAG)
class TelesalesDormantTillsDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TelesalesDormantTillsAllocationSerializer
    queryset = TelesalesDormantTillsAllocation.objects.all()


@extend_schema(tags=TAG)
class TelesalesDormantTillsCsvUploadView(BaseCsvUploadView):
    serializer_class = TelesalesDormantTillsAllocationSerializer


# ── Retail allocated portfolio (portfolio app, warehouse, read-only) ──────────

@extend_schema(tags=TAG)
class RetailAllocatedPortfolioListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_serializer_class(self):
        from apps.portfolio.models import RetailAllocatedPortfolio
        from rest_framework import serializers as drf

        class _Serializer(drf.ModelSerializer):
            class Meta:
                model = RetailAllocatedPortfolio
                fields = "__all__"

        return _Serializer

    def get_queryset(self):
        from apps.portfolio.models import RetailAllocatedPortfolio
        return RetailAllocatedPortfolio.objects.all()


@extend_schema(tags=TAG)
class RetailAllocatedPortfolioDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        from apps.portfolio.models import RetailAllocatedPortfolio
        from rest_framework import serializers as drf

        class _Serializer(drf.ModelSerializer):
            class Meta:
                model = RetailAllocatedPortfolio
                fields = "__all__"

        return _Serializer

    def get_queryset(self):
        from apps.portfolio.models import RetailAllocatedPortfolio
        return RetailAllocatedPortfolio.objects.all()


# ══════════════════════════════════════════════════════════════════════════════
# Managed mirror tables for manual CSV uploads of warehouse datasets
# ──────────────────────────────────────────────────────────────────────────────
# The warehouse models (managed=False) are read-only via the router. These views
# write/read the managed *_upload mirror tables so manual uploads persist. List +
# CSV upload; the CSV upload returns the legacy results-ZIP via AmendingCsvUploadView.
# ══════════════════════════════════════════════════════════════════════════════

@extend_schema(tags=TAG)
class DailySalesAccountsWithCtoUploadListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DailySalesAccountsWithCtoUploadSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_cif", "brn_code", "sale_code", "customer_segment", "account_status"]
    queryset = DailySalesAccountsWithCtoUpload.objects.all()


@extend_schema(tags=TAG)
class DailySalesAccountsWithCtoUploadCsvView(AmendingCsvUploadView):
    model = DailySalesAccountsWithCtoUpload
    serializer_class = DailySalesAccountsWithCtoUploadSerializer
    result_filename = "weighted_sales_daily_accounts_upload_results"


@extend_schema(tags=TAG)
class DailyDormancyConvertedAccountUploadListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DailyDormancyConvertedAccountUploadSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_cif", "brn_code", "customer_segment", "current_status"]
    queryset = DailyDormancyConvertedAccountUpload.objects.all()


@extend_schema(tags=TAG)
class DailyDormancyConvertedAccountUploadCsvView(AmendingCsvUploadView):
    model = DailyDormancyConvertedAccountUpload
    serializer_class = DailyDormancyConvertedAccountUploadSerializer
    result_filename = "weighted_sales_dormancy_converted_upload_results"


@extend_schema(tags=TAG)
class MerchantBankTillManualUploadListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MerchantBankTillManualUploadSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["seller_code", "sellercode", "current_branch", "brn_zone", "staff_role"]
    queryset = MerchantBankTillManualUpload.objects.all()


@extend_schema(tags=TAG)
class MerchantBankTillManualUploadCsvView(AmendingCsvUploadView):
    model = MerchantBankTillManualUpload
    serializer_class = MerchantBankTillManualUploadSerializer
    result_filename = "merchant_bank_till_manual_upload_results"


@extend_schema(tags=TAG)
class RetailAllocatedPortfolioUploadListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RetailAllocatedPortfolioUploadSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_id", "sales_code", "branch", "main_segment"]
    queryset = RetailAllocatedPortfolioUpload.objects.all()


@extend_schema(tags=TAG)
class RetailAllocatedPortfolioUploadCsvView(AmendingCsvUploadView):
    """Upsert on cust_id (ported from the legacy retail-allocated-portfolio uploader)."""

    model = RetailAllocatedPortfolioUpload
    serializer_class = RetailAllocatedPortfolioUploadSerializer
    result_filename = "retail_allocated_portfolio_upload_results"
    excluded_columns = ("id", "updated_at", "uploaded_at")

    def save_valid(self, row, serializer):
        RetailAllocatedPortfolioUpload.objects.update_or_create(
            cust_id=serializer.validated_data.get("cust_id"),
            defaults=serializer.validated_data,
        )
        return None
