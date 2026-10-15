"""Internal Audit's branch return, and the nine card lines it feeds.

Written against the table Internal Audit actually send — eight branches, a
score and an implementation rate, pasted in as it came:

    Branch     Score   Implimentation
    Eldoret    1.65    93%
    Rehani     1.72    82%
    ...

The spelling "Implimentation" is theirs. A reader that only accepts the
correct spelling rejects the real file, so it is matched as written.
"""

import datetime
import io

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from . import audit_returns as ar
from .live_scorecard import build_card, score_for
from .models import (
    BranchEmployeeDmcData, EmployeeRoleHistory, ScAuditReturn,
)

PASTED = """Branch\tScore\tImplimentation
Eldoret\t1.65\t93%
Rehani\t1.72\t82%
Embu\t1.65\t80%
Mombasa\t1.67\t81%
Nyeri\t1.62\t92%
Harambee\t1.7\t92%
Komarock\t1.66\t83%
Thika\t1.74\t80%
"""


class ReadingTheTableTests(TestCase):
    def test_the_table_reads_exactly_as_internal_audit_send_it(self):
        rows, report = ar.read_pasted(PASTED)
        self.assertEqual(len(rows), 8)
        self.assertEqual(report["ignored_values"], [])
        by_branch = {r["branch"]: r for r in rows}
        self.assertAlmostEqual(by_branch["Eldoret"]["audit_score"], 1.65)
        self.assertAlmostEqual(by_branch["Eldoret"]["implementation"], 0.93)
        self.assertAlmostEqual(by_branch["Thika"]["audit_score"], 1.74)
        self.assertAlmostEqual(by_branch["Thika"]["implementation"], 0.80)

    def test_their_spelling_of_implimentation_is_accepted(self):
        """It is a typo in the real file. Insisting on the correct spelling
        would reject the only table anyone actually sends."""
        rows, _ = ar.read_pasted(
            "Branch\tScore\tImplimentation\nEldoret\t1.65\t93%")
        self.assertAlmostEqual(rows[0]["implementation"], 0.93)
        rows, _ = ar.read_pasted(
            "Branch\tScore\tImplementation\nEldoret\t1.65\t93%")
        self.assertAlmostEqual(rows[0]["implementation"], 0.93)

    def test_ninety_three_and_nought_point_nine_three_mean_the_same(self):
        """93 scored against a target of 0.85 reads as 9,300%."""
        for written in ("93%", "93", 0.93, 93):
            with self.subTest(repr(written)):
                self.assertAlmostEqual(ar._rate(written), 0.93)

    def test_commas_and_runs_of_spaces_work_too(self):
        """What arrives is whatever the person's clipboard produced."""
        for text in ("Branch,Score,Implimentation\nEldoret,1.65,93%",
                     "Branch   Score   Implimentation\nEldoret   1.65   93%"):
            with self.subTest(text[:20]):
                rows, _ = ar.read_pasted(text)
                self.assertEqual(len(rows), 1)
                self.assertAlmostEqual(rows[0]["audit_score"], 1.65)

    def test_a_body_with_no_header_is_read_in_order_and_says_so(self):
        """Pasting the rows without the header line is the likeliest way to
        get here. Reading positionally is a guess, so the report admits it."""
        rows, report = ar.read_pasted("Eldoret\t1.65\t93%\nRehani\t1.72\t82%")
        self.assertEqual(len(rows), 2)
        self.assertTrue(report["columns"].get("read_positionally"))

    def test_a_total_row_is_not_a_branch(self):
        rows, report = ar.read_pasted(
            PASTED + "Grand Total\t1.68\t85%\n")
        self.assertEqual(len(rows), 8)
        self.assertTrue(report["skipped_rows"])

    def test_a_csv_file_reads_the_same_way(self):
        stream = io.BytesIO(
            b"Branch,Score,Implimentation\nEldoret,1.65,93%\n")
        rows, _ = ar.read_workbook(stream, "audit.csv")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["implementation"], 0.93)

    def test_a_cell_that_is_not_a_number_is_reported(self):
        rows, report = ar.read_pasted(
            "Branch\tScore\tImplimentation\nEldoret\tpending\t93%")
        self.assertIsNone(rows[0]["audit_score"])
        self.assertEqual(
            [i["column"] for i in report["ignored_values"]], ["score"])


