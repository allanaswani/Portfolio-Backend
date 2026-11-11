"""Deposit Growth as the bank's daily deposit movement report computes it
(daily_balance_movement.py, summarise_rm_portfoio_movement - the report sent
every morning, 11 Nov 2026)."""
import datetime

from django.db import connection
from django.test import TestCase

from services import portfolio_service as svc


class ReportDepositGrowthTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS daily_balance_movement")
            cur.execute("""CREATE TABLE daily_balance_movement (
                cust_cif bigint, acc_num varchar(30), rm_code varchar(30),
                sale_code varchar(30), open_date date, customer_segment varchar(50),
                dec_25_bal double precision, sep_26_bal double precision,
                yester_1_bal double precision, yester_2_bal double precision)""")
            rows = [
                # existing customer on the RM's book: 100 -> 160
                (1, "A1", "RM1", "XX9", "2020-05-01", "MASS", 100, 160),
                # existing, overdrawn now: counts as 0, so 50 -> 0
                (2, "A2", "RM1", "RM1", "2019-01-01", "MASS", 50, -30),
                # NEW this year, sold by RM1 but on another RM's book: +40
                (3, "A3", "OTHER", "RM1", "2026-03-10", "MASS", 0, 40),
                # existing customer opened a second account this year: still existing
                (4, "A4", "RM1", "RM1", "2026-04-01", "MASS", 0, 25),
                (4, "A5", "RM1", "RM1", "2018-02-01", "MASS", 10, 10),
                # internal accounts are not left out by the report
                (5, "A6", "RM1", "RM1", "2015-01-01", "INTERNAL ACCOUNTS", 5, 5),
                # another RM's existing customer sold by RM1: not RM1's
                (6, "A7", "OTHER", "RM1", "2010-01-01", "MASS", 70, 90),
            ]
            for r in rows:
                cur.execute("""INSERT INTO daily_balance_movement
                    (cust_cif, acc_num, rm_code, sale_code, open_date, customer_segment,
                     dec_25_bal, sep_26_bal) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", r)

    def test_the_reports_portfolio_change(self):
        g = svc.rm_growth("daily_balance_movement", "rm1", as_at=datetime.date(2026, 9, 30))
        # existing on rm_code: (160 + 0 + 25 + 10 + 5) - (100 + 50 + 0 + 10 + 5) = 35
        # new on sale_code: + 40
        self.assertEqual(g["growth"], 75.0)
        self.assertEqual(g["base"], 165.0)
        self.assertEqual(g["as_at"], datetime.date(2026, 9, 30))
        self.assertIsNone(g["problem"])
