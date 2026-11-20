"""TAT (Loan) is the iApply TAT report's seller view, step by step.

Checked once against the report's own functions (add_current_status_rows,
calculate_tat, tat_value_summary) on 400 random applications: the same figure
to six decimals for every seller in two months.
"""
import datetime as dt

from django.test import SimpleTestCase

from .live_scorecard import SOURCES
from .loan_tat_seller import seller_tat


class SellerTatTests(SimpleTestCase):
    def test_a_closing_step_counts_nought_and_the_mean_skips_noughts(self):
        sep = dt.datetime
        rows = [
            # application, action, created, loaded, status to, status from, user,
            # name, code, seller, branch, segment
            ("A1", sep(2026, 9, 2), sep(2026, 9, 1), sep(2026, 9, 2, 1), "CCA Processing",
             "RM New application created", "RM jane", "Jane Doe", "MK 3445", "Margaret",
             230, "PERSONAL BANKING"),
            ("A1", sep(2026, 9, 5), sep(2026, 9, 1), sep(2026, 9, 5, 1),
             "STORED Archived - Disbursed", "CCA Processing", "CCA john", "John Roe",
             "MK 3445", "Margaret", 230, "PERSONAL BANKING"),
        ]
        # 1 day to the first step; the closing step is nought, so the mean is 1.
        self.assertEqual(seller_tat(rows, 2026, 9), {"MK3445": 1.0})
        self.assertEqual(seller_tat(rows, 2026, 8), {})

    def test_the_card_line_reads_the_seller_view(self):
        self.assertEqual(SOURCES["tat_loan"].actual_key, "tat_seller_month")
        self.assertFalse(SOURCES["tat_loan"].higher_is_better)


def _app(app, branch, segment, days):
    """One application: created 1 Sep, one step ``days`` later, then closed."""
    sep = dt.datetime
    return [
        (app, sep(2026, 9, 1 + days), sep(2026, 9, 1), sep(2026, 9, 1 + days, 1),
         "CCA Processing", "RM New application created", "RM x", "X", "C1", "S",
         branch, segment),
        (app, sep(2026, 9, 20), sep(2026, 9, 1), sep(2026, 9, 20, 1),
         "STORED Archived - Disbursed", "CCA Processing", "CCA y", "Y", "C1", "S",
         branch, segment),
    ]


class BranchTatTests(SimpleTestCase):
    def test_branch_view_over_every_segment_and_per_segment(self):
        from .loan_tat_seller import ALL_SEGMENTS, branch_tat

        rows = (_app("A1", 230, "PERSONAL BANKING", 2) + _app("A2", 230, "SME", 4)
                + _app("A3", "600", "PERSONAL BANKING", 3))
        out = branch_tat(rows, 2026, 9)
        # Each application has one non-nought step (the closing one is nought).
        self.assertEqual(out["BURUBURU BRANCH"][ALL_SEGMENTS], 3.0)
        self.assertEqual(out["BURUBURU BRANCH"]["PERSONAL BANKING"], 2.0)
        self.assertEqual(out["BURUBURU BRANCH"]["SME"], 4.0)
        self.assertEqual(out["KISUMU BRANCH"][ALL_SEGMENTS], 3.0)

    def test_two_codes_of_one_branch_are_one_branch(self):
        from .loan_tat_seller import ALL_SEGMENTS, branch_tat

        out = branch_tat(_app("A1", 19, "SME", 2) + _app("A2", 210, "SME", 6), 2026, 9)
        self.assertEqual(out["HURLINGHAM BRANCH"][ALL_SEGMENTS], 4.0)

    def test_an_unknown_code_is_head_office_as_in_the_report(self):
        from .loan_tat_seller import branch_tat

        self.assertIn("HEAD OFFICE", branch_tat(_app("A1", None, "SME", 2), 2026, 9))


class BranchLoanTatProofTests(SimpleTestCase):
    """The desk's Branch_Loan_TAT is matched against the report, not assumed."""

    HEADER = ["PF", "Code", "Name", "Role", "Branch", "Zone"] + [None] * 12

    def _sheet(self, figures):
        rows = [self.HEADER]
        for n, (branch, value) in enumerate(figures):
            row = [n, f"U{n}", f"Person {n}", "BOM", branch, "Z"] + [None] * 12
            row[6 + 9 - 1] = value
            rows.append(row)
        return {"Branch_Loan_TAT": rows}

    def _views(self, mapping):
        from unittest import mock

        from . import loan_tat_seller as lts

        return (mock.patch.object(lts, "_rows", return_value=[]),
                mock.patch.object(lts, "branch_tat", return_value=mapping))

    def test_the_reading_that_gives_the_desk_figures_is_chosen(self):
        from . import bo_live_feeds as blf

        branches = [f"B{i} BRANCH" for i in range(6)]
        desk = [(b, 2.0 + i) for i, b in enumerate(branches)]
        views = {b: {"*": 9.0, "PERSONAL BANKING": 2.0 + i}
                 for i, b in enumerate(branches)}
        rows_patch, views_patch = self._views(views)
        with rows_patch, views_patch:
            feed = blf.prove_branch_loan_tat(self._sheet(desk), 2026, 9, out=lambda *_: None)
        self.assertEqual(feed["kind"], "branch_loan_tat")
        self.assertEqual(feed["segment"], "PERSONAL BANKING")
        self.assertEqual(feed["match"], 1.0)

    def test_nothing_goes_live_when_no_reading_matches(self):
        from . import bo_live_feeds as blf

        branches = [f"B{i} BRANCH" for i in range(6)]
        desk = [(b, 2.0 + i) for i, b in enumerate(branches)]
        views = {b: {"*": 50.0} for b in branches}
        rows_patch, views_patch = self._views(views)
        lines = []
        with rows_patch, views_patch:
            feed = blf.prove_branch_loan_tat(self._sheet(desk), 2026, 9, out=lines.append)
        self.assertIsNone(feed)
        self.assertTrue(any("not good enough" in line for line in lines))

    def test_value_is_read_by_the_templates_branch_spelling(self):
        from unittest import mock

        from . import bo_live_feeds as blf
        from . import loan_tat_seller as lts

        with mock.patch.object(lts, "branch_month_tat",
                               return_value={"BURUBURU BRANCH": {"*": 1.5, "SME": 0.0}}):
            feed = {"kind": "branch_loan_tat", "segment": "*"}
            when = dt.date(2026, 11, 20)
            self.assertEqual(blf.branch_loan_tat_value(feed, " buruburu  branch", when), 1.5)
            self.assertIsNone(blf.branch_loan_tat_value(feed, "Buruburu", when))
            # A nought is an empty month, not a turnaround of nought days.
            self.assertIsNone(blf.branch_loan_tat_value(dict(feed, segment="SME"),
                                                        "BURUBURU BRANCH", when))
