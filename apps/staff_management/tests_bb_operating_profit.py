"""Branch Operating Profit (19 Nov 2026).

The branch manager's Operating Profit line reads the template's
Revenue_Contribution sheet, and no branch definition existed for it, so every
branch card kept the desk's September figure ("no warehouse source is wired").
These are the readers the branch proof now tests against the desk's figures.
"""
import datetime

from django.core.cache import cache
from django.db import connection
from django.test import TestCase

from . import bb_live_feeds as bb


def _ddl():
    with connection.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS revenue (
            id bigserial PRIMARY KEY, cust_id bigint, brn_code bigint,
            trx_unit bigint, trx_date timestamp, sum_dc numeric,
            income_category text)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS customers (
            cust_id bigint, branch text)""")


class BranchOperatingProfitTests(TestCase):
    def setUp(self):
        cache.clear()
        _ddl()
        with connection.cursor() as cur:
            rows = [
                # account at Hurlingham (19), transacted at Rehani (200)
                (101, 19, 200, "2026-03-10", 1000, "interest_income"),
                (101, 19, 200, "2026-03-10", -300, "interest_expenses"),
                (101, 19, 200, "2026-09-30", 50, "nfi"),
                (101, 19, 200, "2026-10-02", 9999, "interest_income"),  # after September
            ]
            for cust, brn, unit, day, value, cat in rows:
                cur.execute(
                    "INSERT INTO revenue (cust_id, brn_code, trx_unit, trx_date, "
                    "sum_dc, income_category) VALUES (%s, %s, %s, %s, %s, %s)",
                    [cust, brn, unit, day, value, cat])
            cur.execute("INSERT INTO customers (cust_id, branch) VALUES (101, 'HURLINGHAM')")
        from apps.portfolio.models import LoansMomIFRSMovement

        from .models import CustMonthlyFtp

        LoansMomIFRSMovement.objects.create(lns_account="L1", eom_date=datetime.date(2026, 6, 30),
                                            branch="HURLINGHAM", pl_charge=80, int_adj=30)

        CustMonthlyFtp.objects.create(cust_cif=101, current_year=2026, jan_ftp=100,
                                      sep_ftp=200, oct_ftp=5000, total_ftp=1)

    def test_direct_contribution_by_account_branch(self):
        got = bb._revenue(2026, 9, "brn_code", "direct", 60_000)
        # GII 1000 - IE 300 (stored negative, taken as a size) + NFI 50;
        # October's 9999 is after the card's month.
        self.assertEqual(got, {"hurlingham": 750.0})

    def test_income_contribution_adds_ftp_and_takes_the_loan_loss(self):
        got = bb._revenue(2026, 9, "brn_code", "income", 60_000)
        # 750 + FTP Jan 100 + Sep 200 (not October, not total_ftp)
        #     - P&L charge less int. adj. (80 - 30)
        self.assertEqual(got, {"hurlingham": 1000.0})

    def test_by_transaction_unit_puts_it_where_it_was_transacted(self):
        got = bb._revenue(2026, 9, "trx_unit", "direct", 60_000)
        self.assertEqual(got, {"rehani": 750.0})

    def test_the_proof_tests_every_table_of_the_sheet(self):
        for key in ("Revenue_Contribution", "Revenue_Contribution#1",
                    "Revenue_Contribution#2"):
            self.assertEqual(len(bb.DEFINITIONS[key]), 4, key)
        self.assertEqual({o.get("block") for _l, _k, o in bb.DEFINITIONS["Revenue_Contribution#2"]},
                         {2})
        # A branch line on that sheet no longer says nothing is wired.
        self.assertNotIn("no warehouse source", bb.why_not_live("Revenue_Contribution", 0))
        self.assertNotIn("no warehouse source", bb.why_not_live("Revenue_Contribution", 1))

    def test_a_branch_total_reads_by_branch(self):
        totals = bb._totals({"kind": "revenue", "by": "brn_code", "parts": "direct",
                             "sheet": "Revenue_Contribution"}, 2026, 9, 60_000)
        self.assertEqual(
            bb._branch_total(totals, "Hurlingham", {"kind": "revenue"}), 750.0)
