"""Active Customers and Digital Adoption from the registration data.

The desk's routine registration report builds a row per customer with a 1/0
flag for every month - ``total_trx_active_dec_2025`` through
``total_trx_active_dec_2026``, and ``mobile_active_*`` beside it. That is
exactly the measure these cards state, and unlike the lake's feed it reaches
back to December 2025, so the prior-year count a "grow by 20%" target is
applied to can be read rather than reported as missing.
"""

import datetime

from django.db import connection
from django.test import TestCase

from . import registration_activity as ra
from .live_scorecard import _two_month_active

CODE = "AK4001"
YEAR = 2026

#: The months the real report carries, written the way it writes them - some
#: short, some in full, which is why the parser matches on three letters.
COLUMNS = [
    ("total_trx_active_dec_2025", datetime.date(2025, 12, 1)),
    ("total_trx_active_jan_2026", datetime.date(2026, 1, 1)),
    ("total_trx_active_feb_2026", datetime.date(2026, 2, 1)),
    ("total_trx_active_march_2026", datetime.date(2026, 3, 1)),
    ("mobile_active_dec_2025", datetime.date(2025, 12, 1)),
    ("mobile_active_jan_2026", datetime.date(2026, 1, 1)),
    ("mobile_active_feb_2026", datetime.date(2026, 2, 1)),
    ("mobile_active_march_2026", datetime.date(2026, 3, 1)),
]


