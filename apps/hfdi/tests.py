import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.hfdi.models import (
    Project, Sales, HfdiTargets, CrmProject, LegacyProject,
    CrmSalesRecord, LegacySalesRecord, HfdiManualFinanceEntry,
    AffordableHousingApplication, AffordableHousingRegistrations,
)

BASE = "/hfdi/"
THIS_MONTH = date.today().replace(day=1)


def _seed():
    project = Project.objects.create(name="Riverside")
    Sales.objects.create(
        project=project, pm="PM", month=THIS_MONTH,
        mtd_volume=5, ytd_volume=5,
        mtd_value=Decimal("100"), ytd_value=Decimal("100"), ytd_income=Decimal("20"),
    )
    HfdiTargets.objects.create(
        project_id=project.id, pm="PM", rm="RM", month=str(THIS_MONTH),
        target_start_date=str(THIS_MONTH.replace(month=1)),
        target_sales_end_date=str(date(THIS_MONTH.year, 12, 31)),
        target_collections_end_date=str(date(THIS_MONTH.year, 12, 31)),
        volume=10, value=Decimal("200"), income=Decimal("50"), collections_value=Decimal("150"),
    )
    CrmProject.objects.create(project_id=1001, project_name="Riverside")
    LegacyProject.objects.create(project_id=1002, project_name="Hillview")
    CrmSalesRecord.objects.create(
        project_id=1001, sale_month=THIS_MONTH, mtd_volume=3, ytd_volume=3,
        mtd_value=Decimal("60"), ytd_value=Decimal("60"),
    )
    LegacySalesRecord.objects.create(
        project_id=1002, sale_month=THIS_MONTH, mtd_volume=2, ytd_volume=2,
        mtd_value=Decimal("40"), ytd_value=Decimal("40"),
    )
    HfdiManualFinanceEntry.objects.create(
        project_id=1001, sale_month=THIS_MONTH,
        ytd_revenue_booked=Decimal("30"), mtd_revenue_booked=Decimal("30"),
    )


