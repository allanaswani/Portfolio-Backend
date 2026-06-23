"""Tests for the newly ported staff_management scorecard-config endpoints."""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    ScorecardKPI, ScorecardRole, InsurancePolicy, TradeFinanceData,
    LeaveRecord, EmployeeRoleHistory, Drawdown, TelesalesStaff,
    BranchEmployeeDmcData, BranchFinalEmployeeDmcData,
)


class ScorecardConfigEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sm_user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_role_create_update_delete(self):
        # create
        r = self.client.post("/staff_management/roles/", {"name": "RM", "weight": 1}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        role_id = r.data["id"]
        # update
        r = self.client.patch(f"/staff_management/roles/{role_id}/", {"description": "Relationship Mgr"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(ScorecardRole.objects.get(pk=role_id).description, "Relationship Mgr")
        # delete
        r = self.client.delete(f"/staff_management/roles/{role_id}/")
        self.assertIn(r.status_code, (200, 204))
        self.assertFalse(ScorecardRole.objects.filter(pk=role_id).exists())

    def test_role_csv_upload(self):
        csv_content = b"name,description,is_active\nBBM,Branch Manager,true\nCSO,Customer Service,true\n"
        upload = SimpleUploadedFile("roles.csv", csv_content, content_type="text/csv")
        r = self.client.post("/staff_management/roles/upload-csv/", {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["created"], 2)
        self.assertTrue(ScorecardRole.objects.filter(name="BBM").exists())
        self.assertTrue(ScorecardRole.objects.filter(name="CSO").exists())

    def test_kpi_csv_upload_reports_bad_rows(self):
        # second row missing required 'name' → reported, first row imported
        csv_content = b"name,category,weight\nDeposits Growth,deposits,2\n,loans,1\n"
        upload = SimpleUploadedFile("kpis.csv", csv_content, content_type="text/csv")
        r = self.client.post("/staff_management/kpis/upload-csv/", {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["created"], 1)
        self.assertEqual(r.data["error_count"], 1)
        self.assertTrue(ScorecardKPI.objects.filter(name="Deposits Growth").exists())

    def test_csv_upload_requires_file(self):
        r = self.client.post("/staff_management/roles/upload-csv/", {}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_requires_authentication(self):
        anon = APIClient()
        r = anon.get("/staff_management/roles/")
        self.assertIn(r.status_code, (401, 403))


class LegacyStaffManagementEndpointTests(TestCase):
    """Ported legacy staff_management resources (managed tables)."""

    def setUp(self):
        self.user = User.objects.create_user("legacy_user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_insurance_policy_crud(self):
        payload = {
            "policy_no": "POL-001", "insured": "Acme Ltd", "branch": "Nairobi",
            "code": "RM01", "month": "6", "year": "2026",
            "premiums": "1000.00", "paid": "500.00",
        }
        r = self.client.post("/staff_management/insurance-policy/", payload, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.data["id"]
        r = self.client.get("/staff_management/insurance-policy/")
        self.assertEqual(r.status_code, 200)
        r = self.client.patch(f"/staff_management/insurance-policy/{pk}/", {"branch": "Mombasa"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(InsurancePolicy.objects.get(pk=pk).branch, "Mombasa")
        r = self.client.delete(f"/staff_management/insurance-policy/{pk}/")
        self.assertIn(r.status_code, (200, 204))

    def test_trade_finance_csv_upload(self):
        # The ported uploader enforces the full-column gate and returns a results ZIP
        # (legacy contract), not the BaseCsvUploadView JSON.
        csv_content = (
            b"originating_branch,rm_name,rm_code,guarantee_ref,product_type,customer_id,segment,"
            b"our_customer,beneficiary,currency,amount_fcy,issue_date,expiry_date,commission_lcy,"
            b"month,fx_rate,year,security_type,cash_cover_amount,cash_cover_percentage,other_security\n"
            b"Nairobi,Jane Doe,RM9,GR-1,LC,123,Corporate,Cust A,Ben A,USD,1000.00,2026-01-01,"
            b"2026-06-01,10.000000,Jan,130.000000,2026,cash,0,0,none\n"
        )
        upload = SimpleUploadedFile("tf.csv", csv_content, content_type="text/csv")
        r = self.client.post("/staff_management/trade-finance/upload-csv/", {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("application/zip", r["Content-Type"])
        self.assertTrue(TradeFinanceData.objects.filter(guarantee_ref="GR-1").exists())

    def test_leave_record_constraint_and_create(self):
        # valid: end after start
        r = self.client.post("/staff_management/leave-records/", {
            "sales_code": "RM01", "leave_type": "sick_leave",
            "start_date": "2026-06-01", "end_date": "2026-06-05",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(LeaveRecord.objects.filter(sales_code="RM01").exists())

    def test_role_history_create(self):
        r = self.client.post("/staff_management/role-history/", {
            "sales_code": "RM01", "role_code": "commercial_rm",
            "start_date": "2026-01-01", "role_status": "permanent",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(EmployeeRoleHistory.objects.filter(sales_code="RM01").exists())

    def test_drawdowns_csv_upload(self):
        csv_content = b"cust_id,customer_name,branch,segment\n123,Cust A,Nairobi,Corporate\n"
        upload = SimpleUploadedFile("dd.csv", csv_content, content_type="text/csv")
        r = self.client.post("/staff_management/drawdowns/upload-csv/", {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Drawdown.objects.count(), 1)

    def test_sales_people_csv_upload(self):
        csv_content = b"sales_code,sales_person,branch,role,team_leader\nT01,John,Nairobi,Telesales,Lead A\n"
        upload = SimpleUploadedFile("ts.csv", csv_content, content_type="text/csv")
        r = self.client.post("/staff_management/sales-people/upload-csv/", {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(TelesalesStaff.objects.filter(sales_code="T01").exists())

    def test_rm_kpi_base_summary_refresh(self):
        # Now runs the real pivot from customer_allocation_base (empty here → 0 inserted).
        r = self.client.post("/staff_management/rm-kpi-base-summary/refresh/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "completed")
        self.assertEqual(r.data["inserted"], 0)
        self.assertEqual(r.data["error_count"], 0)

    def test_employee_summary(self):
        r = self.client.get("/staff_management/employee-summary/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("total", r.data)

    def test_legacy_endpoints_require_auth(self):
        anon = APIClient()
        for url in [
            "/staff_management/insurance-policy/",
            "/staff_management/trade-finance/",
            "/staff_management/leave-records/",
            "/staff_management/role-history/",
        ]:
            self.assertIn(anon.get(url).status_code, (401, 403))


# ── Amending CSV uploaders (per-column transforms + upsert, legacy contract) ────

def _model_csv(model, rows, excluded=("id", "updated_at", "date_update_etl"), extra_cols=()):
    """
    Build a CSV whose header covers every required column of ``model``, filling
    unspecified cells with a type-valid default (numbers→0, dates→a real date) so the
    serializer accepts them — mirroring a real upload that has values in every column.
    """
    import csv
    import io
    from django.db import models as dm

    fields = [f for f in model._meta.concrete_fields if f.name not in set(excluded)]
    cols = [f.name for f in fields] + [c for c in extra_cols if c not in {f.name for f in fields}]

    def default_for(f):
        if isinstance(f, dm.EmailField):
            return "a@b.com"
        if isinstance(f, (dm.IntegerField, dm.BigIntegerField, dm.DecimalField, dm.FloatField)):
            return "0"
        if isinstance(f, dm.DateTimeField):
            return "2024-01-01T00:00:00"
        if isinstance(f, dm.DateField):
            return "2024-01-01"
        return "x"  # non-blank placeholder so required CharFields validate

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    by_name = {f.name: f for f in fields}
    for r in rows:
        writer.writerow({c: r[c] if c in r else default_for(by_name.get(c)) if c in by_name else "" for c in cols})
    return SimpleUploadedFile("upload.csv", buf.getvalue().encode("utf-8"), content_type="text/csv")


class AmendingCsvUploaderTests(TestCase):
    """The staff uploaders that amend columns / upsert (ported from the old backend)."""

    def setUp(self):
        self.user = User.objects.create_user(username="dmc", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_branch_employee_dmc_upserts_on_composite_key(self):
        row = {"staff_pf_number": "1001", "sales_code": "SC1", "staff_role": "RM", "staff_name": "Ann"}
        url = "/staff_management/branch_employee_dmc_data/upload-csv/"
        r1 = self.client.post(url, {"file": _model_csv(BranchEmployeeDmcData, [row])}, format="multipart")
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertIn("application/zip", r1["Content-Type"])
        self.assertEqual(BranchEmployeeDmcData.objects.count(), 1)

        # Same composite key, new name → update (not a 2nd row).
        row["staff_name"] = "Ann B"
        r2 = self.client.post(url, {"file": _model_csv(BranchEmployeeDmcData, [row])}, format="multipart")
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(BranchEmployeeDmcData.objects.count(), 1)
        self.assertEqual(BranchEmployeeDmcData.objects.get().staff_name, "Ann B")

    def test_branch_final_dmc_upserts_on_staff_branch(self):
        url = "/staff_management/branch_final_employee_dmc_data/upload-csv/"
        for name in ("First", "Second"):
            r = self.client.post(
                url,
                {"file": _model_csv(BranchFinalEmployeeDmcData, [{"staff_branch": "Nairobi", "staff_name": name}])},
                format="multipart",
            )
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(BranchFinalEmployeeDmcData.objects.count(), 1)
        self.assertEqual(BranchFinalEmployeeDmcData.objects.get().staff_name, "Second")

    def test_insurance_parses_dates_cleans_money_and_replaces_year(self):
        url = "/staff_management/insurance-policy/upload-csv/"
        InsurancePolicy.objects.create(insured="OLD", year="2024")
        row = {
            "insured": "Acme", "starting_date": "05/03/2024", "ending_date": "04/03/2025",
            "sum_insured": "1,000,000", "premiums": "", "paid": "2,500",
            "balance": "", "commission": "100", "year": "2024", "month": "March",
        }
        r = self.client.post(url, {"file": _model_csv(InsurancePolicy, [row], excluded=("id", "updated_at"))}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        # Replace-by-year wiped the pre-existing 2024 row; only the uploaded one remains.
        self.assertEqual(InsurancePolicy.objects.filter(year="2024").count(), 1)
        obj = InsurancePolicy.objects.get(year="2024")
        self.assertEqual(obj.insured, "Acme")
        self.assertEqual(str(obj.starting_date), "2024-03-05")   # dd/mm/YYYY parsed
        self.assertEqual(obj.sum_insured, 1000000)               # commas stripped
        self.assertEqual(obj.premiums, 0)                        # blank → 0
        self.assertEqual(obj.paid, 2500)

    def test_trade_finance_casts_money_and_fx_default(self):
        url = "/staff_management/trade-finance/upload-csv/"
        row = {
            "originating_branch": "HQ", "customer_id": "123", "currency": "USD",
            "amount_fcy": "10,000", "commission_lcy": "", "fx_rate": "",
            "cash_cover_amount": "", "cash_cover_percentage": "0", "year": "2024", "month": "Jan",
        }
        r = self.client.post(url, {"file": _model_csv(TradeFinanceData, [row], excluded=("id", "updated_at"))}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        obj = TradeFinanceData.objects.get(year="2024")
        self.assertEqual(obj.amount_fcy, 10000)      # commas stripped
        self.assertEqual(obj.commission_lcy, 0)      # blank → 0
        self.assertEqual(obj.fx_rate, 1)             # blank fx_rate → 1

    def test_missing_columns_rejected(self):
        url = "/staff_management/branch_final_employee_dmc_data/upload-csv/"
        bad = SimpleUploadedFile("x.csv", b"staff_name\nAnn\n", content_type="text/csv")
        r = self.client.post(url, {"file": bad}, format="multipart")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("missing", str(r.data).lower())


# ── RM KPI base summary: CSV upsert + pivot refresh from customer_allocation_base ─

def _make_cab(**over):
    """Create a CustomerAllocationBase row, filling required fields with defaults."""
    from django.db import models as dm
    from apps.portfolio_management_enrichment.models import CustomerAllocationBase
    kwargs = {}
    for f in CustomerAllocationBase._meta.concrete_fields:
        if f.name == "id" or f.has_default() or f.null:
            continue
        if isinstance(f, (dm.IntegerField, dm.DecimalField, dm.FloatField)):
            kwargs[f.name] = 0
        else:
            kwargs[f.name] = "x"
    kwargs.update(over)
    return CustomerAllocationBase.objects.create(**kwargs)


class RmKpiBaseSummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="rmkpi", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_csv_upsert_keyed_on_sales_code_eom_kpi(self):
        from .models import RmKPIBaseSummary
        url = "/staff_management/rm-kpi-base-summary/upload-csv/"
        row = {"sales_code": "RM1", "eom_date": "2024-01-01", "kpi_code": "nfi_growth", "kpi_value": "100"}
        r = self.client.post(url, {"file": _model_csv(RmKPIBaseSummary, [row])}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("application/zip", r["Content-Type"])
        self.assertEqual(RmKPIBaseSummary.objects.get(sales_code="RM1", kpi_code="nfi_growth").kpi_value, 100)

        row["kpi_value"] = "250"
        r = self.client.post(url, {"file": _model_csv(RmKPIBaseSummary, [row])}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(RmKPIBaseSummary.objects.filter(sales_code="RM1", kpi_code="nfi_growth").count(), 1)
        self.assertEqual(RmKPIBaseSummary.objects.get(sales_code="RM1", kpi_code="nfi_growth").kpi_value, 250)

    def test_refresh_pivots_six_kpis_from_allocation_base(self):
        from datetime import date
        from .models import RmKPIBaseSummary
        # Two customers for RM7: income_contribution = Σnet_after_expense + Σftp − Σloan_loss.
        _make_cab(rm_code="RM7", cust_id="C1", net_after_expense=100, ftp=10, loan_loss=5, nfi=20, deposit=1000, aum_cust_id=5000)
        _make_cab(rm_code="RM7", cust_id="C2", net_after_expense=200, ftp=30, loan_loss=15, nfi=40, deposit=2000, aum_cust_id=7000)

        r = self.client.post("/staff_management/rm-kpi-base-summary/refresh/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["inserted"], 6)         # six KPIs for the one rm_code
        self.assertEqual(r.data["error_count"], 0)

        eom = date(date.today().year, 1, 1)
        def val(code):
            return RmKPIBaseSummary.objects.get(sales_code="RM7", eom_date=eom, kpi_code=code).kpi_value
        self.assertEqual(val("income_contribution"), 320)   # (100+200)+(10+30)-(5+15)
        self.assertEqual(val("nfi_growth"), 60)             # 20+40
        self.assertEqual(val("loan_loss"), -20)             # -(5+15)
        self.assertEqual(val("active_customers"), 2)        # count(cust_id)
        self.assertEqual(val("deposit_growth"), 3000)       # 1000+2000
        self.assertEqual(val("portfolio_aum"), 12000)       # 5000+7000

        # Idempotent: re-running upserts (no duplicates).
        self.client.post("/staff_management/rm-kpi-base-summary/refresh/")
        self.assertEqual(RmKPIBaseSummary.objects.filter(sales_code="RM7").count(), 6)


# ── Managed mirror uploads for warehouse datasets (write target via *_upload) ────

class WarehouseMirrorUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mir", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    _EXCL = ("id", "uploaded_at", "updated_at")

    def test_merchant_till_upload_persists_to_mirror_and_lists(self):
        from .models import MerchantBankTillManualUpload
        url = "/staff_management/merchant-bank-tills-manual/upload-csv/"
        csv = _model_csv(MerchantBankTillManualUpload, [{"merchant_id": "M1", "account_name": "Shop A"}], excluded=self._EXCL)
        r = self.client.post(url, {"file": csv}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("application/zip", r["Content-Type"])
        self.assertEqual(MerchantBankTillManualUpload.objects.count(), 1)
        # Uploaded rows are retrievable from the mirror list endpoint.
        r = self.client.get("/staff_management/merchant-bank-tills-manual/uploads/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["count"], 1)

    def test_weighted_sales_daily_accounts_upload_no_longer_404(self):
        from .models import DailySalesAccountsWithCtoUpload
        url = "/staff_management/weighted-sales-daily-accounts/upload-csv/"
        csv = _model_csv(DailySalesAccountsWithCtoUpload, [{"acc_num": "A1", "account_status": "active"}], excluded=self._EXCL)
        r = self.client.post(url, {"file": csv}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(DailySalesAccountsWithCtoUpload.objects.count(), 1)

    def test_retail_allocated_portfolio_upserts_on_cust_id(self):
        from apps.portfolio.models import RetailAllocatedPortfolioUpload
        url = "/staff_management/retail-allocated-portfolio/upload-csv/"
        for name in ("Alpha", "Beta"):
            csv = _model_csv(RetailAllocatedPortfolioUpload, [{"cust_id": "777", "customer_name": name}], excluded=self._EXCL)
            r = self.client.post(url, {"file": csv}, format="multipart")
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(RetailAllocatedPortfolioUpload.objects.filter(cust_id=777).count(), 1)
        self.assertEqual(RetailAllocatedPortfolioUpload.objects.get(cust_id=777).customer_name, "Beta")
