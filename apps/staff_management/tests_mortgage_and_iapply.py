"""The Mortgage Business ARM card's three dashes, all off data already held.

* Net Mortgage sales, commercial / non-commercial rate (20% each): the
  drawdown carries ``final_interest``, so the split is made on the rate.
* Errors (5%): applications iApply RETURNED, over applications.
* TAT (Loan) (10%): the summarised dump had no row for them; the raw trail
  the iApply report reads does.
"""

import datetime

from django.db import connection
from django.test import TestCase

from . import loan_applications as la
from .live_scorecard import (
    COMMERCIAL_RATE_ABOVE, SOURCES, _mortgage_split_ytd, live_actuals)

CODE = "MB4100"
YEAR = 2026


def make_drawdowns():
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS drawdown_daily (
                id bigserial PRIMARY KEY,
                drawdown_dt date, salesperson varchar(255),
                loan_officer_id varchar(50), final_interest double precision,
                net_drawdown double precision
            )
        """)


def drawn(rate, amount, on=datetime.date(YEAR, 3, 1), code=CODE):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO drawdown_daily (drawdown_dt, salesperson, "
            "loan_officer_id, final_interest, net_drawdown) "
            "VALUES (%s, %s, '', %s, %s)", [on, code, rate, amount])


def make_trail():
    with connection.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {la.TABLE} (
                id bigserial PRIMARY KEY,
                "ApplicationId" varchar(40), "SellerCode" varchar(40),
                "CreationDate" varchar(40),
                "ActionDate" timestamp without time zone,
                "StatusTo" varchar(120)
            )
        """)


def step(app_id, created, actioned, status="Credit Approval", code=CODE):
    with connection.cursor() as cur:
        cur.execute(
            f'INSERT INTO {la.TABLE} ("ApplicationId", "SellerCode", '
            f'"CreationDate", "ActionDate", "StatusTo") '
            f'VALUES (%s, %s, %s, %s, %s)',
            [app_id, code, created, actioned, status])


class MortgageSplitTests(TestCase):

    def setUp(self):
        make_drawdowns()

    def test_the_rate_splits_the_drawdowns(self):
        drawn(13.5, 4_000_000)                       # commercial
        drawn(COMMERCIAL_RATE_ABOVE, 3_000_000)      # at 10%: non-commercial
        drawn(9.5, 1_000_000)                        # non-commercial
        commercial, non_commercial, latest = _mortgage_split_ytd(CODE, YEAR)
        self.assertEqual(commercial, 4_000_000)
        self.assertEqual(non_commercial, 4_000_000)
        self.assertEqual(latest, datetime.date(YEAR, 3, 1))

    def test_the_lines_read_it_and_are_no_longer_pending(self):
        drawn(13.5, 4_000_000)
        for code, key in (
                ("net_mortgage_sales_10_commercial_rate_mortgages",
                 "mortgage_commercial"),
                ("net_mortgage_sales_10_non_commercial_rate_mortgages",
                 "mortgage_non_commercial")):
            with self.subTest(code):
                self.assertEqual(SOURCES[code].actual_key, key)
                self.assertFalse(SOURCES[code].pending)
        out = live_actuals(CODE, wanted={"mortgage_commercial"})
        self.assertEqual(out["mortgage_commercial"]["value"], 4_000_000)


class ApplicationTrailTests(TestCase):

    def setUp(self):
        make_trail()

    def test_errors_are_the_share_sent_back(self):
        step("A1", "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        step("A1", "2026-03-01 00:00:00", "2026-03-03 00:00:00",
             status="RM Processing Application Returned by DCR")
        step("A2", "2026-03-01 00:00:00", "2026-03-05 00:00:00")
        step("A3", "2026-03-01 00:00:00", "2026-03-04 00:00:00")
        step("A4", "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        found = la.seller_applications(CODE, YEAR)
        self.assertEqual(found["applications"], 4)
        self.assertEqual(found["returned"], 1)
        self.assertAlmostEqual(found["error_rate"], 0.25)
        # (2 + 4 + 3 + 1) / 4, creation to last action.
        self.assertAlmostEqual(found["tat_days"], 2.5, places=4)

    def test_the_card_reads_errors_lower_is_better(self):
        self.assertFalse(SOURCES["errors"].pending)
        self.assertFalse(SOURCES["errors"].higher_is_better)
        step("A1", "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        out = live_actuals(CODE, wanted={"loan_application_errors"})
        self.assertEqual(out["loan_application_errors"]["value"], 0)

    def test_tat_falls_back_to_the_trail(self):
        """No summarised dump row - the Mortgage ARM case - and the trail
        answers instead of "no loan applications"."""
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS iapply_loan_approvals_data_dump (
                    id bigserial PRIMARY KEY, creation_date timestamp,
                    seller_code varchar(20), total_bank_tat numeric,
                    branch integer
                )
            """)
        step("A1", "2026-03-01 00:00:00", "2026-03-08 00:00:00")
        out = live_actuals(CODE, wanted={"tat_days"})
        self.assertAlmostEqual(out["tat_days"]["value"], 7.0, places=4)
        self.assertIn("iApply trail", out["tat_days"]["as_at_label"])
