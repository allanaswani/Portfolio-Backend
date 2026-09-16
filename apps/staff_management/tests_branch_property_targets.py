"""The branch property plan: what migration 0016 loaded, and the map it needs.

The plan is 22 branches summing to exactly 340 units for 2026. That total is the
contract — an apportionment that no longer adds up to the bank figure is wrong
however plausible each branch's row looks — so it is asserted here rather than
left to whoever next edits the list.
"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.staff_management.models import BranchPropertyTarget
from core.date_utils import BRANCH_BY_CODE, branch_code_for


class BranchCodeMapTests(SimpleTestCase):
    """branch_code_for turns a branch NAME into the warehouse code."""

    def test_every_branch_in_the_sql_case_is_parsed(self):
        """The regex reads BRN_CASE. It pads single-digit codes with a second
        space, and a pattern expecting exactly one space found only 16 of 24."""
        self.assertEqual(len(BRANCH_BY_CODE), 24)
        self.assertEqual(BRANCH_BY_CODE[25], "EMBU BRANCH")
        self.assertEqual(BRANCH_BY_CODE[19], "HURLINGHAM BRANCH")

    def test_exact_names_resolve(self):
        self.assertEqual(branch_code_for("REHANI BRANCH"), 200)
        self.assertEqual(branch_code_for("rehani branch"), 200)
        self.assertEqual(branch_code_for("  MOMBASA BRANCH "), 300)

    def test_the_plan_spellings_resolve_to_the_right_branch(self):
        """The plan's names are not the warehouse's names."""
        self.assertEqual(branch_code_for("SAMEER BUSINESS PARK BRANCH"), 270)
        self.assertEqual(branch_code_for("THIKA ROAD MALL-TRM BRANCH"), 260)

    def test_thika_road_mall_is_not_thika(self):
        """A fuzzy 'shares a word' match resolved THIKA ROAD MALL-TRM to THIKA
        (500) instead of TRM (260). One branch's plan on another branch's page
        is worse than no plan at all."""
        self.assertNotEqual(branch_code_for("THIKA ROAD MALL-TRM BRANCH"),
                            branch_code_for("THIKA BRANCH"))
        self.assertEqual(branch_code_for("THIKA BRANCH"), 500)

    def test_an_unknown_branch_is_none_not_a_guess(self):
        self.assertIsNone(branch_code_for("KISII BRANCH"))
        self.assertIsNone(branch_code_for(""))
        self.assertIsNone(branch_code_for(None))


class SeededPlanTests(TestCase):
    """Migration 0016 runs when the test database is built."""

    def test_twenty_two_branches_for_2026(self):
        self.assertEqual(
            BranchPropertyTarget.objects.filter(year=2026).count(), 22)

    def test_the_plan_sums_to_exactly_340(self):
        total = sum(
            t.target_properties
            for t in BranchPropertyTarget.objects.filter(year=2026)
        )
        self.assertEqual(total, Decimal("340.00000000"))

    def test_the_known_figures(self):
        rehani = BranchPropertyTarget.objects.get(brn_code=200, year=2026)
        self.assertEqual(rehani.staff_branch, "REHANI BRANCH")
        self.assertEqual(rehani.staff_zone, "Zone C")
        self.assertEqual(rehani.target_properties, Decimal("35.66433566"))

        embu = BranchPropertyTarget.objects.get(brn_code=25, year=2026)
        self.assertEqual(embu.target_properties, Decimal("7.13286713"))

    def test_zone_c_is_rehani_alone(self):
        zone_c = BranchPropertyTarget.objects.filter(year=2026, staff_zone="Zone C")
        self.assertEqual([t.brn_code for t in zone_c], [200])

    def test_every_planned_branch_resolves_to_its_own_code(self):
        """The name stored alongside the code must agree with the code."""
        for t in BranchPropertyTarget.objects.filter(year=2026):
            self.assertEqual(
                branch_code_for(t.staff_branch), t.brn_code,
                f"{t.staff_branch} resolves to {branch_code_for(t.staff_branch)}, "
                f"stored as {t.brn_code}",
            )

    def test_one_target_per_branch_per_year(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BranchPropertyTarget.objects.create(
                    brn_code=200, year=2026, staff_branch="REHANI BRANCH",
                    target_properties=Decimal("1"),
                )

    def test_a_negative_target_is_rejected(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BranchPropertyTarget.objects.create(
                    brn_code=999, year=2026, staff_branch="NOWHERE",
                    target_properties=Decimal("-1"),
                )
