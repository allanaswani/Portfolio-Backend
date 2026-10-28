"""Finance's IFRS movement workbook into loans_mom_ifrs_movement.

On the host the table's newest month was 2025-07-01 with not one 2026 row:
its only route in, the old system's CSV upload, was never carried over.
"""

import datetime

from django.test import TestCase

from . import ifrs_movement as im


def a_row(account="250003405", gross=100.0, grade="SUBSTD"):
    return {"lns_account": account, "prev_gross": None, "current_gross": gross,
            "prev_ifrs": None, "current_ifrs": None, "prev_grade": "WATCH",
            "current_grade": grade, "movt_in_gross": None,
            "movt_in_ifrs": None, "narration_status": None,
            "write_off_amount": None, "adjusted_opening_ifrs": None,
            "customer_name": "X", "pl_charge": 10.0, "cust_code": None,
            "description": None, "segment": None, "int_adj": 1.0,
            "cust_code_strategy": "1188777", "new_segmentation": None,
            "branch": None, "branch2": None, "comments": None,
            "increase_writeback": None, "product": None, "product_desc": None}


class ReadingTests(TestCase):

    def test_month_sheets_are_recognised_and_the_rest_are_not(self):
        self.assertEqual(im.month_of("Aug 2026"), datetime.date(2026, 8, 1))
        self.assertEqual(im.month_of("Jan 2026"), datetime.date(2026, 1, 1))
        for other in ("rm_summary", "CUSTOMER SUMMARY_2026", "unique_cif",
                      "BRANCH SUMMARY_2026"):
            with self.subTest(other):
                self.assertIsNone(im.month_of(other))

    def test_an_account_is_stored_as_digits_the_card_can_join_on(self):
        """The card joins TRIM(lns_account) to the loan account number;
        "250003405.0" would match nothing."""
        self.assertEqual(im._clean("lns_account", 250003405.0), "250003405")
        self.assertEqual(im._clean("cust_code_strategy", 1188777.0),
                         "1188777")
        self.assertEqual(im._clean("cust_code", "1188777-4"), "1188777-4")
        self.assertEqual(im._clean("pl_charge", 7180415.67), 7180415.67)
        self.assertIsNone(im._clean("pl_charge", "#N/A"))
        self.assertEqual(im._clean("customer_name", " PLEASANT VIEW "),
                         "PLEASANT VIEW")


class ReplaceTests(TestCase):

    def test_loading_a_month_twice_replaces_it_and_never_doubles_it(self):
        from apps.portfolio.models import LoansMomIFRSMovement

        aug = datetime.date(2026, 8, 1)
        im.replace_month(aug, [a_row("1"), a_row("2")])
        im.replace_month(aug, [a_row("1"), a_row("2"), a_row("3")])
        self.assertEqual(
            LoansMomIFRSMovement.objects.filter(eom_date=aug).count(), 3)

    def test_other_months_are_left_alone(self):
        from apps.portfolio.models import LoansMomIFRSMovement

        jul_2025 = datetime.date(2025, 7, 1)
        im.replace_month(jul_2025, [a_row("9")])
        im.replace_month(datetime.date(2026, 8, 1), [a_row("1")])
        self.assertEqual(
            LoansMomIFRSMovement.objects.filter(eom_date=jul_2025).count(), 1)
        self.assertEqual(im.months_held(),
                         [jul_2025, datetime.date(2026, 8, 1)])
