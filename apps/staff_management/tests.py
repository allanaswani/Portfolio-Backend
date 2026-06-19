"""Tests for the newly ported staff_management scorecard-config endpoints."""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    ScorecardKPI, ScorecardRole, InsurancePolicy, TradeFinanceData,
    LeaveRecord, EmployeeRoleHistory, Drawdown, TelesalesStaff,
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
        csv_content = (
            b"originating_branch,rm_name,guarantee_ref,product_type,customer_id,segment,"
            b"our_customer,beneficiary,currency,amount_fcy,issue_date,expiry_date,"
            b"commission_lcy,month,fx_rate,year\n"
            b"Nairobi,Jane Doe,GR-1,LC,123,Corporate,Cust A,Ben A,USD,1000.00,2026-01-01,"
            b"2026-06-01,10.000000,1,130.000000,2026\n"
        )
        upload = SimpleUploadedFile("tf.csv", csv_content, content_type="text/csv")
        r = self.client.post("/staff_management/trade-finance/upload-csv/", {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["created"], 1)
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
        r = self.client.post("/staff_management/rm-kpi-base-summary/refresh/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "triggered")

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
