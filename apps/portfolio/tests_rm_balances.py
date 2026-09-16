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

    def _run(self, row, columns=None):
        """Drive _rm_balance against one warehouse row without a warehouse.

        `columns` is what the catalogue reports the table has. It defaults to
        the keys of `row` plus customer_segment, so a test only names it when
        the schema IS the point."""
        cols = columns if columns is not None else set(row) | {"customer_segment"}
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
             mock.patch.object(svc, "connection", conn), \
             mock.patch.object(svc, "_table_columns", return_value=cols):
            dt.now.return_value = datetime(2026, 9, 16)
            return svc._rm_balance("daily_balance_movement", "EM3579")

    def test_yesterday_wins_when_the_file_has_posted(self):
        value, as_at = self._run({
            "yester_1_bal": 296_503_081.98, "yester_2_bal": 295_382_949.81, "aug_26_bal": 306_000_000.0,
        })
        self.assertAlmostEqual(value, 296_503_081.98, places=2)
        self.assertEqual(as_at, "yesterday")

    def test_falls_back_to_the_day_before(self):
        """The loan case: yester_1_bal empty across every account."""
        value, as_at = self._run({
            "yester_1_bal": None, "yester_2_bal": 479_466_154.31, "aug_26_bal": 470_000_000.0,
        })
        self.assertAlmostEqual(value, 479_466_154.31, places=2)
        self.assertEqual(as_at, "2 days ago")

    def test_falls_back_to_the_last_closed_month(self):
        value, as_at = self._run({
            "yester_1_bal": None, "yester_2_bal": None,
            "aug_26_bal": 306_280_000.0, "jul_26_bal": 300_000_000.0,
        })
        self.assertAlmostEqual(value, 306_280_000.0, places=2)
        self.assertEqual(as_at, "as at 31 August 2026")

    def test_no_rows_reports_nothing_rather_than_zero_as_a_fact(self):
        value, as_at = self._run({"yester_1_bal": None, "yester_2_bal": None, "aug_26_bal": None})
        self.assertEqual(value, 0.0)
        self.assertIsNone(as_at)

    def test_a_zero_is_not_a_balance(self):
        """A summed 0.0 means every account filtered out, not a book worth zero;
        the ladder must keep walking rather than reporting it."""
        value, as_at = self._run({"yester_1_bal": 0.0, "yester_2_bal": 295_382_949.81})
        self.assertAlmostEqual(value, 295_382_949.81, places=2)
        self.assertEqual(as_at, "2 days ago")

    def test_months_the_warehouse_never_created_are_not_selected(self):
        """This is the bug that shipped.

        The month columns are not a uniform monthly series: 2026 is monthly but
        older periods are QUARTERLY, so jul_25_bal and oct_25_bal do not exist.
        Naming one fails the whole statement, and with the error swallowed the
        function returned 0.00 for an RM sitting on 296 million — whereupon the
        screen fell back to August's close and showed 306M as if it were today.

        Only columns the catalogue reports may appear in the SQL."""
        warehouse = {
            "rm_code", "customer_segment", "yester_1_bal", "yester_2_bal",
            "dec_24_bal", "mar_25_bal", "jun_25_bal", "sep_25_bal", "dec_25_bal",
            "jan_26_bal", "feb_26_bal", "mar_26_bal", "apr_26_bal", "may_26_bal",
            "jun_26_bal", "jul_26_bal", "aug_26_bal", "sep_26_bal",
        }
        cur = mock.MagicMock()
        cur.description = [("yester_1_bal",)]
        cur.fetchone.return_value = (296_503_081.98,)
        cur.__enter__.return_value = cur
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        with mock.patch.object(svc, "datetime") as dt, \
             mock.patch.object(svc, "connection", conn), \
             mock.patch.object(svc, "_table_columns", return_value=warehouse):
            dt.now.return_value = datetime(2026, 9, 16)
            value, as_at = svc._rm_balance("daily_balance_movement", "EM3579")

        sql = cur.execute.call_args[0][0]
        for absent in ("jul_25_bal", "aug_25_bal", "oct_25_bal", "nov_25_bal"):
            self.assertNotIn(absent, sql, f"{absent} does not exist in the warehouse")
        self.assertIn("aug_26_bal", sql)
        self.assertNotIn("sep_26_bal", sql)  # the running month, still never a rung
        self.assertAlmostEqual(value, 296_503_081.98, places=2)
        self.assertEqual(as_at, "yesterday")

    def test_a_database_error_is_not_swallowed(self):
        """Returning 0.0 on failure is what hid the bug for a whole deploy."""
        cur = mock.MagicMock()
        cur.execute.side_effect = RuntimeError("relation does not exist")
        cur.__enter__.return_value = cur
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        with mock.patch.object(svc, "datetime") as dt, \
             mock.patch.object(svc, "connection", conn), \
             mock.patch.object(svc, "_table_columns",
                               return_value={"yester_1_bal", "aug_26_bal"}):
            dt.now.return_value = datetime(2026, 9, 16)
            with self.assertRaises(RuntimeError):
                svc._rm_balance("daily_balance_movement", "EM3579")
