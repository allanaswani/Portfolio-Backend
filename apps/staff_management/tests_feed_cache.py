"""A card never waits for a whole-table report read; the proof does."""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase


class FeedCacheTests(SimpleTestCase):
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

        with mock.patch.object(feed_cache, "_local") as local:
            local.wait = True
            self.assertEqual(feed_cache.cached("k2", lambda: {"A": 1}), {"A": 1})
        self.assertEqual(cache.get("k2"), {"A": 1})
