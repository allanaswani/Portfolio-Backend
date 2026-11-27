"""Institutional Banking cards for the month still open, from the warehouse.

Every IB card line reads the IB actuals template, whose per-person sheets are
SUMIFS over its account sheet (Portfolio): each IB account's RM_CODE, the
desk's LEGACY CAT (Legacy / Non-Legacy - typed by the desk, no warehouse
source), month-end balances from DEC_25_BAL, interest expense and rate, NFI.

A line goes live only once the warehouse figure it would use is proven to
give the desk's own template figure for a closed month (``manage.py
ib_feed_probe``), as every other book's live feeds are. Until then
:func:`live_ib_card` returns None and the open month says it is waiting -
never a made-up score.
"""
from __future__ import annotations

#: Lines proven against the desk's template and switched on: template sheet
#: name -> how it is read. Empty until the probe has run on the server.
PROVEN: dict = {}


def live_ib_card(book, actuals, holder, as_at):
    """The open month's IB card from proven warehouse feeds, or None."""
    if not PROVEN:
        return None
    return None
