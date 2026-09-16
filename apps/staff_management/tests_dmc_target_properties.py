"""target_properties on branch_final_employee_dmc_data.

targets.py's CATALOGUE has always carried a
("properties", "target_properties", "number", "Property Sales", ...) entry, but
the column existed only on branch_employee_dmc_data (the per-staff table).
rollup() intersects the catalogue with the columns a table actually has, so at
bank, zone and branch scope the metric was skipped in silence — no error, just
a target nobody could see.

The column now exists on the branch table too, filled from the plan by
migration 0018.
"""
from decimal import Decimal

from django.test import TestCase

from apps.staff_management import targets
from apps.staff_management.models import (
    BranchFinalEmployeeDmcData, BranchPropertyTarget,
)


class ColumnTests(TestCase):
    def test_the_catalogue_entry_now_resolves_on_the_branch_table(self):
        cols = targets._columns(BranchFinalEmployeeDmcData)
        self.assertIn("target_properties", cols)

    def test_it_is_decimal_not_integer(self):
        """Rounding the 22 branch figures to whole units makes them sum to 341.
        The bank would be reading a plan one unit bigger than the one it set."""
        field = BranchFinalEmployeeDmcData._meta.get_field("target_properties")
        self.assertEqual(field.get_internal_type(), "DecimalField")
        self.assertEqual(field.decimal_places, 8)


class SeededFromThePlanTests(TestCase):
    """Migrations 0016 and 0018 both run when the test database is built."""

    def test_every_planned_branch_reached_its_dmc_row(self):
        planned = {
            t.brn_code: t.target_properties
            for t in BranchPropertyTarget.objects.filter(year=2026)
        }
        self.assertEqual(len(planned), 22)

        for brn, target in planned.items():
            rows = BranchFinalEmployeeDmcData.objects.filter(brn_code=brn)
            if not rows.exists():
                # 0018 reports these rather than inventing a DMC row. A test
                # database built without the DMC fixture legitimately has none;
                # what must never happen is a row carrying the WRONG figure.
                continue
            for row in rows:
                self.assertEqual(row.target_properties, target)

    def test_a_branch_gets_its_own_figure_not_a_neighbours(self):
        """260 is "THIKA ROAD MALL-TRM BRANCH" in the plan and "TRM BRANCH" in
        the warehouse; 500 is THIKA. Matching on name put 260's plan on 500."""
        rehani = BranchPropertyTarget.objects.get(brn_code=200, year=2026)
        trm = BranchPropertyTarget.objects.get(brn_code=260, year=2026)
        thika = BranchPropertyTarget.objects.get(brn_code=500, year=2026)
        self.assertEqual(rehani.target_properties, Decimal("35.66433566"))
        self.assertEqual(trm.target_properties, Decimal("7.13286713"))
        self.assertEqual(thika.target_properties, Decimal("16.64335664"))
        self.assertNotEqual(trm.target_properties, thika.target_properties)


class BankRollupTests(TestCase):
    """The reason the column is a decimal, demonstrated end to end."""

    def setUp(self):
        BranchFinalEmployeeDmcData.objects.all().delete()
        for t in BranchPropertyTarget.objects.filter(year=2026):
            BranchFinalEmployeeDmcData.objects.create(
                brn_code=t.brn_code,
                staff_branch=t.staff_branch,
                staff_zone=t.staff_zone,
                target_properties=t.target_properties,
                # rollup() counts current staff only (targets._active). A row
                # left with active NULL is silently excluded, so a fixture
                # without this returns None for every metric, not just this one.
                active=1,
                exit=0,
            )

    def test_the_bank_target_is_340(self):
        out = targets.rollup("bank")
        entry = out["targets"]["properties"]
        self.assertEqual(entry["label"], "Property Sales")
        self.assertEqual(entry["annual"], 340.0)

    def test_rounding_each_branch_first_would_have_given_341(self):
        """Guards the choice, not the code: if someone 'tidies' the column to an
        integer, the exact sum below stops being 340 and this fails."""
        exact = sum(
            r.target_properties
            for r in BranchFinalEmployeeDmcData.objects.all()
        )
        self.assertEqual(exact, Decimal("340.00000000"))
        rounded = sum(
            round(r.target_properties)
            for r in BranchFinalEmployeeDmcData.objects.all()
        )
        self.assertEqual(rounded, 341)

    def test_a_zone_sums_only_its_own_branches(self):
        out = targets.rollup("zone", value="Zone C")
        # Zone C is Rehani alone.
        self.assertEqual(out["targets"]["properties"]["annual"], 36.0)

    def test_one_branch_reads_its_own_plan(self):
        out = targets.rollup("branch", value="REHANI BRANCH")
        self.assertEqual(out["targets"]["properties"]["annual"], 36.0)

    def test_the_metric_reports_which_table_it_came_from(self):
        out = targets.rollup("bank")
        self.assertEqual(
            out["targets"]["properties"]["source"],
            "branch_final_employee_dmc_data",
        )
