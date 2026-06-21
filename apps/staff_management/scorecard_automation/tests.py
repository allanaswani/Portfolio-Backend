from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.staff_management.models import StaffEmployeeData, EmployeeRoleHistory
from apps.staff_management.scorecard_automation.models import (
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance,
)
from apps.staff_management.scorecard_automation.services import (
    EmployeeMonthlyPerformanceService,
)

EOM = date(date.today().year, 5, 1)


def _seed_engine():
    ScRole.objects.create(role_code="rm", role_name="Relationship Manager", role_type="IC")
    ScKpi.objects.create(
        kpi_code="deposits", kpi_name="Deposits",
        kpi_calculation_mode="actual_over_target", score_cap="1.00",
        has_base_value=False, is_increasing=True, is_active=True,
    )
    ScRoleKpiMapping.objects.create(
        role_code="rm", kpi_order=1, kpi_code="deposits", mapping_category="Financial",
        kpi_target=100, effective_from=date(EOM.year, 1, 1), effective_to=date(EOM.year, 12, 31),
        bonus_effective_from=date(EOM.year, 1, 1), bonus_effective_to=date(EOM.year, 12, 31),
        kpi_weight=Decimal("1.00000"), plan_category="p1", target_category="monthly", prorate=False,
        is_bonus=False,
    )
    StaffEmployeeData.objects.create(
        staff_pf_number=1001, staff_name="Jane Doe", staff_email="jane@hf.co.ke",
        sales_code="RM001", department="Retail", staff_unit="Branch A", staff_org_unit="Branch A",
        job_title="RM", employment_date=date(EOM.year, 1, 1),
        employee_category="retail_branch_front_office", is_active=True,
    )
    EmployeeRoleHistory.objects.create(
        sales_code="RM001", role_code="rm",
        start_date=date(EOM.year, 1, 1), end_date=date(EOM.year, 12, 31),
    )
    ScEmployeePerformanceActual.objects.create(
        sales_code="RM001", kpi_code="deposits", eom_date=EOM, kpi_value=80,
    )


class ScorecardEngineTests(TestCase):
    def setUp(self):
        _seed_engine()

    def test_run_monthly_scorecard_computes_expected_score(self):
        result = EmployeeMonthlyPerformanceService.run_monthly_kpi_scorecard(EOM.isoformat())
        self.assertEqual(result["status"], "completed")

        row = ScEmployeeMonthlyPerformance.objects.get(sales_code="RM001", kpi_code="deposits", eom_date=EOM)
        # actual 80 / target 100 = 0.8, capped at 1.00, weighted by 1.0 → 0.8
        self.assertEqual(row.ytd_actual, 80)
        self.assertEqual(row.ytd_target, 100)
        self.assertAlmostEqual(row.ytd_score, 0.8, places=4)
        self.assertAlmostEqual(row.ytd_weighted_score, 0.8, places=4)
        self.assertEqual(row.role_code, "rm")
        self.assertEqual(row.kpi_name, "Deposits")

    def test_run_is_idempotent(self):
        EmployeeMonthlyPerformanceService.run_monthly_kpi_scorecard(EOM.isoformat())
        EmployeeMonthlyPerformanceService.run_monthly_kpi_scorecard(EOM.isoformat())
        self.assertEqual(
            ScEmployeeMonthlyPerformance.objects.filter(sales_code="RM001", eom_date=EOM).count(), 1
        )


class ScorecardAutomationApiTests(TestCase):
    def setUp(self):
        _seed_engine()
        self.user = get_user_model().objects.create_user(username="tester", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_run_endpoint_generates_rows(self):
        resp = self.client.post(
            "/staff_management/scorecard-automation/run/",
            {"eom_date": EOM.isoformat(), "scope": "all"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["status"], "completed")
        self.assertTrue(ScEmployeeMonthlyPerformance.objects.filter(eom_date=EOM).exists())

    def test_monthly_performance_list_endpoint(self):
        EmployeeMonthlyPerformanceService.run_monthly_kpi_scorecard(EOM.isoformat())
        resp = self.client.get("/staff_management/scorecard-automation/monthly_performance/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertGreaterEqual(resp.data["count"], 1)

    def test_kpi_crud_endpoint(self):
        resp = self.client.get("/staff_management/scorecard-automation/kpis/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertGreaterEqual(resp.data["count"], 1)
