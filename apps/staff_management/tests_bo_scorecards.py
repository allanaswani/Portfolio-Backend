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
import datetime
import pathlib

from django.test import TestCase
from rest_framework.test import APIClient

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


class BoActualsIdentityTests(TestCase):
    """The back-office template does not use one identifier throughout.

    The same branch manager is ``EKN1329`` on the Active_Customers sheet and
    ``ENGUITHI`` - an AD username - on Account_Opening_PB, Account_Opening_BB
    and Branch_Loan_TAT. A card is keyed on the sales code, so reading the
    column at its word dropped three whole sheets and showed a dash in place
    of figures the branch had already reported.
    """

    CODE = "EKN1329"

    def setUp(self):
        from .models import EmployeeRoleHistory

        # get_or_create: migration 0032 seeds this roster from the sales
        # workbook's own List sheet, so the row may already be there.
        EmployeeRoleHistory.objects.get_or_create(
            sales_code=self.CODE, role_code="bo_bom",
            start_date=datetime.date(2026, 1, 1),
            defaults={"role_status": "active"})

    @staticmethod
    def _row(code, kpi_code, value, sheet, name="Eric Nguithi"):
        return {
            "sheet": sheet, "how": "latest", "kpi_codes": [kpi_code],
            "sales_code": code, "staff_pf": "",
            "staff_name": name, "role": "BOM", "branch": "Kiambu",
            "value": value, "as_at_month": datetime.date(2026, 8, 1),
            "months_with_a_figure": 8,
        }

    def test_a_username_sheet_reaches_the_card_the_sales_code_names(self):
        from . import bo_actuals

        entries, report = bo_actuals.plan([
            self._row(self.CODE, "bo_active_customers", -2.689,
                      "Active_Customers"),
            self._row("ENGUITHI", "bo_account_opening_pb", 0.501,
                      "Account_Opening_PB"),
            self._row("ENGUITHI", "bo_branch_loan_tat", 3.355,
                      "Branch_Loan_TAT"),
        ])
        # Every figure lands under the SALES code, not the username.
        self.assertEqual({e["sales_code"] for e in entries}, {self.CODE})
        self.assertEqual(
            {(e["kpi_code"], e["value"]) for e in entries},
            {("bo_active_customers", -2.689),
             ("bo_account_opening_pb", 0.501),
             ("bo_branch_loan_tat", 3.355)})
        # And the two that stood in on the name are declared, so a load never
        # silently re-attributes somebody's figures.
        self.assertEqual(report["by_name_in_workbook"], 2)
        self.assertEqual(report["no_person"], [])

    def test_branch_loan_tat_is_written_though_the_platform_measures_it(self):
        """``tat_days`` reads iApply on the person's own seller code, which a
        branch manager does not sell under. The source is live, answers
        nothing for them, and the figure is on the template's own sheet."""
        from . import bo_actuals

        entries, report = bo_actuals.plan([
            self._row(self.CODE, "bo_branch_loan_tat", 3.355,
                      "Branch_Loan_TAT"),
        ])
        self.assertEqual([(e["kpi_code"], e["value"]) for e in entries],
                         [("bo_branch_loan_tat", 3.355)])
        self.assertEqual(report["behind_a_live_source"], 1)

    def test_an_unknown_name_is_reported_rather_than_guessed(self):
        from . import bo_actuals

        entries, report = bo_actuals.plan([
            self._row("ZZTHOMPSON", "bo_account_opening_pb", 1.0,
                      "Account_Opening_PB", name="Someone Entirely Else"),
        ])
        self.assertEqual(entries, [])
        self.assertEqual(len(report["no_person"]), 1)

    def test_one_name_lending_two_codes_is_refused(self):
        """Two people spelt the same way lend nothing. Guessing would post a
        branch's figures to a stranger."""
        from . import bo_actuals
        from .models import EmployeeRoleHistory

        EmployeeRoleHistory.objects.get_or_create(
            sales_code="EKN9999", role_code="bo_cso",
            start_date=datetime.date(2026, 1, 1),
            defaults={"role_status": "active"})
        entries, report = bo_actuals.plan([
            self._row(self.CODE, "bo_active_customers", 1.0,
                      "Active_Customers"),
            self._row("EKN9999", "bo_active_customers", 2.0,
                      "Active_Customers"),
            self._row("ENGUITHI", "bo_account_opening_pb", 3.0,
                      "Account_Opening_PB"),
        ])
        wrote = {(e["sales_code"], e["kpi_code"]) for e in entries}
        self.assertNotIn(("EKN1329", "bo_account_opening_pb"), wrote)
        self.assertNotIn(("EKN9999", "bo_account_opening_pb"), wrote)
        self.assertEqual(report["by_name_in_workbook"], 0)


