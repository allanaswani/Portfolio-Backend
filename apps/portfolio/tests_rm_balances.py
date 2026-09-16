"""The RM balance ladder: yesterday, the day before, then the last closed month.

EM3579 on 16 Sep 2026 is the case these are written from. The deposit file had
posted (yester_1_bal summed to 296,503,081.98 over 797 accounts) but the loan
file had not (yester_1_bal empty over all 233 loan accounts), so the two tiles
on one screen had to answer as at two different days — and say so.
"""
from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase

from services import portfolio_service as svc


class ClosedMonthsTests(SimpleTestCase):
    def test_running_month_is_never_a_rung(self):
        """September's column exists all through September and holds a part
        month. It is not a month-end balance and must not be fallen back to."""
        with mock.patch.object(svc, "datetime") as dt:
            dt.now.return_value = datetime(2026, 9, 16)
            cols = [c for c, _ in svc._closed_months()]
        self.assertNotIn("sep_26_bal", cols)
        self.assertEqual(cols[0], "aug_26_bal")

    def test_most_recent_first_and_crosses_the_year(self):
        with mock.patch.object(svc, "datetime") as dt:
            dt.now.return_value = datetime(2026, 2, 3)
            cols = [c for c, _ in svc._closed_months()]
        self.assertEqual(cols[:3], ["jan_26_bal", "dec_25_bal", "nov_25_bal"])

    def test_label_is_a_real_month_end(self):
        with mock.patch.object(svc, "datetime") as dt:
            dt.now.return_value = datetime(2026, 9, 16)
            labels = dict((c, l) for c, l in svc._closed_months())
        self.assertEqual(labels["aug_26_bal"], "31 August 2026")
        self.assertEqual(labels["jun_26_bal"], "30 June 2026")

    def test_february_in_a_leap_year(self):
        with mock.patch.object(svc, "datetime") as dt:
            dt.now.return_value = datetime(2028, 6, 1)
            labels = dict((c, l) for c, l in svc._closed_months())
        self.assertEqual(labels["feb_28_bal"], "29 February 2028")


class BalanceLadderTests(SimpleTestCase):
    """_rm_balance picks a rung and names the day it is as at."""

    def _run(self, row):
        """Drive _rm_balance against one warehouse row without a warehouse."""
        cur = mock.MagicMock()
        cur.description = [(k,) for k in row]
        cur.fetchone.return_value = tuple(row.values())
        cur.__enter__.return_value = cur
        # Replace the whole connection object, not its .cursor: SimpleTestCase
        # wraps the real connection's methods to block DB access, and patching
        # one of them in place breaks its teardown.
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        with mock.patch.object(svc, "datetime") as dt, \
             mock.patch.object(svc, "connection", conn):
            dt.now.return_value = datetime(2026, 9, 16)
            return svc._rm_balance("daily_balance_movement", "EM3579")

    def test_yesterday_wins_when_the_file_has_posted(self):
        value, as_at = self._run({
            "y1": 296_503_081.98, "y2": 295_382_949.81, "aug_26_bal": 306_000_000.0,
        })
        self.assertAlmostEqual(value, 296_503_081.98, places=2)
        self.assertEqual(as_at, "yesterday")

    def test_falls_back_to_the_day_before(self):
        """The loan case: yester_1_bal empty across every account."""
        value, as_at = self._run({
            "y1": None, "y2": 479_466_154.31, "aug_26_bal": 470_000_000.0,
        })
        self.assertAlmostEqual(value, 479_466_154.31, places=2)
        self.assertEqual(as_at, "2 days ago")

    def test_falls_back_to_the_last_closed_month(self):
        value, as_at = self._run({
            "y1": None, "y2": None,
            "aug_26_bal": 306_280_000.0, "jul_26_bal": 300_000_000.0,
        })
        self.assertAlmostEqual(value, 306_280_000.0, places=2)
        self.assertEqual(as_at, "as at 31 August 2026")

    def test_no_rows_reports_nothing_rather_than_zero_as_a_fact(self):
        value, as_at = self._run({"y1": None, "y2": None, "aug_26_bal": None})
        self.assertEqual(value, 0.0)
        self.assertIsNone(as_at)

    def test_a_zero_is_not_a_balance(self):
        """A summed 0.0 means every account filtered out, not a book worth zero;
        the ladder must keep walking rather than reporting it."""
        value, as_at = self._run({"y1": 0.0, "y2": 295_382_949.81})
        self.assertAlmostEqual(value, 295_382_949.81, places=2)
        self.assertEqual(as_at, "2 days ago")