class MatchingABranchTests(TestCase):
    """One row serves every person in the branch, so a mismatch does not cost
    one card - it costs a whole branch. Hence exact, or a UNIQUE prefix, and
    never a loose match."""

    ROSTER = {"ELDORET", "HARAMBEEAVE", "THIKA", "THIKAROADMALLTRM",
              "KOMAROCK", "KITENGELA"}

    def test_the_branch_word_and_case_do_not_matter(self):
        for written in ("Eldoret", "ELDORET BRANCH", "eldoret br",
                        " Eldoret  Branch "):
            with self.subTest(written):
                self.assertEqual(ar.fold_branch(written), "ELDORET")

    def test_a_shorter_name_finds_its_branch_by_unique_prefix(self):
        """Internal Audit write "Harambee"; the roster says "HARAMBEE AVE
        BRANCH". Nothing else begins with HARAMBEE, so there is one possible
        answer."""
        self.assertEqual(
            ar.match_key(ar.fold_branch("Harambee"), self.ROSTER),
            ("HARAMBEEAVE", "prefix"))

    def test_thika_does_not_take_thika_road_malls_score(self):
        """The reason the prefix rung is second and not first. THIKA is a
        prefix of both THIKA and THIKAROADMALLTRM, and they are different
        branches."""
        self.assertEqual(
            ar.match_key(ar.fold_branch("Thika"), self.ROSTER),
            ("THIKA", "exact"))

    def test_an_ambiguous_name_is_reported_not_guessed(self):
        """Two candidates and no exact match. Handing a branch somebody
        else's audit score is worse than handing it none."""
        self.assertEqual(
            ar.match_key("NAIROBI", {"NAIROBICBD", "NAIROBIWEST"}), ("", ""))

    def test_a_name_nothing_matches_is_reported(self):
        self.assertEqual(ar.match_key("ATLANTIS", self.ROSTER), ("", ""))


class SavingTests(TestCase):
    def rows(self, score=1.65, rate=0.93, branch="Eldoret"):
        return [{"branch": branch, "branch_key": ar.fold_branch(branch),
                 "audit_score": score, "implementation": rate}]

    def test_a_second_load_corrects_rather_than_duplicating(self):
        ar.save(self.rows(), "2026", who="audit")
        ar.save(self.rows(score=1.60), "2026", who="audit")
        self.assertEqual(ScAuditReturn.objects.count(), 1)
        self.assertAlmostEqual(ScAuditReturn.objects.get().audit_score, 1.60)

    def test_a_branch_the_new_return_omits_is_left_alone(self):
        """Internal Audit send a correction for one branch. Clearing the rest
        would blank the audit line for everybody else in the bank."""
        ar.save(self.rows(branch="Eldoret") + self.rows(branch="Embu"),
                "2026", who="audit")
        ar.save(self.rows(branch="Eldoret", score=1.60), "2026", who="audit")
        self.assertEqual(ScAuditReturn.objects.count(), 2)
        self.assertAlmostEqual(
            ScAuditReturn.objects.get(branch="Embu").audit_score, 1.65)

    def test_the_same_branch_spelt_two_ways_is_one_row(self):
        """Keyed on the folded name, so "Eldoret" and "ELDORET BRANCH" cannot
        both exist and be read by whichever came first."""
        ar.save(self.rows(branch="Eldoret"), "2026", who="audit")
        ar.save(self.rows(branch="ELDORET BRANCH", score=1.60), "2026",
                who="audit")
        self.assertEqual(ScAuditReturn.objects.count(), 1)


