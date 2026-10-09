"""The back-office (non-sales) cards, as migration 0031 seeds them.

Ten cards for branch operations managers, customer service officers, tellers,
cash tellers and the retail back office, read out of
``2026_BO_Non_Sales_Scorecards - Q2 with_updated_targets.xlsb`` and
cross-checked against ``2026_BO_Actual_Template.xlsx``.

These tests guard the three things that were got wrong while reading it, each
of which would have put a wrong number on somebody's card:

1. the Target column is empty on nine of the ten cards - the figure is in a
   **PM**, per-month, column - so reading only "Target" left 120 of the 132
   lines with no target at all;
2. a KPI keyed on its measure split NPS into two codes over a trailing
   disambiguator and split KYC over a typo on one card, so a KPI is keyed on
   its FEED;
3. a role cannot hold the same KPI twice, and the cash-centre teller card has
   two lines both reading ``Branch_Audit``.
"""

import csv
import pathlib

from django.test import TestCase

from .live_scorecard import FULL_YEAR_TARGETS, SOURCES
from .scorecard_automation.models import ScKpi, ScRole, ScRoleKpiMapping

MAP = (pathlib.Path(__file__).resolve().parents[2]
       / "docs" / "bo-scorecard-kpi-map.csv")

ROLES = {
    "bo_bom", "bo_bom_cso", "bo_cso", "bo_cso_ub", "bo_csm_diaspora",
    "bo_cash_teller", "bo_cash_centre_teller", "bo_teller", "bo_rbo",
    "bo_tl_rbo",
}


class SeededCardsTests(TestCase):
    def test_all_ten_cards_are_there(self):
        seeded = set(ScRole.objects.filter(role_code__startswith="bo_")
                     .values_list("role_code", flat=True))
        self.assertEqual(seeded, ROLES)

    def test_every_cards_weights_sum_to_one(self):
        """The check that the extraction is complete rather than partial. A
        card whose weights sum to 0.92 has had a line silently dropped, and
        every score on it would be understated."""
        for role in sorted(ROLES):
            with self.subTest(role):
                total = sum(
                    float(m.kpi_weight) for m in
                    ScRoleKpiMapping.objects.filter(role_code=role))
                self.assertAlmostEqual(
                    total, 1.0, places=4,
                    msg=f"{role} weights sum to {total}")

    def test_no_role_holds_the_same_kpi_twice(self):
        """The cash-centre teller card has two lines reading Branch_Audit -
        one labelled "Branch Audit", one "Cash Management" - and the unique
        constraint on the mapping table refuses a second. Keying those two on
        the feed alone made the migration fail; the measure is in the code."""
        from collections import Counter

        pairs = Counter(
            ScRoleKpiMapping.objects.filter(role_code__startswith="bo_")
            .values_list("role_code", "kpi_code"))
        self.assertEqual([p for p, n in pairs.items() if n > 1], [])

    def test_one_hundred_and_thirty_two_lines(self):
        self.assertEqual(
            ScRoleKpiMapping.objects.filter(
                role_code__startswith="bo_").count(), 132)

    def test_every_bo_kpi_has_a_source(self):
        """Same invariant the RM cards hold to: nothing reaches a card without
        somebody having decided what it is. Without this a new line falls
        through to a generic "measured elsewhere", which may be a lie and is
        the kind nobody notices because it looks considered."""
        codes = set(ScKpi.objects.filter(kpi_code__startswith="bo_")
                    .values_list("kpi_code", flat=True))
        self.assertTrue(codes)
        self.assertEqual(sorted(codes - set(SOURCES)), [])


