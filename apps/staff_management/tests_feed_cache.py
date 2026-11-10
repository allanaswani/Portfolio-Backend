"""A card never waits for a whole-table report read, and never loses one."""
import datetime
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone


class FeedCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_cold_read_starts_in_the_background_and_returns_nothing(self):
        from . import feed_cache

        started = []
        with mock.patch.object(feed_cache, "_must_wait", return_value=False), \
                mock.patch("threading.Thread") as thread:
            thread.return_value.start.side_effect = lambda: started.append(1)
            self.assertIsNone(feed_cache.cached("k1", lambda: {"A": 1}))
            # A second request does not start a second read.
            self.assertIsNone(feed_cache.cached("k1", lambda: {"A": 1}))
        self.assertEqual(started, [1])

    def test_inside_waiting_it_reads_and_keeps_the_result(self):
        from . import feed_cache

        with feed_cache.waiting():
            self.assertEqual(feed_cache.cached("k2", lambda: {"A": 1}), {"A": 1})
        self.assertEqual(cache.get("k2"), {"A": 1})

    def test_a_result_outlives_the_cache(self):
        # Valary Simiyu's October card (10 Nov 2026): New Customers and
        # Drawdowns went back to "being read" whenever the hour-long cache
        # entry ran out. The database copy is shown instead.
        from . import feed_cache

        with feed_cache.waiting():
            feed_cache.cached("k3", lambda: {"VS3759": 4, 19: 2})
        cache.clear()
        with mock.patch.object(feed_cache, "_must_wait", return_value=False), \
                mock.patch.object(feed_cache, "_start") as start:
            self.assertEqual(feed_cache.cached("k3", lambda: {}), {"VS3759": 4, 19: 2})
        start.assert_not_called()

    def test_an_old_result_is_shown_while_a_fresh_one_is_read(self):
        from . import feed_cache
        from .models import BoWorkbookFile

        with feed_cache.waiting():
            feed_cache.cached("k4", lambda: {"A": 1}, ttl=60)
        BoWorkbookFile.objects.filter(kind=feed_cache._kind("k4")).update(
            loaded_at=timezone.now() - datetime.timedelta(hours=2))
        cache.clear()
        with mock.patch.object(feed_cache, "_must_wait", return_value=False), \
                mock.patch.object(feed_cache, "_start") as start:
            self.assertEqual(feed_cache.cached("k4", lambda: {"A": 2}, ttl=60), {"A": 1})
        start.assert_called_once()

    def test_a_background_read_gets_the_long_statement_limit(self):
        from . import feed_cache

        seen = []
        with feed_cache.waiting():
            feed_cache.cached("k5", lambda: seen.append(feed_cache.timeout(120_000)) or {})
        self.assertEqual(feed_cache.timeout(120_000), 120_000)
        self.assertEqual(seen, [feed_cache.BACKGROUND_TIMEOUT_MS])

    def test_fresh_reads_again_even_when_kept(self):
        from . import feed_cache

        with feed_cache.waiting():
            feed_cache.cached("k6", lambda: {"A": 1})
        with feed_cache.fresh():
            self.assertEqual(feed_cache.cached("k6", lambda: {"A": 2}), {"A": 2})
        self.assertEqual(feed_cache.cached("k6", lambda: {"A": 3}), {"A": 2})