class WhatTheCardReadsTests(TestCase):
    """Antony Siajabu's branch operations manager card: three audit lines,
    21% of the card between them, all unscored before this."""

    CODE = "ASI3192"

    def setUp(self):
        # No fixture needed: ASI3192 is one of the 101 people migration 0032
        # seeded into the back-office roster, Kitengela and all. Creating him
        # again trips unique_role_start_per_employee, which is the roster
        # doing its job.
        self.assertTrue(
            EmployeeRoleHistory.objects.filter(
                sales_code__iexact=self.CODE, role_code="bo_bom").exists(),
            "the seeded back-office roster should already hold ASI3192")

    def lines(self):
        card = build_card(self.CODE)
        self.assertTrue(card["has_card"], card)
        return {line["kpi_code"]: line
                for group in card["perspectives"] for line in group["lines"]}

    def load(self, score=1.60, rate=0.93, branch="Kitengela"):
        ar.save([{"branch": branch, "branch_key": ar.fold_branch(branch),
                  "audit_score": score, "implementation": rate}],
                "2026", who="audit")

    def test_without_a_return_the_card_names_the_screen(self):
        line = self.lines()["bo_branch_audit_branch_audit"]
        self.assertIsNone(line["score"])
        self.assertIn("Audit returns", line["pending"])

    def test_the_target_is_the_one_its_own_description_states(self):
        """It was seeded at 1.0 where the measure of success says 1.65, and
        because the score is lower-is-better that mis-scored a branch meeting
        the real target as a 65% overshoot."""
        line = self.lines()["bo_branch_audit_branch_audit"]
        self.assertAlmostEqual(line["annual_target"], 1.65)
        self.assertIn("1.65", line["measure_of_success"])

    def test_the_score_is_lower_is_better(self):
        """1.60 beats a target of 1.65. Read the other way round, the
        branches with the worst audits would come top."""
        self.load(score=1.60)
        line = self.lines()["bo_branch_audit_branch_audit"]
        self.assertFalse(line["higher_is_better"])
        self.assertAlmostEqual(line["ytd_actual"], 1.60)
        self.assertAlmostEqual(line["score"], 1.0)

    def test_a_miss_is_a_near_miss_and_not_a_nought(self):
        """Scored in proportion rather than pass/fail: 1.70 against 1.65 is
        97%, which is what it is."""
        self.load(score=1.70)
        line = self.lines()["bo_branch_audit_branch_audit"]
        self.assertAlmostEqual(line["score"], 1.65 / 1.70, places=4)

    def test_beating_the_grade_does_not_pay_a_bonus(self):
        """A graded control score is not a sales target."""
        self.load(score=1.0)
        line = self.lines()["bo_branch_audit_branch_audit"]
        self.assertAlmostEqual(line["score"], 1.0)
        self.assertAlmostEqual(line["score_cap"], 1.0)

    def test_implementation_feeds_its_own_line_and_the_other_way_up(self):
        self.load(rate=0.93)
        line = self.lines()["bo_branch_audit_resolution"]
        self.assertTrue(line["higher_is_better"])
        self.assertAlmostEqual(line["ytd_actual"], 0.93)
        self.assertAlmostEqual(line["ytd_target"], 0.85)
        self.assertAlmostEqual(line["score"], 0.93 / 0.85, places=4)

    def test_the_compliance_line_is_not_in_this_return(self):
        """Loading the return must not make the compliance line look answered
        - it is a different figure that is not in the table."""
        self.load()
        line = self.lines()["bo_branch_audit_compliance"]
        self.assertIsNone(line["score"])
        self.assertIn("Figures to load", line["pending"])

    def test_a_branch_the_return_misses_is_told_so(self):
        self.load(branch="Eldoret")
        line = self.lines()["bo_branch_audit_branch_audit"]
        self.assertIsNone(line["score"])
        self.assertIn("Kitengela", line["pending"])
        self.assertIn("spelt differently", line["pending"])

    def test_the_diaspora_card_reproduces_its_stated_score(self):
        """The one calibration point this line has: an actual of 1.6337
        against a target of 1.65 scores 1.0 on the Diaspora card."""
        self.assertAlmostEqual(
            score_for(1.633636363636363, 1.65, False, cap=1.0), 1.0)