class HfdiDashboardAggregationTests(TestCase):
    def setUp(self):
        _seed()
        self.user = get_user_model().objects.create_user(username="hfdi", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_all_aggregation_endpoints_run(self):
        for path in [
            "hfdi_sales_months_recorded/",
            "projects_monthly_performance_hfdi_list/",
            "hfdi_api_sales_data_monthly_volume_sumary_api_data/",
            "hfdi_api_sales_data_monthly_value_sumary_api_data/",
            "hfdi_api_sales_data_monthly_ytd_income_sumary_api_data/",
            "hfdi-ytd_performance_hfdi_list/",
            "hfdi-ytd_performance_hfdi_list_per_project/",
            "hfdi-combined-projects-list/",
        ]:
            resp = self.client.get(BASE + path)
            self.assertEqual(resp.status_code, 200, f"{path} -> {resp.status_code}: {resp.content}")
            self.assertIsInstance(resp.data, list)

    def test_volume_summary_pivots_current_month(self):
        resp = self.client.get(BASE + "hfdi_api_sales_data_monthly_volume_sumary_api_data/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.data), 1)
        month_key = ["jan", "feb", "march", "apr", "may", "june",
                     "july", "aug", "sept", "oct", "nov", "dec"][THIS_MONTH.month - 1]
        self.assertEqual(resp.data[0][month_key], 5)

    def test_combined_projects_merges_crm_and_legacy(self):
        resp = self.client.get(BASE + "hfdi-combined-projects-list/")
        self.assertEqual(resp.status_code, 200, resp.content)
        names = {r["project_name"] for r in resp.data}
        self.assertIn("Riverside", names)
        self.assertIn("Hillview", names)

    def test_crud_alias_paths_resolve(self):
        for path in ["hfdi_target_feedback/", "hfdi_sales_data/", "obligation_summary/",
                     "hfdi_crm_projects/", "hfdi_sales_legacy/", "hfdi-targets/"]:
            resp = self.client.get(BASE + path)
            self.assertEqual(resp.status_code, 200, f"{path} -> {resp.status_code}")


def _csv_upload(rows, fieldnames):
    import csv
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return SimpleUploadedFile("upload.csv", buf.getvalue().encode("utf-8"), content_type="text/csv")


class AffordableHousingCsvUploadTests(TestCase):
    """The two affordable-housing uploaders amend columns + upsert (legacy contract)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="afh", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_application_upload_amends_and_upserts(self):
        cols = ["application_id", "timestamp", "name", "assisted_by", "preferred_typology",
                "typology", "mode_of_payment", "need_deposit_assitance", "status",
                "phone_number", "email", "deposits", "unit_price"]
        row = {c: "" for c in cols}
        row.update({
            "application_id": "APP-1", "timestamp": "05, March 2024 14:30", "name": "Jane",
            "preferred_typology": "Two Bedroom (2BR)", "phone_number": "254700000001",
            "deposits": "1,200", "unit_price": "3,500,000",
        })
        resp = self.client.post(
            BASE + "affordable-housing-applications/upload-csv/",
            {"file": _csv_upload([row], cols)}, format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("application/zip", resp["Content-Type"])

        obj = AffordableHousingApplication.objects.get(phone_number=254700000001)
        self.assertEqual(obj.house_type, "2BR")               # last parenthesised group
        self.assertEqual(obj.timestamp, "2024-03-05T14:30:00")  # parsed timestamp
        self.assertEqual(obj.deposits, Decimal("1200"))         # commas stripped
        self.assertEqual(obj.unit_price, Decimal("3500000"))

        # Re-upload same phone+timestamp → update, not duplicate.
        row["name"] = "Jane Updated"
        resp = self.client.post(
            BASE + "affordable-housing-applications/upload-csv/",
            {"file": _csv_upload([row], cols)}, format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(AffordableHousingApplication.objects.filter(phone_number=254700000001).count(), 1)
        self.assertEqual(AffordableHousingApplication.objects.get(phone_number=254700000001).name, "Jane Updated")

    def test_registrations_upload_amends_and_upserts(self):
        cols = ["timestamp", "name", "phone_number", "email", "assisted_by",
                "user_deposits", "typology", "project", "unit_price"]
        row = {c: "" for c in cols}
        row.update({
            "timestamp": "05, March 2024 14:30", "name": "Ken", "phone_number": "254700000002",
            "assisted_by": "Agent", "user_deposits": "-", "typology": "Studio (STD)",
            "project": "Pangani", "unit_price": "2,000,000",
        })
        resp = self.client.post(
            BASE + "affordable-housing-registrations/upload-csv/",
            {"file": _csv_upload([row], cols)}, format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("application/zip", resp["Content-Type"])

        obj = AffordableHousingRegistrations.objects.get(phone_number=254700000002)
        self.assertEqual(obj.house_type, "STD")
        self.assertEqual(obj.user_deposits, Decimal("0"))       # '-' → 0
        self.assertEqual(obj.unit_price, Decimal("2000000"))

        # Re-upload same phone → update existing instance, no duplicate.
        row["name"] = "Ken Updated"
        resp = self.client.post(
            BASE + "affordable-housing-registrations/upload-csv/",
            {"file": _csv_upload([row], cols)}, format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(AffordableHousingRegistrations.objects.filter(phone_number=254700000002).count(), 1)
        self.assertEqual(AffordableHousingRegistrations.objects.get(phone_number=254700000002).name, "Ken Updated")

    def test_missing_columns_rejected(self):
        resp = self.client.post(
            BASE + "affordable-housing-applications/upload-csv/",
            {"file": _csv_upload([{"name": "x"}], ["name"])}, format="multipart",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("missing", str(resp.data).lower())


def _model_csv(model, rows, excluded=("id",)):
    """CSV covering every editable column of ``model`` with type-valid defaults."""
    import csv
    from django.db import models as dm
    excluded = set(excluded)
    fields = [f for f in model._meta.concrete_fields if f.editable and f.name not in excluded]
    cols = [f.name for f in fields]

    def default_for(f):
        if isinstance(f, dm.EmailField):
            return "a@b.com"
        if isinstance(f, (dm.IntegerField, dm.BigIntegerField, dm.DecimalField, dm.FloatField)):
            return "0"
        if isinstance(f, dm.DateTimeField):
            return "2024-01-01T00:00:00"
        if isinstance(f, dm.DateField):
            return "2024-01-01"
        return "x"

    by_name = {f.name: f for f in fields}
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r[c] if c in r else default_for(by_name[c]) for c in cols})
    return SimpleUploadedFile("u.csv", buf.getvalue().encode("utf-8"), content_type="text/csv")


class HfdiAmendingUploaderTests(TestCase):
    """The HFDI uploaders that upsert / amend columns (ported from the old backend)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="up", password="pw12345", first_name="Up", last_name="Loader")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_mortgages_upserts_on_project_unit(self):
        from apps.hfdi.models import HfdiCustomersHfcMortgages
        url = BASE + "hfdi_customers_hfc_mortgages/upload-csv/"
        for stage in ("A", "B"):
            r = self.client.post(
                url, {"file": _model_csv(HfdiCustomersHfcMortgages,
                      [{"project": "Riverside", "unit": "U1", "mortgage_stage": stage}])},
                format="multipart")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertIn("application/zip", r["Content-Type"])
        self.assertEqual(HfdiCustomersHfcMortgages.objects.filter(project="Riverside", unit="U1").count(), 1)
        self.assertEqual(HfdiCustomersHfcMortgages.objects.get(project="Riverside", unit="U1").mortgage_stage, "B")

    def test_pipeline_upserts_and_cleans_units(self):
        from apps.hfdi.models import AffordableHousingProjectsPipeline
        url = BASE + "affordable_housing_pipeline/upload-csv/"
        r = self.client.post(
            url, {"file": _model_csv(AffordableHousingProjectsPipeline,
                  [{"project_name": "Pangani", "units": "1,200"}])}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        obj = AffordableHousingProjectsPipeline.objects.get(project_name="Pangani")
        self.assertEqual(obj.units, 1200)   # comma stripped

    def test_seller_mapping_upserts_on_staff_id(self):
        from apps.hfdi.models import AFHSellerMapping
        url = BASE + "afh_seller_mapping/upload-csv/"
        for unit in ("Sales", "Ops"):
            r = self.client.post(
                url, {"file": _model_csv(AFHSellerMapping, [{"staff_id": "S1", "staff_unit": unit}])},
                format="multipart")
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(AFHSellerMapping.objects.filter(staff_id="S1").count(), 1)

    def test_employee_sales_existence_and_duplicate_guards(self):
        from apps.hfdi.models import HfdiEmployeeData, HfdiEmployeeDataSalesRecord
        HfdiEmployeeData.objects.create(staff_pf_number=5001, staff_name="Jane")
        url = BASE + "employee_sales/upload-csv/"
        row = {"staff_pf_number": "5001", "sale_month": "2024-03-15", "mtd_volume": "3"}
        r = self.client.post(url, {"file": _model_csv(HfdiEmployeeDataSalesRecord, [row])}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        rec = HfdiEmployeeDataSalesRecord.objects.get(staff_pf_number=5001)
        self.assertEqual(str(rec.sale_month), "2024-03-01")        # normalised to 1st
        self.assertEqual(rec.input_user, "Up Loader")              # stamped from request user

        # Duplicate (same pf + month) is skipped, unknown pf is rejected.
        self.client.post(url, {"file": _model_csv(HfdiEmployeeDataSalesRecord, [row])}, format="multipart")
        self.assertEqual(HfdiEmployeeDataSalesRecord.objects.filter(staff_pf_number=5001).count(), 1)
        bad = {"staff_pf_number": "9999", "sale_month": "2024-03-15", "mtd_volume": "3"}
        self.client.post(url, {"file": _model_csv(HfdiEmployeeDataSalesRecord, [bad])}, format="multipart")
        self.assertFalse(HfdiEmployeeDataSalesRecord.objects.filter(staff_pf_number=9999).exists())
