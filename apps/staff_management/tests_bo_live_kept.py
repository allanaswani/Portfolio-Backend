"""Back-office live lines read once for the whole bank, not per person per load.

17 Nov 2026: FM4424's card took 3½ minutes because each proven line read
transaction_diary for that one person while the page waited, and a read that
timed out was remembered nowhere. The figures must be the same as the old
per-person SQL gave; only where they are read from changes.
"""
import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase


class WholeBankReadTests(TestCase):
    AS_AT = datetime.date(2026, 10, 31)

    def setUp(self):
        from apps.gceo_dashboard.models import TransactionDiary

        with connection.schema_editor() as editor:
            editor.create_model(TransactionDiary)
        self.addCleanup(self._drop, TransactionDiary)
        cache.clear()
        self.addCleanup(cache.clear)
        rows = [
            # AA1: three rows on two days, one of them a reversal.
            ("aa1 ", "2026-10-05 09:00", 100, "Original"),
            ("AA1", "2026-10-05 15:00", 100, "Original"),
            ("AA1", "2026-10-06 10:00", 100, "Reversal"),
            # BB2: one row of another code.
            ("BB2", "2026-10-07 11:00", 200, "Original"),
            # November is outside October's card.
            ("AA1", "2026-11-02 10:00", 100, "Original"),
        ]
        with connection.cursor() as cur:
            for usr, at, code, flag in rows:
                cur.execute(
                    "INSERT INTO transaction_diary (trx_usr, trx_date, tmstamp,"
                    " trx_code, reverse_flag) VALUES (%s, %s, %s, %s, %s)",
                    [usr, at, at, code, flag])

    @staticmethod
    def _drop(model):
        with connection.schema_editor() as editor:
            editor.delete_model(model)

    def _value(self, feed, code):
        from . import bo_live_feeds as f

        return f.live_value(dict(feed, sheet="S"), code, self.AS_AT)

    def test_per_day_worked_is_the_persons_rows_over_their_days(self):
        feed = {"kind": "per_day_worked"}
        self.assertEqual(self._value(feed, "AA1"), 1.5)
        self.assertEqual(self._value(feed, "BB2"), 1.0)
        self.assertIsNone(self._value(feed, "ZZ9"))

    def test_a_code_count_counts_only_that_persons_original_rows(self):
        feed = {"kind": "code_count", "codes": [100], "rows": "original",
                "cumulative": False}
        self.assertEqual(self._value(feed, "AA1"), 2.0)
        self.assertEqual(self._value(feed, "BB2"), 0.0)
        self.assertEqual(self._value(feed, "ZZ9"), 0.0)

    def test_a_ratio_reads_the_same_measures(self):
        feed = {"kind": "ratio", "num": "reversed", "den": "rows"}
        self.assertAlmostEqual(self._value(feed, "AA1"), 1 / 3)
        self.assertEqual(self._value(feed, "BB2"), 0.0)

    def test_the_second_person_reads_nothing_from_the_warehouse(self):
        from . import bo_live_feeds as f

        feed = {"kind": "per_day_worked"}
        self.assertEqual(self._value(feed, "AA1"), 1.5)
        with patch.object(f, "_rows", side_effect=AssertionError("read again")):
            self.assertEqual(self._value(feed, "BB2"), 1.0)

    def test_the_read_is_kept_in_the_database(self):
        from . import bo_live_feeds as f

        self.assertEqual(self._value({"kind": "per_day_worked"}, "AA1"), 1.5)
        cache.clear()  # a restart, or another worker
        with patch.object(f, "_rows", side_effect=AssertionError("read again")):
            self.assertEqual(self._value({"kind": "per_day_worked"}, "AA1"), 1.5)

    def test_warm_reads_every_proven_feed(self):
        from . import bo_live_feeds as f

        proven = {"A": {"kind": "per_day_worked", "sheet": "A"},
                  "B": {"kind": "code_count", "codes": [100], "rows": "original",
                        "cumulative": False, "sheet": "B"}}
        with patch.object(f, "proven", return_value=proven):
            done = dict(f.warm(self.AS_AT))
        self.assertEqual(done["transactions per person"], 2)
        self.assertEqual(done["B codes"], 1)
