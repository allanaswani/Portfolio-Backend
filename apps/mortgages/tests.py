"""Tests for the mortgages module — CRUD, pipeline, amortization, aggregations."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    MortgageProduct, Borrower, MortgageApplication, MortgageLoan,
    RepaymentScheduleItem, Lead, FieldAgent,
)
from .views import monthly_installment, build_amortization


class AmortizationMathTests(TestCase):
    def test_zero_rate_is_straight_line(self):
        self.assertEqual(monthly_installment(120000, 0, 12), Decimal("10000.00"))

    def test_annuity_payment_and_schedule_clears_balance(self):
        inst = monthly_installment(1_000_000, 12, 12)
        self.assertGreater(inst, Decimal("80000"))  # ~88,849
        _, rows = build_amortization(1_000_000, 12, 12)
        self.assertEqual(len(rows), 12)
        self.assertEqual(Decimal(rows[-1]["balance_after"]), Decimal("0.00"))


class MortgageEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mort_user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.product = MortgageProduct.objects.create(
            name="Home Loan", product_type="home_purchase", interest_rate="12.5")

    def test_product_crud(self):
        r = self.client.post("/mortgages/products/", {
            "name": "Construction Loan", "product_type": "construction",
            "interest_rate": "13.000", "min_tenure_months": 12, "max_tenure_months": 240,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.data["id"]
        r = self.client.patch(f"/mortgages/products/{pid}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(MortgageProduct.objects.get(pk=pid).is_active)

    def test_borrower_create_autoref_application(self):
        b = Borrower.objects.create(full_name="Jane W")
        r = self.client.post("/mortgages/applications/", {
            "borrower": b.id, "product": self.product.id,
            "amount_requested": "5000000.00", "tenure_months": 240,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.data["application_ref"].startswith("APP-"))

    def test_lead_funnel_and_convert(self):
        lead = Lead.objects.create(full_name="Mary K", interested_product=self.product,
                                   estimated_loan_amount="3000000")
        r = self.client.get("/mortgages/leads/funnel/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["total_leads"], 1)

        r = self.client.post(f"/mortgages/leads/{lead.id}/convert/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        lead.refresh_from_db()
        self.assertEqual(lead.status, "converted")
        self.assertIsNotNone(lead.converted_application_id)
        # a borrower was auto-created from the lead
        self.assertTrue(Borrower.objects.filter(full_name="Mary K").exists())

    def test_approve_then_disburse_generates_schedule(self):
        b = Borrower.objects.create(full_name="Paul O")
        app = MortgageApplication.objects.create(
            borrower=b, product=self.product, amount_requested="1000000", tenure_months=12)
        r = self.client.post(f"/mortgages/applications/{app.id}/approve/",
                             {"comments": "ok"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "approved")

        r = self.client.post(f"/mortgages/applications/{app.id}/disburse/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        loan = MortgageLoan.objects.get(application=app)
        self.assertGreater(loan.monthly_installment, Decimal("0"))
        self.assertEqual(RepaymentScheduleItem.objects.filter(loan=loan).count(), 12)
        app.refresh_from_db()
        self.assertEqual(app.status, "disbursed")

    def test_disburse_twice_blocked(self):
        b = Borrower.objects.create(full_name="Twice")
        app = MortgageApplication.objects.create(
            borrower=b, product=self.product, amount_requested="500000", tenure_months=6)
        self.client.post(f"/mortgages/applications/{app.id}/disburse/", {}, format="json")
        r = self.client.post(f"/mortgages/applications/{app.id}/disburse/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_calculator(self):
        r = self.client.post("/mortgages/calculator/", {
            "principal": "1000000", "interest_rate": "12", "tenure_months": 12,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data["schedule"]), 12)
        self.assertGreater(Decimal(r.data["total_interest"]), Decimal("0"))

    def test_calculator_requires_fields(self):
        r = self.client.post("/mortgages/calculator/", {"principal": "1000000"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_payment_create(self):
        b = Borrower.objects.create(full_name="Payer")
        loan = MortgageLoan.objects.create(borrower=b, principal="1000000",
                                           interest_rate="12", tenure_months=12)
        r = self.client.post("/mortgages/payments/", {
            "loan": loan.id, "amount": "88849.00", "principal_paid": "78849.00",
            "interest_paid": "10000.00", "method": "mpesa",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_field_visit_csv_upload_and_leaderboard(self):
        agent = FieldAgent.objects.create(name="John Kamau", team="Westlands")
        Lead.objects.create(full_name="L1", field_agent=agent, status="converted")
        Lead.objects.create(full_name="L2", field_agent=agent, status="new")
        header = ("field_agent,team,location,prospects_reached,leads_collected,"
                  "qualified_leads,customers_onboarded,applications_started,follow_ups_needed\n")
        csv_content = (header + f"{agent.id},Westlands,Westlands,25,25,10,5,5,8\n").encode()
        upload = SimpleUploadedFile("visits.csv", csv_content, content_type="text/csv")
        r = self.client.post("/mortgages/field-visits/upload-csv/",
                            {"file": upload}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["created"], 1)

        r = self.client.get("/mortgages/field/leaderboard/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["leads"], 2)
        self.assertEqual(r.data[0]["converted"], 1)

    def test_dashboard(self):
        r = self.client.get("/mortgages/dashboard/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("outstanding_balance", r.data)
        self.assertIn("applications_by_status", r.data)

    def test_requires_authentication(self):
        anon = APIClient()
        for url in ["/mortgages/products/", "/mortgages/leads/", "/mortgages/dashboard/"]:
            self.assertIn(anon.get(url).status_code, (401, 403))


class DeferredFeatureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("feat_user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_interest_rate_crud_sets_creator(self):
        r = self.client.post("/mortgages/interest-rates/", {
            "name": "KMRC Affordable", "rate_type": "kmrc", "rate": "9.500",
            "effective_date": "2026-01-01",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        from .models import InterestRate
        self.assertEqual(InterestRate.objects.get().created_by, self.user)
        r = self.client.get("/mortgages/interest-rates/?is_active=true")
        self.assertEqual(r.status_code, 200)

    def test_collection_case_crud_and_summary(self):
        borrower = Borrower.objects.create(full_name="Jane Doe", branch="THIKA BRANCH")
        loan = MortgageLoan.objects.create(
            borrower=borrower, principal="1000000", outstanding_balance="800000",
            status="active")
        r = self.client.post("/mortgages/collection-cases/", {
            "loan": loan.id, "amount_overdue": "25000", "days_overdue": 45,
            "status": "in_progress",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["loan_ref"], loan.loan_ref)

        # An overdue schedule item should surface in the summary
        RepaymentScheduleItem.objects.create(
            loan=loan, installment_no=1, due_date="2026-01-01",
            payment_amount="25000", is_paid=False)
        r = self.client.get("/mortgages/collections/summary/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("par_pct", r.data)
        self.assertEqual(r.data["overdue_loans"], 1)
        self.assertTrue(any(b["bucket"] == "90+" or b["count"] >= 0 for b in r.data["buckets"]))

    def test_reports_shape(self):
        r = self.client.get("/mortgages/reports/")
        self.assertEqual(r.status_code, 200, r.content)
        for key in ("disbursements_by_month", "portfolio_by_product",
                    "portfolio_by_branch", "applications_by_status", "repayment_performance"):
            self.assertIn(key, r.data)

    def test_notifications_flow(self):
        from .models import Notification
        Notification.objects.create(user=self.user, type="info", title="Hello")
        other = User.objects.create_user("other", password="x")
        Notification.objects.create(user=other, type="info", title="Not mine")

        r = self.client.get("/mortgages/notifications/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)  # only own

        r = self.client.get("/mortgages/notifications/unread-count/")
        self.assertEqual(r.data["unread"], 1)

        nid = Notification.objects.get(user=self.user).id
        r = self.client.post(f"/mortgages/notifications/{nid}/read/")
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/mortgages/notifications/unread-count/")
        self.assertEqual(r.data["unread"], 0)
