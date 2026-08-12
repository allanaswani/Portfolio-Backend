"""
Views for the legacy staff_management tables ported from hf_group_project-master.

- managed=True tables → full CRUD (list/create, retrieve/update/destroy) + CSV upload.
- managed=False tables → list/retrieve; ETL populates them, but the manual admin
  endpoints (create + CSV upload) write them too, exactly like the old backend.
  The router has no write opinion on unmanaged models, so those writes fall
  through to `default` — the same physical database in this deployment.
- Manual CSV uploads (merchant tills, weighted-sales daily accounts/dormancy,
  retail-allocated-portfolio) target the REAL warehouse tables with the old
  backend's per-dataset semantics — see the upload views at the bottom.
"""

import django_filters.rest_framework
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework import serializers as drf_serializers
from rest_framework.filters import SearchFilter
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
)
from apps.portfolio.models import RetailAllocatedPortfolio
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
    queryset = BranchEmployeeDmcData.objects.all().order_by("-id")


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
    # date_time_etl is an auto-filled ETL housekeeping column (default=now); the
    # old backend never required it in the CSV, so don't demand it here either.
    excluded_columns = ("id", "updated_at", "date_time_etl")

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
    queryset = BranchFinalEmployeeDmcData.objects.all().order_by("-id")


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
    queryset = Drawdown.objects.all().order_by("-id")


@extend_schema(tags=TAG)
class DrawdownDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DrawdownSerializer
    queryset = Drawdown.objects.all()


@extend_schema(tags=TAG)
class DrawdownCsvUploadView(BaseCsvUploadView):
    # Write to DrawdownDaily (table ``drawdown_daily``) — the SAME table the list,
    # search, single-create and update all use (drawdown-daily/). The upload was
    # wired to the separate ``drawdown`` table (DrawdownSerializer), so uploaded
    # rows never appeared in the drawdowns screen. The whole UI (columns, create
    # form) is built on DrawdownDaily fields, so the uploaded CSV matches this.
    serializer_class = DrawdownDailySerializer


@extend_schema(tags=TAG)
class DrawdownDailyListView(generics.ListCreateAPIView):
    # ListCreate (not List): the old drawdown-daily/ accepted POSTs from the
    # data-management screens. drawdown_daily is unmanaged, but DB_*/DW_* point
    # at the same physical database in this deployment, so the write lands in
    # the right table.
    # Newest-first: without ordering the list is oldest-first, so freshly-added
    # rows (highest id) land on the last page and look "missing" after a save.
    permission_classes = [IsAuthenticated]
    serializer_class = DrawdownDailySerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cust_id", "unit_code", "id_product", "customer_segment"]
    queryset = DrawdownDaily.objects.all().order_by("-id")


@extend_schema(tags=TAG)
class DrawdownDailyDetailView(generics.RetrieveUpdateDestroyAPIView):
    # Retrieve + update + delete, like the old backend's DrawdownDailyView
    # (GET/PUT/DELETE). Editing (e.g. correcting a sales code) sent PUT here and
    # got 405 while this was a read-only RetrieveAPIView.
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
    queryset = InsurancePolicy.objects.all().order_by("-id")


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
    queryset = TradeFinanceData.objects.all().order_by("-id")


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
    queryset = CustMonthlyFtp.objects.all().order_by("-id")


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
class MerchantBankTillManualListView(generics.ListCreateAPIView):
    # Old endpoint was list+create (MerchantBankTillListCreateView).
    permission_classes = [IsAuthenticated]
    serializer_class = MerchantBankTillManualDataSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["seller_code", "sellercode", "current_branch", "brn_zone", "staff_role"]
    queryset = MerchantBankTillManualData.objects.all().order_by("-id")


@extend_schema(tags=TAG)
class MerchantBankTillManualDetailView(generics.RetrieveUpdateDestroyAPIView):
    # Retrieve + update + delete, like the old backend's MerchantBankTillDetailView.
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
class ProductListView(generics.ListCreateAPIView):
    # Old endpoint was list+create (product mapping admin screen).
    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["code", "product_map", "focus", "sme_pb"]
    queryset = Product.objects.all().order_by("-id")


