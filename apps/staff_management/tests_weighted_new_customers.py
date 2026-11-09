"""New Customers is the weighted sales report's count, step by step.

Checked once against the report's own process_daily_accounts_dataframe,
new_customers and zero_out_return_salespersons_in_same_role on 3,000 random
accounts: the same count for every seller.
"""
import datetime as dt

import pandas as pd
from django.test import SimpleTestCase

from .weighted_sales_new_customers import count_by_seller


def row(code, cif, opened, status="ACTIVE", cto=50, bal=0, before=0, segment="MASS"):
    return {"SALE_CODE": code, "CUSTOMER_SEGMENT": segment, "TOTAL_ACCOUNT_BEFORE_2024": before,
            "CUST_OPEN_DATE": opened, "CUST_CIF": cif, "CUST_CTO": cto, "CURR_24_BAL": bal,
            "ACCOUNT_STATUS": status}


class NewCustomersTests(SimpleTestCase):
    def test_the_reports_rules(self):
        sep, oct_ = dt.datetime(2026, 9, 3), dt.datetime(2026, 10, 3)
        frame = pd.DataFrame([
            row("MK 3445", 1, sep),                     # counted (space dropped)
            row("MK3445", 1, sep),                      # same customer again: once
            row("MK3445", 2, sep, status="CLOSED"),     # first row closed: not counted
            row("MK3445", 2, sep),
            row("MK3445", 3, sep, cto=0, bal=0),        # unfunded
            row("MK3445", 4, sep, before=1),            # had an account before this year
            row("MK3445", 5, sep, segment="STAFF"),     # staff
            row("MK3445", 6, oct_),                     # after the card's month
            row("AL3116", 7, sep),                      # corrected to AKL3116
            row("DSR309", 8, dt.datetime(2026, 5, 1)),  # zeroed to June
        ])
        self.assertEqual(count_by_seller(frame, 2026, 9), {"MK3445": 1, "AKL3116": 1})


class FocusAccountsTests(SimpleTestCase):
    def test_funded_open_focus_accounts_with_the_reports_merges(self):
        from .live_scorecard import SOURCES
        from .weighted_sales_new_customers import focus_by_seller

        sep = dt.datetime(2026, 9, 3)
        frame = pd.DataFrame([
            {"SALE_CODE": "MK3445", "CUSTOMER_SEGMENT": "MASS", "ACC_OPEN_DATE": sep,
             "BAL": bal, "ACCOUNT_CTO": cto, "ACCOUNT_STATUS": status, "PROD_ID": prod,
             "BRN_CODE": brn}
            for bal, cto, status, prod, brn in [
                (5, 0, "ACTIVE", 1, 20),       # counted
                (0, 3, "ACTIVE", 31805, 20),   # forced focus, funded by CTO
                (0, 0, "ACTIVE", 1, 20),       # unfunded
                (5, 0, "CLOSED", 1, 20),       # closed
                (5, 0, "ACTIVE", 2, 20),       # not a focus product
                (5, 0, "ACTIVE", 1, 10),       # branch listed twice: counts twice
            ]])
        got = focus_by_seller(frame, [(1, "Y"), (2, "N"), (31805, "N")],
                              [(10, "X"), (10, "X"), (20, "Y")], 2026, 9)
        self.assertEqual(got, {"MK3445": 4})
        self.assertEqual(
            SOURCES["cross_sell_new_casa_accounts_focus_accounts"].actual_key,
            "focus_accounts")


class BranchNewCustomersTests(SimpleTestCase):
    def test_by_branch_with_210_as_hurlingham(self):
        from .weighted_sales_new_customers import count_by_branch

        sep = dt.datetime(2026, 9, 3)
        frame = pd.DataFrame([dict(row("MK3445", 1, sep), BRN_CODE=500),
                              dict(row("MK3445", 1, sep), BRN_CODE=500),   # same customer
                              dict(row("AB1", 2, sep), BRN_CODE=210),
                              dict(row("DSR309", 3, dt.datetime(2026, 5, 1)), BRN_CODE=19)])
        # No seller is zeroed on the branch table, and 210 is Hurlingham (19).
        self.assertEqual(count_by_branch(frame, 2026, 9), {500: 1, 19: 2})
