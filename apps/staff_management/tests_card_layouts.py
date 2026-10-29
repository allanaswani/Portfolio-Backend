"""Card layouts from the template - a new year's cards by upload.

Against this year's workbooks the loader reports the back-office cards as
132 of 132 lines unchanged, and the sales cards as 180 unchanged with no line
added, removed or re-weighted - the 38 it does change are wording, chiefly
"Grow by 43% of the Dec book" printed on cards that score 21%, 36%, 38% or
100%. These tests hold the rules on a card of their own.
"""

import datetime

from django.test import TestCase

from . import card_layouts as cl

ROLE = "layout_test_card"


def mapping(code, order, weight, wording="", target=None, basis="",
            base="", category="Financials (50%)"):
    from .scorecard_automation.models import ScKpi, ScRoleKpiMapping

    ScKpi.objects.get_or_create(kpi_code=code, defaults={
        "kpi_name": code.replace("_", " ").title(), "kpi_description": "",
        "score_cap": "1.20", "actuals_sheet": code.title()})
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)
    return ScRoleKpiMapping.objects.create(
        role_code=ROLE, kpi_code=code, kpi_order=order,
        mapping_category=category, kpi_description=wording,
        kpi_weight=weight, kpi_target=target, target_basis=basis,
        target_base=base, is_bonus=False, effective_from=start,
        effective_to=end, bonus_effective_from=start, bonus_effective_to=end,
        plan_category="p1", target_category="full_year")


def line(code, order, weight, wording, category="Financials (50%)",
         feed=None):
    return {"order": order, "perspective": category,
            "description": code.replace("_", " "), "measure": wording,
            "weight": weight, "target": None,
            "feed": feed if feed is not None else code.title(), "slug": code}


def card(*lines):
    return [{"sheet": "Test_Sheet", "roles": (ROLE,), "lines": list(lines)}]


class LayoutTests(TestCase):

    def setUp(self):
        mapping("deposits", 1, 0.5, "Grow deposits")
        mapping("asset_growth_t", 2, 0.5, "Grow by 43% of the Dec book",
                target=0.43, basis="rate_on_base", base="december_loan_book")

    def statuses(self, plans):
        return {l["kpi_code"]: l["status"] for p in plans for l in p["lines"]}

    def test_the_same_layout_changes_nothing(self):
        plans = cl.plan(cl.SALES, card(
            line("deposits", 1, 0.5, "Grow deposits"),
            line("asset_growth_t", 2, 0.5, "Grow by 43% of the Dec book")))
        self.assertEqual(cl.summary(plans)["unchanged"], 2)
        self.assertEqual(cl.summary(plans)["changed"], 0)
        self.assertEqual(plans[0]["removed"], [])

    def test_a_new_weight_is_written_with_its_history(self):
        from .scorecard_automation.models import ScRoleKpiMapping

        plans = cl.plan(cl.SALES, card(
            line("deposits", 1, 0.6, "Grow deposits"),
            line("asset_growth_t", 2, 0.4, "Grow by 43% of the Dec book")))
        self.assertEqual(self.statuses(plans)["deposits"], "changed")
        cl.apply(plans)
        m = ScRoleKpiMapping.objects.get(role_code=ROLE, kpi_code="deposits")
        self.assertAlmostEqual(float(m.kpi_weight), 0.6)
        self.assertTrue(m.history.exists())

    def test_a_stated_rate_moves_the_rate_scored(self):
        """The card must not say 21% and score 43%."""
        from .scorecard_automation.models import ScRoleKpiMapping

        plans = cl.plan(cl.SALES, card(
            line("deposits", 1, 0.5, "Grow deposits"),
            line("asset_growth_t", 2, 0.5, "Grow by 21% of the Dec book")))
        cl.apply(plans)
        m = ScRoleKpiMapping.objects.get(role_code=ROLE,
                                         kpi_code="asset_growth_t")
        self.assertAlmostEqual(float(m.kpi_target), 0.21)
        self.assertEqual(m.kpi_description, "Grow by 21% of the Dec book")

    def test_a_new_line_becomes_a_loadable_kpi(self):
        from .scorecard_automation.models import ScKpi, ScRoleKpiMapping
        from .scorecard_manual import MANUAL_ACTUALS  # noqa: F401
        from .live_scorecard import SOURCES

        plans = cl.plan(cl.SALES, card(
            line("deposits", 1, 0.4, "Grow deposits"),
            line("asset_growth_t", 2, 0.4, "Grow by 43% of the Dec book"),
            line("brand_new_measure", 3, 0.2, "Something the bank adds",
                 feed="")))
        self.assertEqual(self.statuses(plans)["brand_new_measure"], "new_kpi")
        cl.apply(plans)
        self.assertTrue(ScRoleKpiMapping.objects.filter(
            role_code=ROLE, kpi_code="brand_new_measure").exists())
        self.assertTrue(ScKpi.objects.get(
            kpi_code="brand_new_measure").not_configured_reason)
        # Not measured anywhere - so the card offers it for loading.
        self.assertNotIn("brand_new_measure", SOURCES)

    def test_a_dropped_line_is_removed(self):
        from .scorecard_automation.models import ScRoleKpiMapping

        plans = cl.plan(cl.SALES, card(line("deposits", 1, 1.0,
                                            "Grow deposits")))
        self.assertEqual([r["kpi_code"] for r in plans[0]["removed"]],
                         ["asset_growth_t"])
        cl.apply(plans)
        self.assertFalse(ScRoleKpiMapping.objects.filter(
            role_code=ROLE, kpi_code="asset_growth_t").exists())

    def test_a_moved_line_is_found_not_replaced(self):
        plans = cl.plan(cl.SALES, card(
            line("asset_growth_t", 1, 0.5, "Grow by 43% of the Dec book"),
            line("deposits", 2, 0.5, "Grow deposits")))
        self.assertEqual(cl.summary(plans)["changed"], 2)
        self.assertEqual(cl.summary(plans)["new_kpi"], 0)
        self.assertEqual(plans[0]["removed"], [])

    def test_wording_is_compared_without_line_breaks(self):
        self.assertEqual(cl._norm("Financials \n(25%)"),
                         cl._norm("Financials (25%)"))
        self.assertAlmostEqual(cl._stated_rate(
            "Grow by 38% of the Dec book Balance"), 0.38)
        self.assertIsNone(cl._stated_rate("As per assigned target"))