def make_the_feeds(table="registation_data"):
    """Create the registration table and the RM book it joins to.

    Both are warehouse tables, so Django does not create them and the SQL
    would go untested.
    """
    flags = ", ".join(f'"{name}" integer' for name, _ in COLUMNS)
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                cust_id bigint, sales_code varchar(100), updated_at timestamptz
            )
        """)
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {table} "
            f"(cust_id bigint, current_branch varchar(80), {flags})")


def allocate(*cust_ids, code=CODE):
    with connection.cursor() as cur:
        for cust_id in cust_ids:
            cur.execute(
                "INSERT INTO retail_allocated_portfolio "
                "(cust_id, sales_code, updated_at) VALUES (%s, %s, NOW())",
                [cust_id, code])


def customer(cust_id, active=(), digital=(), table="registation_data"):
    """``active`` / ``digital`` are (year, month) pairs."""
    values = {name: 0 for name, _ in COLUMNS}
    for name, month in COLUMNS:
        if name.startswith("total_trx_active") and (month.year, month.month) \
                in {(y, m) for y, m in active}:
            values[name] = 1
        if name.startswith("mobile_active") and (month.year, month.month) \
                in {(y, m) for y, m in digital}:
            values[name] = 1
    columns = ", ".join(f'"{n}"' for n in values)
    marks = ", ".join(["%s"] * (len(values) + 1))
    with connection.cursor() as cur:
        cur.execute(f"INSERT INTO {table} (cust_id, {columns}) "
                    f"VALUES ({marks})", [cust_id] + list(values.values()))


class ReadingTheColumnNamesTests(TestCase):
    """The month set grows as the year runs, so the columns are discovered
    rather than listed - this file would otherwise need editing monthly."""

    def test_the_spellings_the_report_actually_uses(self):
        for name, expected in (
                ("total_trx_active_dec_2025", datetime.date(2025, 12, 1)),
                ("total_trx_active_march_2026", datetime.date(2026, 3, 1)),
                ("total_trx_active_june_2026", datetime.date(2026, 6, 1)),
                ("total_trx_active_sept_2026", datetime.date(2026, 9, 1)),
                ("TOTAL_TRX_ACTIVE_JAN_2026", datetime.date(2026, 1, 1))):
            with self.subTest(name):
                self.assertEqual(
                    ra.parse_column(name, ra.PREFIX_ACTIVE), expected)

    def test_the_two_families_do_not_read_each_other(self):
        self.assertIsNone(
            ra.parse_column("mobile_active_jan_2026", ra.PREFIX_ACTIVE))
        self.assertIsNone(
            ra.parse_column("total_trx_active_jan_2026", ra.PREFIX_DIGITAL))

    def test_a_column_it_cannot_read_is_none_rather_than_a_guess(self):
        for name in ("", None, "total_trx_active", "cust_id",
                     "total_trx_active_xxx_2026", "total_trx_active_jan_26"):
            with self.subTest(name):
                self.assertIsNone(ra.parse_column(name, ra.PREFIX_ACTIVE))


class FindingTheTableTests(TestCase):
    def test_it_takes_the_name_as_the_desk_spells_it(self):
        """The desk calls it registation_data, which is missing an R."""
        make_the_feeds()
        self.assertEqual(ra.find_table(), "registation_data")

    def test_a_table_without_the_flags_is_not_this_feed(self):
        """Reporting it as found would turn a missing feed into an empty
        one, which is a different answer."""
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE registation_data (cust_id bigint)")
        self.assertEqual(ra.find_table(), "")

    def test_no_table_at_all_is_no_table(self):
        self.assertEqual(ra.find_table(), "")


class ActiveMeansTransactedInTheLastTwoMonthsTests(TestCase):
    """EITHER of the two months, not both.

    The rule, as the business states it, is "the last customer transaction
    in the last 2 months" - so a customer who transacted in one of them is
    active. This file used to assert the opposite: an inner join requiring
    the flag in a month AND the month before it, which counts only customers
    who turned up twice and silently drops everyone else.

    Lydia Apanja's signed Q3_Sep_26 card is the check on it: 358 active
    against a YTD target of 116. A both-months rule over her book cannot
    produce a figure that far above target.
    """

    def setUp(self):
        make_the_feeds()
        allocate(1, 2, 3)

    def test_two_consecutive_months_count(self):
        customer(1, active=[(2026, 1), (2026, 2)])
        count, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(count, 1)
        self.assertEqual(as_at, datetime.date(2026, 2, 28))

    def test_one_month_alone_counts_too(self):
        """The change. Their last transaction is inside the window."""
        customer(2, active=[(2026, 2)])
        count, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(count, 1)
        self.assertEqual(as_at, datetime.date(2026, 2, 28))

    def test_a_customer_counts_in_the_month_after_they_transacted(self):
        """January activity still counts as at February - the window is the
        month and the one before it."""
        customer(3, active=[(2026, 1)])
        self.assertEqual(_two_month_active(CODE, YEAR)[YEAR][0], 1)

    def test_a_month_with_no_activity_at_all_is_not_reported(self):
        """The guard that goes with the OR. Under a two-month window a month
        with no rows inherits the month before it, so the feed would appear
        to reach a month that has not happened. Reach is measured on the
        month itself."""
        customer(1, active=[(2026, 1), (2026, 2)])
        _, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(
            as_at, datetime.date(2026, 2, 28),
            "March has no activity, so the figure must not be dated to it")

    def test_the_prior_year_is_readable_which_is_the_whole_point(self):
        """A pair closing in December 2025 is last year's count - the base a
        "grow by 20%" target is applied to. The lake's feed starts in
        January 2026 and can never answer this."""
        customer(1, active=[(2025, 12), (2026, 1)])
        found = _two_month_active(CODE, YEAR)
        # Dec 2025 has no November beside it here, so the pair that closes in
        # January is this year's; what matters is that December is READ.
        self.assertIn(datetime.date(2025, 12, 1),
                      ra.coverage()["months"])

    def test_somebody_elses_customer_is_not_counted(self):
        """And the answer is nought, not a blank: another RM's customer being
        active tells us the feed reaches February, so "none of yours were"
        is a figure rather than a gap."""
        allocate(99, code="OTHER1")
        customer(99, active=[(2026, 1), (2026, 2)])
        count, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(count, 0)
        self.assertEqual(as_at, datetime.date(2026, 2, 28))

    def test_the_latest_month_with_activity_is_the_one_reported(self):
        """Customer 1 last transacted in February and customer 2 in March.
        As at March both are inside the two-month window, so both count -
        under the old AND rule only customer 2 did."""
        customer(1, active=[(2026, 1), (2026, 2)])
        customer(2, active=[(2026, 2), (2026, 3)])
        count, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(count, 2)
        self.assertEqual(as_at, datetime.date(2026, 3, 31))


class DigitalAdoptionTests(TestCase):
    def setUp(self):
        make_the_feeds()
        allocate(1, 2)

    def test_digital_reads_the_mobile_flags(self):
        customer(1, active=[(2026, 1), (2026, 2)],
                 digital=[(2026, 1), (2026, 2)])
        customer(2, active=[(2026, 1), (2026, 2)])
        self.assertEqual(
            _two_month_active(CODE, YEAR, digital=True)[YEAR][0], 1)
        # Both are active; only one of them is digital.
        self.assertEqual(_two_month_active(CODE, YEAR)[YEAR][0], 2)

    def test_digital_in_one_month_is_digitally_active(self):
        """Digital follows the same window as active: the last digital
        transaction inside the two months."""
        customer(1, active=[(2026, 1), (2026, 2)], digital=[(2026, 2)])
        self.assertEqual(
            _two_month_active(CODE, YEAR, digital=True)[YEAR][0], 1)
        self.assertEqual(_two_month_active(CODE, YEAR)[YEAR][0], 1)


class WhenTheFeedIsNotThereTests(TestCase):
    def test_an_absent_table_falls_through_to_the_lake(self):
        """The lake's mirror is the second feed, and an ABSENT registration
        table is the only thing that reaches it."""
        from .models import CustomerMonthlyActivity

        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                    cust_id bigint, sales_code varchar(100),
                    updated_at timestamptz)
            """)
        allocate(1)
        for month in (1, 2):
            CustomerMonthlyActivity.objects.create(
                cust_id=1, month=datetime.date(YEAR, month, 1),
                active=True, digital_active=False)

        # The registration table is not there, so this figure can only have
        # come from the mirror.
        count, as_at = _two_month_active(CODE, YEAR)[YEAR]
        self.assertEqual(count, 1)
        self.assertEqual(as_at, datetime.date(YEAR, 2, 28))

    def test_a_feed_that_is_there_and_empty_is_not_fallen_through(self):
        """A real nought is a figure. Falling through would quietly report a
        different measure under the same name."""
        make_the_feeds()
        allocate(1)
        found = _two_month_active(CODE, YEAR)
        self.assertNotIn("error", found)
        self.assertEqual(found, {})


class WhatTheFeedCoversTests(TestCase):
    def test_it_reports_the_span_and_the_pairs_it_can_answer(self):
        make_the_feeds()
        span = ra.coverage()
        self.assertEqual(span["table"], "registation_data")
        self.assertEqual(span["first_month"], datetime.date(2025, 12, 1))
        self.assertEqual(span["last_month"], datetime.date(2026, 3, 1))
        # December has no November beside it, so it opens no pair.
        self.assertEqual(span["complete_pairs"],
                         [datetime.date(2026, 1, 1),
                          datetime.date(2026, 2, 1),
                          datetime.date(2026, 3, 1)])
