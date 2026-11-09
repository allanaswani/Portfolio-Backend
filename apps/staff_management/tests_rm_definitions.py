"""The proof chooses the candidate definition that reproduces the desk."""
import datetime
from unittest import mock

from django.test import TestCase


class ChooseTests(TestCase):
    def test_the_candidate_that_gives_the_desk_is_stored_and_read(self):
        from . import rm_definitions as rmd
        from .sales_live_feeds import same

        candidates = {"PAR: officer": {"A1": 0.5, "B2": 0.5},
                      "PAR: allocated": {"A1": 0.10, "B2": 0.20}}
        people = [("A1", 0.10), ("B2", 0.20)]
        with mock.patch.dict(rmd.SHEETS, {"par": (lambda y, m: candidates, "par")}):
            share, name = rmd.choose("par", people, 2026, 9, same, out=lambda *_: None)
            self.assertEqual((share, name), (1.0, "PAR: allocated"))
            self.assertEqual(rmd.chosen()["par"], "PAR: allocated")
            self.assertEqual(rmd.value("par", "B 2", datetime.date(2026, 9, 30)), 0.20)

    def test_nothing_is_stored_below_the_pass_share(self):
        from . import rm_definitions as rmd
        from .sales_live_feeds import same

        with mock.patch.dict(rmd.SHEETS, {"par": (lambda y, m: {"x": {"A1": 9.0}}, "par")}):
            rmd.choose("par", [("A1", 0.1)], 2026, 9, same, out=lambda *_: None)
        self.assertNotIn("par", rmd.chosen())


class CandidateSqlRunsTests(TestCase):
    """Every candidate's SQL runs (here on tiny tables) - a typo would otherwise
    only show on the server's proof."""

    def test_the_three_readers_run(self):
        from django.db import connection

        from . import rm_definitions as rmd

        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                cust_id bigint, sales_code text, updated_at timestamp)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS iapply_loan_tat (
                "ApplicationId" text, "SellerCode" text, "DecisionType" text,
                "StatusTo" text, "ActionDate" text)""")
            cur.execute("INSERT INTO retail_allocated_portfolio VALUES (7, 'MK3445', now())")
            cur.execute("""INSERT INTO iapply_loan_tat VALUES
                ('A', 'MK3445', 'Return', 'RM returned', '2026-09-03 10:00:00'),
                ('A', 'MK3445', 'Approve', 'CCA', '2026-09-04 10:00:00'),
                ('B', 'MK3445', 'Approve', 'CCA', '2026-09-05 10:00:00')""")
        found = rmd.errors(2026, 9)
        self.assertAlmostEqual(
            found["Errors: returned actions / actions, month, by decision"]["MK3445"], 1 / 3)
        self.assertAlmostEqual(
            found["Errors: applications returned / applications, month, by decision"]["MK3445"], 0.5)
        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS loans (
                cust_id bigint, eom_date timestamp, total_arrears double precision,
                days_in_arrears integer, capital_balance double precision,
                total_capital_balance double precision, euro_book_balance double precision,
                account_officer varchar(20))""")
            cur.execute("""INSERT INTO loans VALUES
                (7, '2026-09-30', 5, 40, 100, 100, 100, 'MK3445'),
                (7, '2026-09-30', 0, 0, 300, 300, 300, 'MK3445')""")
            cur.execute("""CREATE TABLE IF NOT EXISTS daily_balance_movement (
                cust_cif bigint, rm_code text, sale_code text, customer_segment text,
                dec_25_bal double precision, sep_26_bal double precision,
                yester_1_bal double precision)""")
            cur.execute("""INSERT INTO daily_balance_movement VALUES
                (7, 'MK3445', 'XX1', 'MASS', 1000, 1500, 0),
                (8, 'MK3445', 'XX1', 'STAFF', 0, 200, 0)""")
        par = rmd.par(2026, 9)
        self.assertAlmostEqual(par["PAR: allocated book, 31+ days / capital_balance"]["MK3445"], 0.25)
        self.assertAlmostEqual(par["PAR: officer book, arrears / capital_balance"]["MK3445"], 5 / 400)
        dep = rmd.deposits(2026, 9)
        self.assertEqual(dep["Deposits: rm_code, all segments"]["MK3445"], 700)
        self.assertEqual(dep["Deposits: rm_code, staff segment out"]["MK3445"], 500)
        self.assertEqual(dep["Deposits: allocated, all segments"]["MK3445"], 500)