# ── Reaching your own card ───────────────────────────────────────────────────
#
# The cards above were seeded, the holders were seeded with them by 0032, and
# not one of those 101 people could open theirs. ``my-card/`` resolved the
# caller by ``Profile.sales_code`` alone - the one identifier that is set for
# people who carry a sales book and for nobody else. Every Team Leader, BOM,
# CSO and teller got "your profile has no sales code" on a card that existed,
# was configured, and had their name on it.
#
# So these pin the two halves of the fix: a person is found by any identifier
# the estate actually holds for them, and - far more important - a person is
# NEVER found by an identifier that could belong to somebody else. Showing
# somebody the wrong scorecard is worse than showing them none.

class ReachingYourOwnCardTests(TestCase):
    """``resolve_sales_code_for_user`` - who the person signed in is."""

    def setUp(self):
        from django.contrib.auth.models import User

        from .models import EmployeeRoleHistory, StaffEmployeeData

        self.User = User
        self.StaffEmployeeData = StaffEmployeeData
        self.EmployeeRoleHistory = EmployeeRoleHistory

        # A real back-office team leader, shaped like migration 0032 seeds one.
        EmployeeRoleHistory.objects.create(
            sales_code="PKM1180", role_code="bo_tl_rbo",
            start_date=datetime.date(2026, 1, 1),
            notes="Peter Kimani | Head Office | Zone A | Jane Boss")
        StaffEmployeeData.objects.create(
            staff_pf_number=1180, staff_name="Peter Kimani",
            staff_email="peter.kimani@hfgroup.co.ke", sales_code="PKM1180",
            department="Retail", staff_unit="Head Office",
            staff_org_unit="Head Office", job_title="TL RBO",
            employment_date=datetime.date(2020, 1, 1),
            employee_category="back_office")

    def user(self, **kwargs):
        kwargs.setdefault("username", "someone")
        kwargs.setdefault("password", "x")
        return self.User.objects.create_user(**kwargs)

    def resolve(self, user, profile=None):
        from .live_scorecard import resolve_sales_code_for_user
        return resolve_sales_code_for_user(user, profile)

    # ── the identifiers that should work ─────────────────────────────────────

    def test_the_profile_still_wins(self):
        """An explicitly set sales code is a deliberate statement about who
        somebody is and must not be second-guessed."""
        from apps.portfolio.models import Profile

        user = self.user(username="unrelated.name")
        profile = Profile.objects.filter(user=user).first()
        profile.sales_code = "SC999"
        profile.save()
        self.assertEqual(self.resolve(user, profile), ("SC999", "your profile"))

    def test_a_team_leader_is_found_by_their_work_email(self):
        """The case the whole change exists for: no sales code on the profile,
        a card seeded under a back-office code, and an e-mail that matches."""
        user = self.user(username="peter.kimani",
                         email="peter.kimani@hfgroup.co.ke")
        code, how = self.resolve(user, None)
        self.assertEqual(code, "PKM1180")
        self.assertIn("e-mail", how)

    def test_a_sign_in_name_matching_the_roster_code_is_enough(self):
        user = self.user(username="PKM1180")
        self.assertEqual(self.resolve(user, None),
                         ("PKM1180", "the back-office roster"))

    def test_a_sign_in_name_is_tried_against_the_roster_email(self):
        """An account created without an e-mail on it. AD names are
        firstname.lastname and the address is the same at the bank's domain."""
        user = self.user(username="peter.kimani", email="")
        code, _how = self.resolve(user, None)
        self.assertEqual(code, "PKM1180")

    def test_a_numeric_sign_in_name_is_read_as_a_pf_number(self):
        user = self.user(username="1180")
        code, how = self.resolve(user, None)
        self.assertEqual(code, "PKM1180")
        self.assertIn("PF number", how)

    def test_a_name_match_is_the_last_resort(self):
        user = self.user(username="pk.temp", first_name="Peter",
                         last_name="Kimani")
        code, how = self.resolve(user, None)
        self.assertEqual(code, "PKM1180")
        self.assertIn("name", how)

    # ── and the ones that must NOT ───────────────────────────────────────────

    def test_a_shared_name_resolves_to_nobody(self):
        """Two people called Peter Kimani. Picking one would show a real
        person somebody else's performance."""
        self.StaffEmployeeData.objects.create(
            staff_pf_number=2244, staff_name="Peter Kimani",
            staff_email="peter.kimani2@hfgroup.co.ke", sales_code="PKM2244",
            department="Retail", staff_unit="Thika", staff_org_unit="Thika",
            job_title="Teller", employment_date=datetime.date(2021, 1, 1),
            employee_category="back_office")
        user = self.user(username="pk.temp", first_name="Peter",
                         last_name="Kimani")
        self.assertEqual(self.resolve(user, None), ("", ""))

    def test_a_stranger_resolves_to_nobody(self):
        user = self.user(username="nobody.here", email="nobody@hfgroup.co.ke",
                         first_name="No", last_name="Body")
        self.assertEqual(self.resolve(user, None), ("", ""))

    def test_a_blank_profile_code_does_not_short_circuit_the_rest(self):
        from apps.portfolio.models import Profile

        user = self.user(username="peter.kimani",
                         email="peter.kimani@hfgroup.co.ke")
        profile = Profile.objects.filter(user=user).first()
        profile.sales_code = "   "
        profile.save()
        code, _how = self.resolve(user, profile)
        self.assertEqual(code, "PKM1180")

    def test_a_partial_name_is_not_a_match(self):
        """Nothing here matches on a fragment."""
        user = self.user(username="pk.temp", first_name="Peter",
                         last_name="Kim")
        self.assertEqual(self.resolve(user, None), ("", ""))


