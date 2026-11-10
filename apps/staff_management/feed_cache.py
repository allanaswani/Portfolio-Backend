"""Whole-table report readers, read once in the background and kept.

The readers ported from the bank's reports (weighted sales New Customers,
focus accounts, drawdowns; the iApply loan TAT seller view) each read a whole
table and work it the way the report does. A card that waited for that on a
cold cache ran past the server's 120-second request limit and showed "Your
scorecard could not be loaded" (9 Nov 2026). So a card never waits.

What went wrong after that (10 Nov 2026, Valary Simiyu's October card still
said "being read" on New Customers and Drawdowns):

* the result lived only in the cache, for an hour - once it expired every
  card went back to "being read" until a new read finished;
* the background read ran under the request's 2-3 minute statement limit on a
  whole year of a big table, so it could fail every time, and only a log line
  said so.

Now every result is also kept in the database (``BoWorkbookFile``, kind
``feed:<hash>``). A card shows the last result read, however old, and an
older one than ``ttl`` starts a fresh read behind it. A background read gets
``BACKGROUND_TIMEOUT_MS``. ``manage.py warm_scorecard_feeds`` reads them all
in the foreground and prints any failure, for cron and for checking.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import logging
import sys
import threading

log = logging.getLogger(__name__)
_local = threading.local()
_running = set()
_running_lock = threading.Lock()
BUSY_SECONDS = 1800
BACKGROUND_TIMEOUT_MS = 1_500_000  # 25 minutes: nobody is waiting on it


@contextlib.contextmanager
def waiting():
    """Inside this, a reader computes and returns rather than starting a
    background read - for the proof, and anything else that must have figures."""
    before = getattr(_local, "wait", False)
    _local.wait = True
    try:
        yield
    finally:
        _local.wait = before


@contextlib.contextmanager
def fresh():
    """Inside this (warm_scorecard_feeds), a reader ignores what is kept and
    reads again, in the foreground."""
    before = getattr(_local, "fresh", False)
    _local.fresh = True
    try:
        with waiting():
            yield
    finally:
        _local.fresh = before


def _must_wait():
    # The test runner reads synchronously: a background thread would outlive
    # the test's transaction.
    return getattr(_local, "wait", False) or (len(sys.argv) > 1 and sys.argv[1] == "test")


def timeout(ms):
    """The statement limit for a reader: its own on a request, a long one off it."""
    if getattr(_local, "background", False):
        return max(int(ms), BACKGROUND_TIMEOUT_MS)
    return int(ms)


def _kind(key):
    # BoWorkbookFile.kind is 20 characters.
    return "feed:" + hashlib.sha1(key.encode()).hexdigest()[:15]


def _pack(found):
    # JSON keeps only string keys; branch readers key on brn_code integers.
    return [[k, v] for k, v in found.items()] if isinstance(found, dict) else found


def _unpack(items):
    return {k: v for k, v in items} if isinstance(items, list) else items


def _stored(key):
    """(result, read at) from the database, or (None, None)."""
    from .models import BoWorkbookFile

    try:
        row = BoWorkbookFile.objects.filter(kind=_kind(key)).first()
    except Exception:  # noqa: BLE001 - a missing table is no stored result
        return None, None
    if row is None or not isinstance(row.payload, dict) or "items" not in row.payload:
        return None, None
    return _unpack(row.payload["items"]), row.loaded_at


def _keep(key, found, ttl):
    from django.core.cache import cache

    from .workbook_cards import save_file

    save_file(_kind(key), {"key": key, "items": _pack(found)}, key[:255],
              "feed_cache")
    cache.set(key, found, ttl)


def _compute(key, compute, ttl):
    before = getattr(_local, "background", False)
    _local.background = True
    try:
        found = compute()
    finally:
        _local.background = before
    _keep(key, found, ttl)
    return found


def _start(key, compute, ttl):
    """Start a background read unless one for ``key`` is running."""
    from django.core.cache import cache

    with _running_lock:
        if key in _running:
            return
        # Across the server's workers. False is "held by another worker"; None
        # (a cache that is down) must not stop the read for good.
        if cache.add(f"{key}:busy", 1, BUSY_SECONDS) is False:
            return
        _running.add(key)

    def run():
        from django.db import connection

        try:
            _compute(key, compute, ttl)
        except Exception:  # noqa: BLE001 - logged; the kept result stays shown
            log.exception("Background read %s failed", key)
        finally:
            with _running_lock:
                _running.discard(key)
            cache.delete(f"{key}:busy")
            connection.close()

    threading.Thread(target=run, name=f"feed-{key}", daemon=True).start()


def cached(key, compute, ttl=3600):
    """The result, or None only before the first read of ``key`` has finished."""
    from django.core.cache import cache

    if getattr(_local, "fresh", False):
        return _compute(key, compute, ttl)
    found = cache.get(key)
    if found is not None:
        return found
    found, at = _stored(key)
    if found is not None:
        cache.set(key, found, ttl)
        from django.utils import timezone

        if at is None or timezone.now() - at > datetime.timedelta(seconds=ttl):
            if not _must_wait():
                _start(key, compute, ttl)
        return found
    if _must_wait():
        return _compute(key, compute, ttl)
    _start(key, compute, ttl)
    return None


PREPARING = ("being read from the report now - it fills in on the next load, "
             "within a few minutes")
