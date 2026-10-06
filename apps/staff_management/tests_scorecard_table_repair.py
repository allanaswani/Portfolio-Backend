"""The 0021 repair migration, exercised against an actually-missing table.

Production returned 500 on the two RM scorecard endpoints with
`relation "sc_employee_monthly_performance" does not exist` while
staff_management.0003 was recorded as applied - legacy django_migrations rows
from the old project shadow this repo's, so a migration can be marked applied
without its DDL running. A fresh test database always has the table, so the
repair path would otherwise never be executed by the suite.
"""
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from importlib import import_module

repair = import_module("apps.staff_management.migrations.0021_ensure_scorecard_tables")
TABLE = "sc_employee_monthly_performance"


def _table_exists():
    with connection.cursor() as cursor:
        return TABLE in connection.introspection.table_names(cursor)


class ScorecardTableRepairTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="rm1", password="pw12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_it_recreates_the_table_when_it_is_missing(self):
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {TABLE} CASCADE")
        self.assertFalse(_table_exists(), "precondition: the table is gone")

        with connection.schema_editor() as editor:
            repair.create_missing(global_apps, editor)

        self.assertTrue(_table_exists(), "0021 must put it back")

    def test_the_endpoints_that_500ed_work_again_afterwards(self):
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {TABLE} CASCADE")
        with connection.schema_editor() as editor:
            repair.create_missing(global_apps, editor)

        for path in ["/staff_management/monthly-performance-detail/self/",
                     "/staff_management/monthly-performance-summary/rm/"]:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200,
                             f"{path} -> {resp.status_code}: {resp.content}")

    def test_the_recreated_table_accepts_a_real_row(self):
        """Columns, not just a name - a wrong shape would fail on insert."""
        from datetime import date
        from apps.staff_management.scorecard_automation.models import (
            ScEmployeeMonthlyPerformance,
        )
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {TABLE} CASCADE")
        with connection.schema_editor() as editor:
            repair.create_missing(global_apps, editor)

        ScEmployeeMonthlyPerformance.objects.create(
            sales_code="RM001", eom_date=date(2026, 9, 30), role_code="RM",
            kpi_order=1, kpi_code="DEP", mapping_category="deposits",
            kpi_name="Deposits", kpi_weight=0.4, ytd_target=100.0,
            ytd_actual=80.0, ytd_score=0.8, ytd_weighted_score=0.32,
        )
        self.assertEqual(ScEmployeeMonthlyPerformance.objects.count(), 1)

    def test_it_is_a_no_op_when_the_table_is_already_there(self):
        self.assertTrue(_table_exists())
        with connection.schema_editor() as editor:
            repair.create_missing(global_apps, editor)
        self.assertTrue(_table_exists())