class MyCardEndpointTests(TestCase):
    """``my-card/`` end to end for somebody with no sales code on file."""

    URL = "/staff_management/scorecard-automation/my-card/"

    def setUp(self):
        from django.contrib.auth.models import User

        from .models import EmployeeRoleHistory, StaffEmployeeData

        EmployeeRoleHistory.objects.create(
            sales_code="PKM1180", role_code="bo_tl_rbo",
            start_date=datetime.date(2026, 1, 1),
            notes="Peter Kimani | Head Office | Zone A | Jane Boss")
        StaffEmployeeData.objects.create(
            staff_pf_number=1180, staff_name="Peter Kimani",
            staff_email="peter.kimani@hfgroup.co.ke", sales_code="PKM1180",
            department="Retail", staff_unit="Head Office",
            staff_org_unit="Head Office", job_title="TL RBO",
            employment_date=datetime.date(2020, 1, 1),
            employee_category="back_office")
        self.tl = User.objects.create_user(
            "peter.kimani", password="x", email="peter.kimani@hfgroup.co.ke")
        self.client = APIClient()
        self.client.force_authenticate(self.tl)

    def test_a_team_leader_gets_a_card_rather_than_no_sales_code(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200, response.content)
        # The card itself may or may not compute in a test database, but the
        # one answer that must never come back is the one that sent every
        # back-office card holder to the wrong place.
        self.assertNotEqual(response.data.get("reason"), "no_sales_code")
        self.assertEqual(response.data.get("sales_code", "PKM1180"), "PKM1180")

    def test_somebody_nothing_identifies_is_told_what_was_tried(self):
        from django.contrib.auth.models import User

        stranger = User.objects.create_user("nobody.here", password="x")
        client = APIClient()
        client.force_authenticate(stranger)
        response = client.get(self.URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data["has_card"])
        self.assertEqual(response.data["reason"], "not_identified")
        self.assertIn("tried", response.data)
        self.assertIn("your profile", response.data["tried"])

    def test_the_card_is_never_taken_from_the_request(self):
        """There is no sales_code parameter, so there is none to forget to
        check. Passing one must change nothing."""
        mine = self.client.get(self.URL).data
        theirs = self.client.get(self.URL + "?sales_code=SOMEONEELSE").data
        self.assertEqual(mine.get("sales_code"), theirs.get("sales_code"))
