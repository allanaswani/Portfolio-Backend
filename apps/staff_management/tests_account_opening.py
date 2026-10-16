"""Account-opening turnaround, from iApply's ACCOUNTS trail.

The cards say what this is: "PB AO TAT OF 1 Day". A number of days, lower is
better. Jane Karathe's signed card reads 0.10 for personal banking and 0.88
for business banking against that one-day target.

It was refused before because iApply carries LOAN turnaround - true of
``iapply_loan_approvals_data_dump``, and not of ``iapply_accounts_tat``,
which is the account application trail.
"""

import datetime

from django.db import connection
from django.test import TestCase

from . import account_opening as ao
from .live_scorecard import SOURCES

CODE = "JK4500"
YEAR = 2026


def make_the_feeds():
    """Create the trail and the customer master it joins to.

    Both are warehouse tables, so Django does not create them. The types are
    the LIVE ones, read off the real table: ``CreationDate`` is a varchar,
    ``ActionDate`` is a timestamp, and ``Customerid`` is a varchar. That
    mixture is the whole reason the reader guards both date casts and strips
    non-digits before joining.
    """
    with connection.cursor() as cur:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS iapply_accounts_tat (
                id bigserial PRIMARY KEY,
                "ApplicationId" varchar(40),
                "Customerid" varchar(40),
                "SellerCode" varchar(40),
                "CreationDate" varchar(40),
                "ActionDate" timestamp without time zone,
                "StatusTo" varchar(80)
            )
        ''')
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id bigserial PRIMARY KEY,
                cust_id bigint, firstname varchar(80), lastname varchar(80),
                segment varchar(60)
            )
        """)


def a_customer(cust_id, segment="MASS"):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO customers (cust_id, segment) VALUES (%s, %s)",
                    [cust_id, segment])


def a_step(application, cust_id, created, actioned, code=CODE):
    """One row of an application's trail."""
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO iapply_accounts_tat ("ApplicationId", "Customerid", '
            '"SellerCode", "CreationDate", "ActionDate") '
            'VALUES (%s, %s, %s, %s, %s)',
            [application, str(cust_id), code, created, actioned])


class TurnaroundTests(TestCase):
    def setUp(self):
        make_the_feeds()
        a_customer(1, "MASS")

    def test_it_measures_days_from_creation_to_the_last_action(self):
        a_step("BA1", 1, "2026-03-01 08:00:00", "2026-03-01 09:00:00")
        a_step("BA1", 1, "2026-03-01 08:00:00", "2026-03-02 08:00:00")
        days, applications, latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 1)
        self.assertAlmostEqual(days, 1.0, places=4)
        self.assertEqual(latest, datetime.date(2026, 3, 2))

    def test_the_average_is_over_applications_not_status_changes(self):
        """An application that went round the houses would otherwise count
        six times and drag the branch's figure with it."""
        for _ in range(6):
            a_step("BA1", 1, "2026-03-01 00:00:00", "2026-03-05 00:00:00")
        a_step("BA2", 1, "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 2)
        # (4 + 1) / 2, not (4 x 6 + 1) / 7.
        self.assertAlmostEqual(days, 2.5, places=4)

    def test_a_malformed_creation_date_does_not_fail_the_whole_read(self):
        """``CreationDate`` is a VARCHAR on the live table. One bad value in
        600,000 rows would otherwise take the statement down, and with it the
        whole card - not just this line."""
        a_step("BA1", 1, "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        a_step("BA2", 1, "not a date", "2026-03-02 00:00:00")
        days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 1)
        self.assertAlmostEqual(days, 1.0, places=4)

    def test_the_timestamp_column_is_read_without_a_timezone_shift(self):
        """``ActionDate`` is a real timestamp. It goes through
        ::text::timestamp rather than ::timestamptz so the session's time
        zone cannot move a figure measured in days."""
        a_step("BA1", 1, "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        days, _applications, latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertAlmostEqual(days, 1.0, places=6)
        self.assertEqual(latest, datetime.date(2026, 3, 2))

    def test_all_four_segments_come_from_one_read(self):
        """611,218 rows and nothing indexes SellerCode, so a query per
        segment meant four scans for every card built."""
        a_customer(2, "SMALL ENTERPRISES")
        a_step("BA1", 1, "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        a_step("BA2", 2, "2026-03-01 00:00:00", "2026-03-03 00:00:00")

        from django.test.utils import CaptureQueriesContext
        from django.db import connection as conn

        with CaptureQueriesContext(conn) as captured:
            found = ao.turnarounds(CODE, YEAR)
        reads = [q for q in captured.captured_queries
                 if "iapply_accounts_tat" in q["sql"]]
        self.assertEqual(len(reads), 1, "one scan, not one per segment")
        self.assertEqual(found["pb"][1], 1)
        self.assertEqual(found["bb"][1], 1)
        self.assertAlmostEqual(found["bb"][0], 2.0, places=4)

    def test_a_customer_id_that_is_not_digits_is_handled(self):
        a_step("BA1", "CU-001", "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        # It joins to nothing, so it falls to the ELSE and counts as PB.
        _days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 1)

    def test_a_trail_that_runs_backwards_is_not_a_turnaround(self):
        a_step("BA1", 1, "2026-03-05 00:00:00", "2026-03-01 00:00:00")
        _days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 0)

    def test_another_sales_code_is_not_counted(self):
        a_step("BA1", 1, "2026-03-01 00:00:00", "2026-03-02 00:00:00",
               code="SOMEBODY")
        _days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 0)

    def test_another_year_is_not_counted(self):
        a_step("BA1", 1, "2025-03-01 00:00:00", "2025-03-02 00:00:00")
        _days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 0)

    def test_nothing_to_measure_is_reported_as_nothing(self):
        days, applications, latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertIsNone(days)
        self.assertEqual(applications, 0)
        self.assertIsNone(latest)


class TheSegmentsTests(TestCase):
    def setUp(self):
        make_the_feeds()

    def test_each_segment_sees_only_its_own(self):
        a_customer(1, "MASS")                 # personal banking
        a_customer(2, "SMALL ENTERPRISES")    # business banking / SME
        a_customer(3, "ULTIMATE")             # ultimate
        for cust_id in (1, 2, 3):
            a_step(f"BA{cust_id}", cust_id,
                   "2026-03-01 00:00:00", "2026-03-02 00:00:00")

        for segment, expected in (("pb", 1), ("bb", 1), ("ub", 1)):
            with self.subTest(segment):
                _days, applications, _latest = ao.turnaround(
                    CODE, YEAR, segment)
                self.assertEqual(applications, expected)

    def test_sme_and_business_banking_are_the_same_population(self):
        """``core.segments`` reads BUSINESS BANKING, SME, SMALL ENTERPRISES
        and MEDIUM ENTERPRISES as one segment. The two lines differ only in
        their target - five days against one - which is on the card."""
        a_customer(2, "MEDIUM ENTERPRISES")
        a_step("BA2", 2, "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        bb = ao.turnaround(CODE, YEAR, "bb")
        sme = ao.turnaround(CODE, YEAR, "sme")
        self.assertEqual(bb, sme)
        self.assertEqual(bb[1], 1)

    def test_an_unmapped_segment_falls_to_personal_banking(self):
        """The ETL's own ELSE. A segment nobody has mapped still lands
        somewhere rather than vanishing from every card."""
        a_customer(9, "SOMETHING NOBODY MAPPED")
        a_step("BA9", 9, "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        _days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 1)

    def test_a_large_enterprise_is_not_personal_banking(self):
        a_customer(9, "LARGE ENTERPRISES")
        a_step("BA9", 9, "2026-03-01 00:00:00", "2026-03-02 00:00:00")
        _days, applications, _latest = ao.turnaround(CODE, YEAR, "pb")
        self.assertEqual(applications, 0)


class WhenTheFeedIsNotThereTests(TestCase):
    def test_an_absent_trail_says_which_table(self):
        """A missing table is the ETL's problem and a timeout is this
        query's, and they go to different people."""
        with self.assertRaises(ao.AccountOpeningUnavailable) as caught:
            ao.turnaround(CODE, YEAR, "pb")
        self.assertIn("iapply_accounts_tat", str(caught.exception))


class TheLinesReadAFeedNowTests(TestCase):
    def test_all_four_are_measured_and_lower_is_better(self):
        for code, key in (("bo_account_opening_pb", "ao_tat_pb"),
                          ("bo_account_opening_bb", "ao_tat_bb"),
                          ("bo_account_opening_ub", "ao_tat_ub"),
                          ("bo_account_opening_sme", "ao_tat_sme")):
            with self.subTest(code):
                source = SOURCES[code]
                self.assertEqual(source.actual_key, key)
                self.assertFalse(source.pending)
                # It is a number of DAYS against a one-day target.
                self.assertFalse(source.higher_is_better)

    def test_the_loan_turnaround_is_still_a_different_feed(self):
        """The refusal was right about ``tat_days``: that reads the LOAN
        approvals dump, and pointing an account-opening line at it would put
        a loan figure against an account-opening target."""
        self.assertEqual(SOURCES["bo_branch_loan_tat"].actual_key, "tat_days")
        self.assertNotEqual(SOURCES["bo_account_opening_pb"].actual_key,
                            "tat_days")


class ItReachesTheCardTests(TestCase):
    CODE = "JK4500"

    def setUp(self):
        from .models import EmployeeRoleHistory, StaffEmployeeData

        make_the_feeds()
        day = datetime.date(2020, 1, 1)
        StaffEmployeeData.objects.create(
            staff_pf_number="4500", staff_name="Jane Karathe",
            sales_code=self.CODE, job_title="Customer Service",
            employment_date=day, is_active=True)
        EmployeeRoleHistory.objects.get_or_create(
            sales_code=self.CODE, role_code="bo_cso", start_date=day,
            defaults={"role_status": "active"})

    def test_the_figure_shows_on_the_card(self):
        from .live_scorecard import build_card

        a_customer(1, "MASS")
        year = datetime.date.today().year
        a_step("BA1", 1, f"{year}-03-01 00:00:00", f"{year}-03-02 00:00:00",
               code=self.CODE)

        card = build_card(self.CODE)
        lines = {ln["kpi_code"]: ln
                 for group in card["perspectives"] for ln in group["lines"]}
        line = lines["bo_account_opening_pb"]
        self.assertAlmostEqual(line["ytd_actual"], 1.0, places=4)
        self.assertFalse(line["pending"])
        self.assertIn("account", line["as_at"])
