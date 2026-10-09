from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.staff_management.models import StaffEmployeeData, EmployeeRoleHistory
from apps.staff_management.scorecard_automation.models import (
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance, ScEmployeeKpiTarget,
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


class PerPersonTargetTests(TestCase):
    """A target allocated to one person beats the one on their role.

    The financial KPIs are allocated individually in the scorecard workbook's
    "Summary Allocation" sheet - one RM's deposit growth target there is 4.35x
    his own base, which no role-level rate can express. These tests pin the
    precedence, and pin that nothing changes for a KPI nobody has allocated.
    """

    def setUp(self):
        _seed_engine()

    def _run_and_read(self):
        EmployeeMonthlyPerformanceService.run_monthly_kpi_scorecard_for_employee(
            "RM001", EOM)
        return ScEmployeeMonthlyPerformance.objects.get(
            sales_code="RM001", kpi_code="deposits", eom_date=EOM)

    def test_without_an_allocation_the_roles_target_still_applies(self):
        """The engine's existing behaviour, unchanged - this is the control."""
        row = self._run_and_read()
        self.assertEqual(row.kpi_target, 100, "the role mapping's target")

    def test_an_allocated_target_replaces_the_roles(self):
        ScEmployeeKpiTarget.objects.create(
            sales_code="RM001", kpi_code="deposits", year=EOM.year,
            kpi_target=250, source="Summary Allocation")
        row = self._run_and_read()
        self.assertEqual(row.kpi_target, 250)

    def test_an_allocation_for_somebody_else_is_not_picked_up(self):
        ScEmployeeKpiTarget.objects.create(
            sales_code="RM999", kpi_code="deposits", year=EOM.year,
            kpi_target=250)
        self.assertEqual(self._run_and_read().kpi_target, 100)

    def test_an_allocation_for_another_year_is_not_picked_up(self):
        ScEmployeeKpiTarget.objects.create(
            sales_code="RM001", kpi_code="deposits", year=EOM.year - 1,
            kpi_target=250)
        self.assertEqual(self._run_and_read().kpi_target, 100)

    def test_the_allocation_can_carry_the_base_value_too(self):
        """base_value is the scorecard's "2025 FY" column. One upload should be
        able to set both numbers without a second round trip."""
        ScEmployeeKpiTarget.objects.create(
            sales_code="RM001", kpi_code="deposits", year=EOM.year,
            kpi_target=250, base_value=1_000)
        row = self._run_and_read()
        self.assertEqual(row.prev_year_value, 1_000)

    def test_one_person_one_target_per_kpi_per_year(self):
        from django.db import IntegrityError, transaction

        ScEmployeeKpiTarget.objects.create(
            sales_code="RM001", kpi_code="deposits", year=EOM.year, kpi_target=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ScEmployeeKpiTarget.objects.create(
                sales_code="RM001", kpi_code="deposits", year=EOM.year, kpi_target=2)
