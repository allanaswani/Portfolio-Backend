"""Somewhere to look at the cards, the rosters, and one person's card.

The cards were seeded and then existed only in the database. These are the
three endpoints behind Administration → Scorecards → Cards & rosters, and the
things worth guarding are:

* a teller resolves to a back-office card off a roster that is NOT the sales
  one, because that is the whole reason the back-office cards could not be
  seen;
* the coverage split tells "nobody has loaded this yet" apart from "nobody can
  ever load this", since those go to different people;
* only an administrator can open somebody else's card, and ``my-card/``
  remains the only route to your own.
"""

import datetime

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from .live_scorecard import bo_role_for, build_card, resolve_person
from .models import BranchEmployeeDmcData, EmployeeRoleHistory, StaffEmployeeData

BASE = "/staff_management/scorecard-automation/"


class BackOfficeRosterTests(TestCase):
    """A teller is on no sales roster. Until the role history was read, that
    meant ten seeded cards nobody could reach."""

    def test_the_seeded_roster_resolves_a_branch_operations_manager(self):
        person = resolve_person("EKN1329")
        self.assertIsNotNone(person, "the List sheet was not seeded")
        self.assertEqual(person.role_code, "bo_bom")
        self.assertEqual(person.roster, "the back-office roster")
        self.assertIn("Eric", person.name)

    def test_a_teller_gets_the_teller_card(self):
        held = EmployeeRoleHistory.objects.filter(role_code="bo_teller").first()
        self.assertIsNotNone(held, "no tellers were seeded")
        person = resolve_person(held.sales_code)
        self.assertEqual(person.role_code, "bo_teller")

    def test_the_sales_roster_still_wins_for_an_rm(self):
        """Order matters: the DMC roster is tried first because it brings the
        targets with it."""
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4191, staff_name="Juspher Muriithi",
            sales_code="JM4191", staff_role="COMMERCIAL RM",
            staff_branch="Rehani", active=1, target_deposits_value=1)
        person = resolve_person("JM4191")
        self.assertEqual(person.role_code, "commercial_rm")
        self.assertEqual(person.roster, "the branch DMC roster")
        self.assertIsNotNone(person.dmc_row)

    def test_an_hr_job_title_is_the_fallback(self):
        """For somebody who joined since the roster was loaded."""
        StaffEmployeeData.objects.create(
            staff_pf_number=9999, staff_name="New Joiner",
            sales_code="NJ9999", job_title="Customer Service Officer",
            staff_unit="Nyeri", is_active=True,
            employment_date=datetime.date(2026, 9, 1))
        person = resolve_person("NJ9999")
        self.assertEqual(person.role_code, "bo_cso")
        self.assertEqual(person.roster, "your HR record")

    def test_an_unknown_job_title_is_not_guessed_at(self):
        for title in ("Security Guard", "Driver", "", None, "Head of Nothing"):
            with self.subTest(repr(title)):
                self.assertIsNone(bo_role_for(title))

    def test_nobody_at_all_is_told_which_problem_it_is(self):
        self.assertIsNone(resolve_person("NOBODY1"))
        card = build_card("NOBODY1")
        self.assertFalse(card["has_card"])
        self.assertEqual(card["reason"], "not_on_any_roster")

    def test_a_back_office_card_actually_builds(self):
        """The point of all of it. No DMC row, so every target comes off the
        role's card - which is where the back-office targets live."""
        card = build_card("EKN1329")
        self.assertTrue(card["has_card"], card)
        self.assertEqual(card["staff"]["role_code"], "bo_bom")
        self.assertEqual(card["staff"]["roster"], "the back-office roster")
        self.assertTrue(card["perspectives"])

        lines = [ln for g in card["perspectives"] for ln in g["lines"]]
        self.assertEqual(len(lines), 15, "the BOM card has 15 lines")
        scored = [ln for ln in lines if ln["ytd_target"] is not None]
        self.assertTrue(scored, "no line on the BOM card has a target")

    def test_the_nps_target_on_a_back_office_card_is_not_prorated(self):
        card = build_card("EKN1329")
        lines = {ln["kpi_code"]: ln
                 for g in card["perspectives"] for ln in g["lines"]}
        nps = lines["bo_nps"]
        self.assertAlmostEqual(nps["annual_target"], 0.6)
        self.assertAlmostEqual(nps["ytd_target"], 0.6)
        self.assertTrue(nps["full_year_target"])


class CatalogueEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", password="x",
                                              is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

        self.nosy = User.objects.create_user("nosy", password="x")
        Profile.objects.update_or_create(
            user=self.nosy, defaults={"sales_code": "EKN1329"})
        self.other = APIClient()
        self.other.force_authenticate(self.nosy)

    # ── who may ──────────────────────────────────────────────────────────
    def test_an_ordinary_user_cannot_see_everybodys_cards(self):
        for path in ("cards/", "roster/", "card-for/?sales_code=EKN1329"):
            with self.subTest(path):
                self.assertEqual(
                    self.other.get(BASE + path).status_code, 403)

    def test_an_administration_group_may(self):
        member = User.objects.create_user("admgrp", password="x")
        member.groups.add(Group.objects.create(name="staff_mgt"))
        client = APIClient()
        client.force_authenticate(member)
        self.assertEqual(client.get(BASE + "cards/").status_code, 200)

    # ── the cards ────────────────────────────────────────────────────────
    def test_every_configured_card_is_listed_with_its_family(self):
        response = self.client.get(BASE + "cards/")
        self.assertEqual(response.status_code, 200, response.content)
        families = {c["role_code"]: c["family"] for c in response.data["cards"]}
        self.assertEqual(families["bo_bom"], "back office")
        self.assertEqual(families["sme_rm"], "sales")
        self.assertEqual(response.data["totals"]["back_office"], 10)

    def test_a_cards_weights_are_reported_so_a_dropped_line_shows(self):
        """The back-office cards sum to exactly 1.000. The sales cards sum to
        1.025, because they carry a Bonus Points perspective worth 2.5% ON TOP
        of the hundred - which is the card's own design and not a fault, so the
        screen reports the figure rather than asserting it is one."""
        response = self.client.get(BASE + "cards/")
        for card in response.data["cards"]:
            with self.subTest(card["role_code"]):
                if card["family"] == "back office":
                    self.assertAlmostEqual(card["total_weight"], 1.0, places=3)
                else:
                    self.assertGreaterEqual(card["total_weight"], 1.0)
                    self.assertLessEqual(card["total_weight"], 1.05)

    def test_one_card_comes_back_with_its_lines(self):
        response = self.client.get(BASE + "cards/?role_code=bo_teller")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.data["kpis"]), 12)
        line = response.data["kpis"][0]
        for key in ("kpi_name", "perspective", "weight", "target", "feed",
                    "coverage", "measure_of_success"):
            self.assertIn(key, line)

    def test_coverage_tells_loadable_apart_from_stranded(self):
        """"Pending" lumps together a figure nobody has loaded yet with one
        nobody can ever load, and those go to different people."""
        response = self.client.get(BASE + "cards/?role_code=bo_bom")
        states = {line["kpi_code"]: line["coverage"]
                  for line in response.data["kpis"]}
        self.assertEqual(states["bo_pl_charge"], "measured")
        self.assertEqual(states["bo_nps"], "loadable")
        self.assertNotIn("stranded", set(states.values()),
                         "nothing on the BOM card should be stranded now")

    def test_an_unknown_card_is_a_404_not_an_empty_page(self):
        self.assertEqual(
            self.client.get(BASE + "cards/?role_code=nope").status_code, 404)

    def test_cards_nobody_holds_are_named(self):
        """bo_cash_teller and bo_bom_cso have nobody on the workbook's own
        List sheet. Putting somebody on them would have been a guess."""
        response = self.client.get(BASE + "cards/")
        orphans = {c["role_code"] for c in response.data["without_holders"]}
        self.assertIn("bo_cash_teller", orphans)
        self.assertIn("bo_bom_cso", orphans)

    # ── the roster ───────────────────────────────────────────────────────
    def test_the_roster_covers_both_families(self):
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=4236, staff_name="Charles Muchiri",
            sales_code="CMM4236", staff_role="SME RM", staff_branch="Rehani",
            active=1)
        response = self.client.get(BASE + "roster/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["by_family"]["back_office"], 101)
        self.assertGreaterEqual(response.data["by_family"]["sales"], 1)

    def test_each_roster_row_says_which_list_it_came_off(self):
        response = self.client.get(BASE + "roster/?role_code=bo_bom")
        rosters = {row["roster"] for row in response.data["rows"]}
        self.assertEqual(rosters, {"employee_role_history"})

    def test_the_roster_can_be_searched(self):
        response = self.client.get(BASE + "roster/?search=eric")
        self.assertTrue(response.data["rows"])
        self.assertTrue(all("eric" in row["staff_name"].lower()
                            or "eric" in row["sales_code"].lower()
                            or "eric" in (row["branch"] or "").lower()
                            for row in response.data["rows"]))

    # ── one person's card ────────────────────────────────────────────────
    def test_an_administrator_can_open_a_back_office_card(self):
        response = self.client.get(BASE + "card-for/?sales_code=EKN1329")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["has_card"], response.data)
        self.assertEqual(response.data["staff"]["role_code"], "bo_bom")

    def test_a_missing_sales_code_is_refused(self):
        self.assertEqual(
            self.client.get(BASE + "card-for/").status_code, 400)

    def test_an_unknown_code_reports_rather_than_failing(self):
        response = self.client.get(BASE + "card-for/?sales_code=ZZ0000")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["has_card"])
        self.assertEqual(response.data["reason"], "not_on_any_roster")


class LoadableFiguresCoverTheBackOfficeTests(TestCase):
    """The Figures to load screen has to list back-office staff too, or 101
    people have figures nobody can load."""

    def setUp(self):
        self.admin = User.objects.create_user("adm2", password="x",
                                              is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_back_office_people_are_on_the_list(self):
        response = self.client.get(BASE + "manual-figures/")
        self.assertEqual(response.status_code, 200, response.content)
        codes = {row["sales_code"] for row in response.data["rows"]}
        self.assertIn("EKN1329", codes)

    def test_a_back_office_figure_can_be_loaded_and_reaches_the_card(self):
        from .scorecard_manual import _default_month

        response = self.client.post(
            BASE + "manual-figures/entry/",
            {"sales_code": "EKN1329", "kpi_code": "bo_nps", "actual": 0.72},
            format="json")
        self.assertEqual(response.status_code, 200, response.content)

        card = build_card("EKN1329")
        nps = {ln["kpi_code"]: ln
               for g in card["perspectives"] for ln in g["lines"]}["bo_nps"]
        self.assertAlmostEqual(nps["ytd_actual"], 0.72)
        self.assertAlmostEqual(nps["score"], 1.2, msg="0.72 beats a 0.6 floor")
        self.assertIn("loaded by Administration", nps["as_at"])
