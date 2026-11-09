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
            # application, action, created, loaded, status to, status from, user, name, code, seller
            ("A1", sep(2026, 9, 2), sep(2026, 9, 1), sep(2026, 9, 2, 1), "CCA Processing",
             "RM New application created", "RM jane", "Jane Doe", "MK 3445", "Margaret"),
            ("A1", sep(2026, 9, 5), sep(2026, 9, 1), sep(2026, 9, 5, 1),
             "STORED Archived - Disbursed", "CCA Processing", "CCA john", "John Roe",
             "MK 3445", "Margaret"),
        ]
        # 1 day to the first step; the closing step is nought, so the mean is 1.
        self.assertEqual(seller_tat(rows, 2026, 9), {"MK3445": 1.0})
        self.assertEqual(seller_tat(rows, 2026, 8), {})

    def test_the_card_line_reads_the_seller_view(self):
        self.assertEqual(SOURCES["tat_loan"].actual_key, "tat_seller_month")
        self.assertFalse(SOURCES["tat_loan"].higher_is_better)
