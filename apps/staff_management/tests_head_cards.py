"""The heads' cards (migration 0060).

Anna Amasinde - SME HEAD, AA3104 - was "role has no card" along with every
other head: 233 of 454 sales codes on the coverage run were skipped for it.
"""

import datetime

from django.test import TestCase

from .live_scorecard import SOURCES, card_role_for

HEAD_ROLES = ("head_commercial", "sme_head", "trade_head", "pb_head",
              "sales_ib_head", "branch_business_head")


def seed_heads():
    """Another module's TransactionTestCase can flush what the migrations
    seeded before this one runs, so the seed is replayed here."""
    import importlib

    from django.apps import apps

    importlib.import_module(
        "apps.staff_management.migrations.0060_seed_head_cards").seed(
            apps, None)


class HeadCardShapeTests(TestCase):

    def setUp(self):
        seed_heads()

    def test_every_head_card_weighs_exactly_one(self):
        from .scorecard_automation.models import ScRoleKpiMapping

        for role in HEAD_ROLES:
            with self.subTest(role):
                weights = [float(w) for w in ScRoleKpiMapping.objects.filter(
                    role_code=role).values_list("kpi_weight", flat=True)]
                self.assertTrue(weights, f"{role} has no lines")
                self.assertAlmostEqual(sum(weights), 1.0, places=6)

    def test_every_head_line_has_a_source_and_is_loadable(self):
        from .scorecard_automation.models import ScRoleKpiMapping
        from .scorecard_manual import MANUAL_ACTUALS, MANUAL_TARGETS

        for code in set(ScRoleKpiMapping.objects.filter(
                role_code__in=HEAD_ROLES).values_list("kpi_code", flat=True)):
            with self.subTest(code):
                self.assertIn(code, SOURCES)
                self.assertIn(code, MANUAL_ACTUALS)
                if code.startswith("head_"):
                    self.assertIn(code, MANUAL_TARGETS)

    def test_the_titles_reach_the_head_cards(self):
        for title, role in (("SME HEAD", "sme_head"),
                            ("HEAD OF SME AND COMMERCIAL", "sme_head"),
                            ("TRADE HEAD", "trade_head"),
                            ("Head Of Trade Finance", "trade_head"),
                            ("PB HEAD", "pb_head"),
                            ("HEAD OF PERSONAL BANKING", "pb_head"),
                            ("HEAD OF SALES AND IB", "sales_ib_head"),
                            ("HEAD OF BRANCH BUSINESS",
                             "branch_business_head"),
                            ("HEAD OF COMMERCIAL", "head_commercial"),
                            # Not a head, and not guessed onto one.
                            ("RBBM", None)):
            with self.subTest(title):
                self.assertEqual(card_role_for(title), role)

    def test_lower_is_better_where_the_card_says_reduce(self):
        for code in ("head_npl", "head_sla", "head_cost_management",
                     "head_interest_expense"):
            with self.subTest(code):
                self.assertFalse(SOURCES[code].higher_is_better)


class AnnaAmasindeTests(TestCase):

    CODE = "AA3104"

    def setUp(self):
        from .models import BranchEmployeeDmcData

        seed_heads()
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=3104, staff_name="Anna Amasinde",
            sales_code=self.CODE, staff_role="SME HEAD", staff_branch="H/Q",
            staff_unit="H/Q", active=1)

    def test_she_has_a_card(self):
        from .live_scorecard import build_card

        card = build_card(self.CODE)
        self.assertTrue(card.get("has_card"), card)
        self.assertEqual(card["staff"]["role_code"], "sme_head")

    def test_a_loaded_department_figure_reaches_her_card(self):
        from .live_scorecard import build_card, last_closed_month_end
        from .scorecard_automation.models import ScEmployeePerformanceActual

        month = last_closed_month_end(datetime.date.today()).replace(day=1)
        ScEmployeePerformanceActual.objects.create(
            sales_code=self.CODE, kpi_code="head_revenue",
            kpi_value=143_586_266.14, eom_date=month)
        card = build_card(self.CODE)
        lines = {ln["kpi_code"]: ln for group in card["perspectives"]
                 for ln in group["lines"]}
        self.assertAlmostEqual(lines["head_revenue"]["ytd_actual"],
                               143_586_266.14, places=2)
