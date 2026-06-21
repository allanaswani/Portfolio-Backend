from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.hfdi.models import (
    Project, Sales, HfdiTargets, CrmProject, LegacyProject,
    CrmSalesRecord, LegacySalesRecord, HfdiManualFinanceEntry,
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
