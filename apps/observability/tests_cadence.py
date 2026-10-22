"""Freshness judged against a table's own cadence.

Written against the five rows the dashboard was reporting as stale on
15 October 2026. Three of them were false alarms, and three false alarms out of
five is worse than no dashboard: it teaches people that the red rows are noise,
and then the one genuinely dead feed on the list gets ignored along with them.

    ceo_loan_movement_monthly_by_segment   14d on dates_eom     monthly
    portfolio_rm_deposit_trends            14d on dates_eom     monthly
    product_mapping                        55d on date_created  reference
    employee_table                         41d on updated_at    a real question
    ceo_channel_report                    532d on trx_date      a dead feed
"""

import datetime

from django.test import SimpleTestCase

from .health import (
    MONTH_END_STALE_DAYS, STALE_DAYS, _classify, _days_since_month_closed,
    cadence_of,
)


class CadenceTests(SimpleTestCase):
    def test_a_month_end_column_is_a_monthly_feed(self):
        for column in ("dates_eom", "eom_date", "DATES_EOM", "month_end",
                       "period_end"):
            with self.subTest(column):
                self.assertEqual(cadence_of("whatever", column), "monthly")

    def test_a_mapping_tables_creation_date_is_reference_data(self):
        self.assertEqual(cadence_of("product_mapping", "date_created"),
                         "reference")
        self.assertEqual(cadence_of("premium_types_mapping", "created_at"),
                         "reference")

    def test_a_creation_date_on_a_FEED_is_still_a_feed(self):
        """The suffix matters as much as the column. A warehouse table that
        happens to carry created_at is a daily feed, and excusing it would
        hide a stopped ETL."""
        self.assertEqual(cadence_of("daily_balance_movement", "created_at"),
                         "daily")
        self.assertEqual(cadence_of("loans", "date_created"), "daily")

    def test_anything_else_is_daily(self):
        for table, column in (("ceo_channel_report", "trx_date"),
                              ("employee_table", "updated_at"),
                              ("loans", "report_date")):
            with self.subTest(table):
                self.assertEqual(cadence_of(table, column), "daily")


class MonthEndFeedsTests(SimpleTestCase):
    """A month-end table is inherently two to five weeks old and crosses a
    seven-day threshold every single month."""

    def test_the_baseline_is_how_long_since_the_month_closed(self):
        self.assertEqual(
            _days_since_month_closed(datetime.date(2026, 10, 15)), 15)
        self.assertEqual(
            _days_since_month_closed(datetime.date(2026, 10, 1)), 1)

    def test_holding_the_last_closed_month_is_not_stale(self):
        """30 September, read on 15 October, is 14 days old and exactly
        right. This was two of the five false alarms.

        Pinned to its own date for the reason given below, on the test that
        missed a month: unpinned, this one passes for most of the month and
        fails on the 1st and the 2nd, when 14 days has not yet been absorbed
        by the days since the month closed.
        """
        from unittest import mock

        with mock.patch("apps.observability.health.timezone") as clock:
            clock.localdate.return_value = datetime.date(2026, 10, 15)
            self.assertEqual(
                _classify(True, 144, 14, "monthly"), "ok",
                "a monthly feed holding the last closed month is not stale")
            self.assertEqual(_classify(True, 38237, 14, "monthly"), "ok")

    def test_the_same_age_on_a_daily_feed_is_stale(self):
        """The point of the cadence: 14 days is fine for one kind of table and
        a stopped ETL for another."""
        self.assertEqual(_classify(True, 144, 14, "daily"), "stale")

    def test_a_monthly_feed_that_missed_a_month_is_stale(self):
        """31 August read on 5 October - 35 days - is a month behind, which is
        the thing this is supposed to catch.

        The date has to be pinned. A monthly verdict is measured from the
        month that last CLOSED, so ``_classify`` reads the clock, and the
        same 35 days means different things depending on where in the month
        it is read: on 5 October it is a month behind, on 22 October it is
        13 days past a month end and merely a warning. Left unpinned this
        passed for the first week of every month and failed for the rest of
        it - which is worse than failing outright, because it looks like a
        regression in whatever happened to be committed that day.
        """
        from unittest import mock

        with mock.patch("apps.observability.health.timezone") as clock:
            clock.localdate.return_value = datetime.date(2026, 10, 5)
            self.assertEqual(_classify(True, 144, 35, "monthly"), "stale")

    def test_it_holds_late_in_the_month_too(self):
        """30 September read on 28 October is 28 days old and still the last
        closed month. Judged against today it would be stale; judged against
        the month that closed, it is not."""
        from unittest import mock

        with mock.patch("apps.observability.health.timezone") as clock:
            clock.localdate.return_value = datetime.date(2026, 10, 28)
            self.assertEqual(_classify(True, 144, 28, "monthly"), "ok")

    def test_the_monthly_threshold_is_looser_than_the_daily_one(self):
        self.assertGreater(MONTH_END_STALE_DAYS, STALE_DAYS)


class ReferenceDataTests(SimpleTestCase):
    def test_reference_data_is_reported_as_what_it_is(self):
        """product_mapping at 55 days on date_created. The column records when
        a product was ADDED, so its age measures how long since the bank
        launched something - not whether the table is loaded."""
        self.assertEqual(_classify(True, 224, 55, "reference"), "reference")
        self.assertEqual(_classify(True, 224, 900, "reference"), "reference")

    def test_an_empty_reference_table_is_still_empty(self):
        """Excusing the age must not excuse an empty table. A mapping table
        with no rows breaks every join that reads it."""
        self.assertEqual(_classify(True, 0, 5, "reference"), "empty")

    def test_a_missing_reference_table_is_still_missing(self):
        self.assertEqual(_classify(False, 0, None, "reference"), "missing")


class TheRealOnesStillShowTests(SimpleTestCase):
    """The two rows on that list that were NOT false alarms. If a cadence rule
    ever starts excusing these, it has gone too far."""

    def test_a_feed_dead_for_seventeen_months_is_stale(self):
        self.assertEqual(
            _classify(True, 248, 532, cadence_of("ceo_channel_report",
                                                 "trx_date")),
            "stale")

    def test_the_hr_roster_at_forty_one_days_still_asks_the_question(self):
        self.assertEqual(
            _classify(True, 2609, 41, cadence_of("employee_table",
                                                 "updated_at")),
            "stale")


class SummaryTests(SimpleTestCase):
    def test_reference_rows_count_as_healthy_not_as_problems(self):
        """Otherwise the headline reads "54 healthy of 80" with nothing
        actually wrong, which is the same false alarm one level up."""
        from .health import summarise

        rows = [{"status": "ok", "rows": 10, "error": ""},
                {"status": "reference", "rows": 224, "error": ""},
                {"status": "stale", "rows": 248, "error": ""}]
        found = summarise(rows)
        self.assertEqual(found["healthy"], 2)
        self.assertEqual(found["problems"], 1)
