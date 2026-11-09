"""Whole-table report readers, read once in the background and kept.

The readers ported from the bank's reports (weighted sales New Customers,
focus accounts, drawdowns; the iApply loan TAT seller view) each read a whole
table and work it the way the report does. A card that waited for that on a
cold cache ran past the server's 120-second request limit and showed "Your
scorecard could not be loaded" (9 Nov 2026). Now a card never waits: on a cold
cache the read starts in the background and the line says it is being read,
and the next load has it. The proof waits (:func:`waiting`), because a figure
it does not have would count as a mismatch.
"""
from __future__ import annotations

import contextlib
import logging
import sys
import threading

log = logging.getLogger(__name__)
_local = threading.local()
BUSY_SECONDS = 900


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


def _must_wait():
    # The test runner reads synchronously: a background thread would outlive
    # the test's transaction.
    return getattr(_local, "wait", False) or (len(sys.argv) > 1 and sys.argv[1] == "test")


def cached(key, compute, ttl=3600):
    """The cached result, or None while it is being read in the background."""
    from django.core.cache import cache

    found = cache.get(key)
    if found is not None:
        return found
    if _must_wait():
        found = compute()
        cache.set(key, found, ttl)
        return found
    if cache.add(f"{key}:busy", 1, BUSY_SECONDS):
        def run():
            from django.db import connection

            try:
                cache.set(key, compute(), ttl)
            except Exception:  # noqa: BLE001 - logged; the line keeps waiting
                log.exception("Background read %s failed", key)
            finally:
                cache.delete(f"{key}:busy")
                connection.close()

        threading.Thread(target=run, name=f"feed-{key}", daemon=True).start()
    return None


PREPARING = ("being read from the report now - it fills in on the next load, "
             "within a few minutes")