class TargetsTests(TestCase):
    """Where each line's target came from, which is the part that was wrong."""

    def test_nearly_every_line_has_a_target(self):
        """120 of 132 had none while the PM column was being ignored."""
        mappings = ScRoleKpiMapping.objects.filter(
            role_code__startswith="bo_")
        without = [f"{m.role_code}/{m.kpi_code}" for m in mappings
                   if m.kpi_target is None]
        self.assertLess(
            len(without), 35,
            f"{len(without)} back-office lines have no target: {without[:12]}")

    def test_a_monthly_target_is_brought_to_a_yearly_figure(self):
        """kpi_target means a YEARLY figure everywhere else in this system, so
        a per-month figure is multiplied on the way in rather than the
        pro-ration being special-cased for these cards.

        The CSO card asks for 100 CRM complaints logged a month, so the year
        is 1,200."""
        crm = ScRoleKpiMapping.objects.get(role_code="bo_cso",
                                           kpi_code="bo_crm")
        self.assertAlmostEqual(crm.kpi_target, 1200.0)

    def test_a_threshold_is_not_multiplied(self):
        """"A net promoter score of 60%" is 60% all year, not 60% a month.
        Multiplying it would make the target 7.2 and score everybody nought."""
        for role in ("bo_cso", "bo_teller", "bo_rbo"):
            with self.subTest(role):
                nps = ScRoleKpiMapping.objects.get(role_code=role,
                                                   kpi_code="bo_nps")
                self.assertAlmostEqual(nps.kpi_target, 0.6)

    def test_a_threshold_is_not_prorated_either(self):
        self.assertIn("bo_nps", FULL_YEAR_TARGETS)
        self.assertIn("bo_operation_lossess", FULL_YEAR_TARGETS)
        self.assertNotIn("bo_crm", FULL_YEAR_TARGETS,
                         "complaints logged accrue; they are not a ceiling")

    def test_a_target_written_as_a_limit_is_read_from_the_ytd_column(self):
        """The BOM card writes loan turnaround as "< 2 Days" and puts the 2 in
        the YTD column. Reading only the prose left the line with no target."""
        tat = ScRoleKpiMapping.objects.get(role_code="bo_bom",
                                           kpi_code="bo_branch_loan_tat")
        self.assertAlmostEqual(tat.kpi_target, 2.0)
        self.assertIn("bo_branch_loan_tat", FULL_YEAR_TARGETS)
        self.assertFalse(SOURCES["bo_branch_loan_tat"].higher_is_better,
                         "fewer days is better")


class WordingTests(TestCase):
    """One feed, several roles, different wording - and before the mapping
    carried its own description, whichever role was seeded first put its
    wording on everybody else's card."""

    def test_the_same_kpi_carries_each_roles_own_words(self):
        casa = {m.role_code: m.kpi_description
                for m in ScRoleKpiMapping.objects.filter(kpi_code="bo_casa")}
        self.assertGreater(len(casa), 1, "CASA is on several cards")
        self.assertGreater(
            len(set(casa.values())), 1,
            "every role shows the same CASA wording, so the per-role "
            "description is not being seeded")

    def test_the_wording_is_not_blank_anywhere(self):
        blank = [f"{m.role_code}/{m.kpi_code}" for m in
                 ScRoleKpiMapping.objects.filter(role_code__startswith="bo_")
                 if not m.kpi_description.strip()]
        self.assertEqual(blank, [])


class ExtractionTests(TestCase):
    """What the CSV says, independently of what was seeded from it."""

    def test_the_map_is_there(self):
        self.assertTrue(MAP.exists(), f"{MAP} is missing")

    def test_the_feed_a_card_names_is_either_real_or_flagged(self):
        """Nine lines name a sheet the actuals template does not have. Those
        are seeded INACTIVE with what the card claims, because the question
        belongs with the desk - but none of them may be silently treated as a
        working feed."""
        with MAP.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 132)

        flagged = {r["actuals_sheet"] for r in rows
                   if "(NOT A SHEET)" in r["actuals_sheet"]}
        self.assertTrue(flagged, "the cross-check against the template is "
                                 "not running")
        for sheet in flagged:
            name = sheet.replace(" (NOT A SHEET)", "")
            code = "bo_" + name.lower().replace("-", "_")
            kpi = ScKpi.objects.filter(kpi_code=code).first()
            if kpi is None:
                continue
            with self.subTest(name):
                self.assertFalse(
                    kpi.is_active,
                    f"{code} names {name}, which the template does not have, "
                    f"but it is seeded active")
                self.assertTrue(kpi.not_configured_reason)
