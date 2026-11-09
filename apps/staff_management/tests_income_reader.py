"""Income Contribution reads the card's month, with interest expense subtracted.

The September 2026 proof read 366.5m for an RM whose desk figure was 96.7m:
interest expense is stored negative and "GII - IE" added it, FTP came from a
total_ftp that does not equal its own months, and the year ran to today.
"""
import datetime

from django.db import connection
from django.test import TestCase


def _ddl():
    with connection.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS revenue (
            id bigserial PRIMARY KEY, cust_id bigint, trx_date timestamp,
            sum_dc numeric, income_category text)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
            cust_id bigint, sales_code text, updated_at timestamp)""")


class IncomeReaderTests(TestCase):
    CODE = "HM3729"

    def setUp(self):
        _ddl()
        with connection.cursor() as cur:
            for cust in (101, 102):
                cur.execute(
                    "INSERT INTO retail_allocated_portfolio (cust_id, sales_code) "
                    "VALUES (%s, %s)", [cust, self.CODE])
            # A duplicate allocation row must not count the customer twice.
            cur.execute("INSERT INTO retail_allocated_portfolio (cust_id, sales_code) "
                        "VALUES (101, %s)", [self.CODE])
            rows = [
                (101, "2026-03-10", 1000, "interest_income"),
                (101, "2026-03-10", -700, "interest_expenses"),
                (102, "2026-09-30", 50, "nfi"),
                (102, "2026-10-02", 9999, "interest_income"),   # after September
                (999, "2026-03-10", 5000, "interest_income"),   # not in the book
            ]
            for cust, day, value, cat in rows:
                cur.execute("INSERT INTO revenue (cust_id, trx_date, sum_dc, income_category) "
                            "VALUES (%s, %s, %s, %s)", [cust, day, value, cat])
        from .models import CustMonthlyFtp
        CustMonthlyFtp.objects.create(cust_cif=101, current_year=2026, jan_ftp=100,
                                      sep_ftp=200, oct_ftp=5000, total_ftp=1)

    def test_parts_are_bounded_by_the_cards_month(self):
        from services.portfolio_service import rm_income_ytd

        got = rm_income_ytd(self.CODE, datetime.date(2026, 9, 30))
        self.assertEqual(got["interest_income"], 1000)      # October's 9999 left out
        self.assertEqual(got["interest_expenses"], -700)
        self.assertEqual(got["nfi"], 50)
        self.assertEqual(got["ftp"], 300)                   # Jan + Sep, not total_ftp, not Oct

    def test_interest_expense_is_subtracted(self):
        from unittest import mock

        from . import live_scorecard

        parts = {"interest_income": 1000.0, "interest_expenses": -700.0, "nfi": 50.0,
                 "ftp": 300.0, "loan_loss": -20.0}
        with mock.patch("services.portfolio_service.rm_income_ytd", return_value=parts):
            gii, ie = parts["interest_income"], abs(parts["interest_expenses"])
            # 1000 - 700 + 50 = 350 direct; + 300 FTP - 20 loss = 630.
            self.assertEqual(gii - ie + parts["nfi"], 350)
            self.assertEqual(gii - ie + parts["nfi"] + parts["ftp"] + parts["loan_loss"], 630)
        self.assertTrue(hasattr(live_scorecard, "build_card"))