@extend_schema(tags=TAG)
class ProductDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer
    queryset = Product.objects.all()


@extend_schema(tags=TAG)
class ProductMappingCsvUploadView(APIView):
    """Upsert product_mapping rows from a CSV (keyed on ``code``). Ports the old
    backend's ProductCSVUploadView.

    Unlike the ETL warehouse datasets (which upload to managed *_upload mirrors),
    product_mapping is app-owned reference/config data — the FD product
    classification and the CEO fixed-deposit summaries read it live — so the
    upload writes straight to it. Each row runs in its own savepoint so one bad
    row doesn't abort the batch, and a results ZIP (successful/failed) is returned.
    """

    permission_classes = [IsAuthenticated]
    REQUIRED = ["code", "product_description", "product_map", "focus", "sme_pb"]

    def post(self, request, *args, **kwargs):
        import csv, io, zipfile
        from django.db import connection, transaction
        from django.http import HttpResponse

        f = request.FILES.get("file")
        if not f:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        if not f.name.lower().endswith(".csv"):
            return Response({"error": "File must be a CSV"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            decoded = f.read().decode("utf-8-sig", errors="replace").splitlines()
        except Exception as e:
            return Response({"error": f"Could not read file: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(decoded)
        fieldnames = reader.fieldnames or []
        missing = [c for c in self.REQUIRED if c not in fieldnames]
        if missing:
            return Response({"error": f"Missing columns in CSV: {missing}"}, status=status.HTTP_400_BAD_REQUEST)

        success_buf, fail_buf = io.StringIO(), io.StringIO()
        sw = csv.DictWriter(success_buf, fieldnames=fieldnames)
        fw = csv.DictWriter(fail_buf, fieldnames=list(fieldnames) + ["error"])
        sw.writeheader(); fw.writeheader()
        created = updated = 0

        for row in reader:
            code = (row.get("code") or "").strip()
            if not code:
                row["error"] = "Missing 'code'"; fw.writerow(row); continue
            vals = [row.get("product_description"), row.get("product_map"),
                    row.get("focus"), row.get("sme_pb")]
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(
                        "UPDATE product_mapping SET product_description=%s, product_map=%s, "
                        "focus=%s, sme_pb=%s WHERE code=%s",
                        vals + [code],
                    )
                    if cur.rowcount == 0:
                        cur.execute(
                            "INSERT INTO product_mapping (code, product_description, product_map, "
                            "focus, sme_pb, date_created) VALUES (%s,%s,%s,%s,%s, now())",
                            [code] + vals,
                        )
                        created += 1
                    else:
                        updated += 1
                sw.writerow(row)
            except Exception as e:
                row["error"] = str(e); fw.writerow(row)

        resp = HttpResponse(content_type="application/zip")
        resp["Content-Disposition"] = 'attachment; filename="product_mapping_upload_results.zip"'
        with zipfile.ZipFile(resp, "w") as zf:
            zf.writestr("successful_records.csv", success_buf.getvalue())
            zf.writestr("failed_records.csv", fail_buf.getvalue())
        resp["X-Records-Created"] = str(created)
        resp["X-Records-Updated"] = str(updated)
        return resp


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
class RmKPIBaseSummaryListCreateView(generics.ListCreateAPIView):
    """Old rm-kpi-base-summary/ — lists the rm_kpi_base_summary rows (and accepts
    POSTs from the admin screen), matching RmKPIBaseSummaryListCreateView in the
    old backend. The computed PortfolioRmDepositTrends aggregate the new backend
    served here had a different shape."""
    permission_classes = [IsAuthenticated]
    serializer_class = RmKPIBaseSummarySerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["sales_code", "kpi_code"]
    queryset = RmKPIBaseSummary.objects.all()


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
class RetailAllocatedPortfolioListView(generics.ListCreateAPIView):
    # Old endpoint was list+create (allocation admin screen posts new rows).
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    # Server-side search so the (large) allocation base can be paged instead of
    # pulled whole and filtered in the browser. `?search=` matches the text columns;
    # `?sales_code=` / `?main_segment=` are exact filters.
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["customer_name", "sales_code", "rm_name", "main_segment"]
    filterset_fields = ["sales_code", "main_segment"]

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
        return RetailAllocatedPortfolio.objects.all().order_by("cust_id")


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
# Manual CSV uploads of warehouse datasets → the REAL warehouse tables
# ──────────────────────────────────────────────────────────────────────────────
# The old backend wrote these tables directly, and the list endpoints read them —
# so uploads must land there or the uploaded data never shows. The models are
# unmanaged, but DB_* and DW_* point at the same physical database in this
# deployment, so ORM writes (which fall through the router to `default`) hit the
# same tables ETL maintains. Semantics are ported 1:1 from the old backend:
#   • weighted-sales daily accounts / dormancy — FULL REPLACE (delete all, insert CSV)
#   • merchant bank tills                      — per-row UPDATE keyed on `id`
#   • retail allocated portfolio               — UPSERT on cust_id
# Each returns the legacy results-ZIP via AmendingCsvUploadView.
# ══════════════════════════════════════════════════════════════════════════════

@extend_schema(tags=TAG)
class DailySalesAccountsWithCtoUploadCsvView(AmendingCsvUploadView):
    """Old DailySalesAccountsWithCtoCSVUploadView: delete ALL rows, insert the CSV."""

    model = DailySalesAccountsWithCto
    serializer_class = DailySalesAccountsWithCtoSerializer
    result_filename = "weighted_sales_daily_accounts_upload_results"
    excluded_columns = ("id", "etl_date_updated")

    def before_rows(self, rows):
        DailySalesAccountsWithCto.objects.all().delete()


@extend_schema(tags=TAG)
class DailyDormancyConvertedAccountUploadCsvView(AmendingCsvUploadView):
    """Old DailyDormancyConvertedAccountCSVUploadView: delete ALL rows, insert the CSV."""

    model = DailyDormancyConvertedAccount
    serializer_class = DailyDormancyConvertedAccountSerializer
    result_filename = "weighted_sales_dormancy_converted_upload_results"
    excluded_columns = ("id", "etl_date_updated")

    def before_rows(self, rows):
        DailyDormancyConvertedAccount.objects.all().delete()


@extend_schema(tags=TAG)
class MerchantBankTillManualUploadCsvView(AmendingCsvUploadView):
    """Old MerchantBankTillService.bulk_create_from_csv: per-row UPDATE keyed on
    ``id`` — a row whose id doesn't exist in the table fails with
    "Record not found." (the old uploader never created new rows)."""

    model = MerchantBankTillManualData
    serializer_class = MerchantBankTillManualDataSerializer
    result_filename = "merchant_bank_till_manual_upload_results"

    def required_columns(self):
        # The old uploader had no column gate — it updates whatever fields the
        # CSV carries for each `id`.
        return []

    def build_serializer(self, row):
        row_id = (row.get("id") or "").strip()
        instance = MerchantBankTillManualData.objects.filter(pk=row_id).first() if row_id else None
        if instance is None:
            raise ValueError("Record not found.")
        return self.serializer_class(instance=instance, data=row, partial=True)


class _RetailAllocatedPortfolioRowSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = RetailAllocatedPortfolio
        exclude = ("id",)


@extend_schema(tags=TAG)
class RetailAllocatedPortfolioUploadCsvView(AmendingCsvUploadView):
    """Old RetailAllocatedPortfolioCSVUploadView: upsert on cust_id straight into
    retail_allocated_portfolio."""

    model = RetailAllocatedPortfolio
    serializer_class = _RetailAllocatedPortfolioRowSerializer
    result_filename = "retail_allocated_portfolio_upload_results"
    excluded_columns = ("id", "updated_at")

    def save_valid(self, row, serializer):
        RetailAllocatedPortfolio.objects.update_or_create(
            cust_id=serializer.validated_data.get("cust_id"),
            defaults=serializer.validated_data,
        )
        return None