class TheScreenTests(TestCase):
    BASE = "/staff_management/scorecard-automation/audit/"

    def setUp(self):
        self.client = APIClient()
        self.auditor = User.objects.create_user("aud", password="x")
        self.auditor.groups.add(Group.objects.create(name="audit"))
        self.rm = User.objects.create_user("rm1", password="x")
        Profile.objects.update_or_create(
            user=self.rm, defaults={"sales_code": "ASI3192"})
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=1, staff_name="Somebody", sales_code="S1",
            staff_role="SME RM", staff_branch="Eldoret", staff_unit="Eldoret",
            active=1)

    def test_anyone_signed_in_may_see_the_figures_they_are_scored_on(self):
        self.client.force_authenticate(self.rm)
        response = self.client.get(self.BASE)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["may_edit"])
        self.assertIn("compliance", response.data["not_covered"])

    def test_an_rm_may_not_file_an_audit_figure(self):
        self.client.force_authenticate(self.rm)
        response = self.client.post(
            self.BASE + "upload/", {"pasted": PASTED, "apply": "true"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ScAuditReturn.objects.count(), 0)

    def test_is_staff_alone_does_not_open_it(self):
        staffer = User.objects.create_user("s1", password="x", is_staff=True)
        self.client.force_authenticate(staffer)
        response = self.client.post(
            self.BASE + "upload/", {"pasted": PASTED})
        self.assertEqual(response.status_code, 403)

    def test_a_paste_reports_before_it_writes(self):
        self.client.force_authenticate(self.auditor)
        response = self.client.post(self.BASE + "upload/", {"pasted": PASTED})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["applied"])
        self.assertEqual(ScAuditReturn.objects.count(), 0)
        self.assertEqual(response.data["report"]["branches"], 8)

    def test_the_second_call_writes(self):
        self.client.force_authenticate(self.auditor)
        response = self.client.post(
            self.BASE + "upload/", {"pasted": PASTED, "apply": "true"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ScAuditReturn.objects.count(), 8)
        self.assertEqual(response.data["written"], 8)

    def test_the_report_names_the_branches_that_reach_nobody(self):
        """Seven of the eight branches are not on this test's roster, and
        that is the thing worth saying out loud."""
        self.client.force_authenticate(self.auditor)
        response = self.client.post(self.BASE + "upload/", {"pasted": PASTED})
        unmatched = response.data["report"]["unmatched"]
        self.assertIn("Thika", unmatched)
        self.assertNotIn("Eldoret", unmatched)

    def test_the_period_defaults_to_this_year(self):
        """The audit score is annual - its own target says so."""
        import datetime

        self.client.force_authenticate(self.auditor)
        response = self.client.post(
            self.BASE + "upload/", {"pasted": PASTED, "apply": "true"})
        self.assertEqual(response.data["report"]["period"],
                         str(datetime.date.today().year))

    def test_one_branch_can_be_corrected_on_its_own(self):
        self.client.force_authenticate(self.auditor)
        response = self.client.post(
            self.BASE + "entry/",
            {"branch": "Eldoret", "audit_score": 1.55,
             "implementation": "95%"})
        self.assertEqual(response.status_code, 201, response.data)
        row = ScAuditReturn.objects.get()
        self.assertAlmostEqual(row.audit_score, 1.55)
        self.assertAlmostEqual(row.implementation, 0.95)
        self.assertTrue(response.data["row"]["matched"])

    def test_a_branch_nobody_has_is_saved_and_said_out_loud(self):
        self.client.force_authenticate(self.auditor)
        response = self.client.post(
            self.BASE + "entry/", {"branch": "Atlantis", "audit_score": 1.6})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data["row"]["matched"])
        self.assertIn("reaches nobody", response.data["detail"])

    def test_a_score_outside_a_grade_is_refused(self):
        self.client.force_authenticate(self.auditor)
        for value in (0, 7, "many"):
            with self.subTest(value):
                response = self.client.post(
                    self.BASE + "entry/",
                    {"branch": "Eldoret", "audit_score": value})
                self.assertEqual(response.status_code, 400)

    def test_coverage_names_the_branches_with_no_return(self):
        """The direction that matters more: a branch full of staff the return
        does not mention has no audit score for anybody in it."""
        self.client.force_authenticate(self.auditor)
        BranchEmployeeDmcData.objects.create(
            staff_pf_number=2, staff_name="Another", sales_code="S2",
            staff_role="SME RM", staff_branch="Nanyuki", staff_unit="Nanyuki",
            active=1)
        self.client.post(self.BASE + "upload/",
                         {"pasted": PASTED, "apply": "true"})
        found = self.client.get(self.BASE).data["coverage"]
        self.assertIn("Nanyuki", found["roster_without_a_return"])
        self.assertNotIn("Eldoret", found["roster_without_a_return"])

    def test_nothing_loaded_is_not_an_error(self):
        self.client.force_authenticate(self.rm)
        response = self.client.get(self.BASE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["rows"], [])
