"""Prove which scorecard lines can read live, from a button rather than the server.

A line reads live only after it reproduces the desk's own figures for a month the
desk has closed. This runs those comparisons for each workbook in a background thread
and keeps what they report, so Administration can read the result on a screen.
"""

from __future__ import annotations

import datetime
import threading

STATUS_KIND = "feed_proof_status"
BOOKS = ("back_office", "sales", "branch_managers")
#: A run silent this long died with its worker, so another may start.
STALE_AFTER = datetime.timedelta(hours=1)
#: How often a running proof reports that it is still going.
SAVE_EVERY = datetime.timedelta(seconds=30)


def _now():
    from django.utils import timezone

    return timezone.now()


def status():
    from .workbook_cards import saved

    state = saved(STATUS_KIND) or {}
    if state.get("state") == "running" and not _is_running(state):
        return dict(state, state="stopped", log=list(state.get("log") or []) + [
            "This run stopped without finishing, usually because the server restarted. "
            "Nothing was changed by it unless a result is listed above. Run it again."])
    return state


def _is_running(state):
    if state.get("state") != "running":
        return False
    heard = datetime.datetime.fromisoformat(state.get("updated_at") or state["started_at"])
    return _now() - heard < STALE_AFTER


def _save(state):
    from .workbook_cards import save_file

    state["updated_at"] = _now().isoformat()
    save_file(STATUS_KIND, state, "feed proof", state.get("by", ""))


def _run_book(book, year, month, out):
    if book == "back_office":
        from . import bo_live_feeds, sales_live_feeds
        from .workbook_cards import BACK_OFFICE

        bo_live_feeds.probe(year, month, out=out)
        out("Now the figures the system already reads for each person's card ...")
        sales_live_feeds.probe(year, month, out=out, book=BACK_OFFICE,
                               store=bo_live_feeds.ENGINE_STORE_KIND)
    elif book == "sales":
        from . import sales_live_feeds

        sales_live_feeds.probe(year, month, out=out)
    elif book == "branch_managers":
        from . import bb_live_feeds

        bb_live_feeds.probe(year, month, out=out)
    else:
        raise ValueError(f"unknown book {book}")


def _fresh(book, year, month, by):
    return {"state": "running", "book": book, "month": f"{year}-{month:02d}",
            "by": by, "started_at": _now().isoformat(), "log": []}


def run(book, year, month, by=""):
    """One run, start to finish, in this thread. Never raises: the screen says why."""
    state = _fresh(book, year, month, by)
    _save(state)

    def out(line=""):
        state["log"].append(str(line))
        if _now() - datetime.datetime.fromisoformat(state["updated_at"]) >= SAVE_EVERY:
            _save(state)

    try:
        _run_book(book, year, month, out)
        state["state"] = "finished"
    except Exception as exc:  # noqa: BLE001 - the reason is the answer
        state["state"] = "failed"
        state["log"].append(f"The run stopped: {exc}")
    state["finished_at"] = _now().isoformat()
    _save(state)
    return state


def start(book, year, month, by=""):
    """Begin a run in the background → True, or False if one is already going."""
    from django.db import connection

    if _is_running(status()):
        return False
    # Said before the thread starts, so a second press cannot start another.
    _save(_fresh(book, year, month, by))

    def target():
        try:
            run(book, year, month, by)
        finally:
            connection.close()

    threading.Thread(target=target, name=f"feed-proof-{book}", daemon=True).start()
    return True


def summary():
    """What is proven for each workbook now, for the screen."""
    from . import bb_live_feeds, bo_live_feeds, sales_live_feeds

    def engine_rows(stored):
        return [{"line": v.get("name"), "sheet": v.get("sheet"), "match": v.get("match"),
                 "people": v.get("people"), "month": v.get("month"), "live": bool(v.get("live"))}
                for v in sorted(stored.values(), key=lambda x: str(x.get("name")))]

    transaction_feeds = [
        {"line": sheet, "sheet": sheet, "match": feed.get("match"), "people": feed.get("people"),
         "month": feed.get("month"), "live": True, "how": bo_live_feeds.describe(feed)}
        for sheet, feed in sorted(bo_live_feeds.proven().items())]
    return {
        "back_office": transaction_feeds + engine_rows(bo_live_feeds.engine_proven()),
        "sales": engine_rows(sales_live_feeds.proven()),
        "branch_managers": [
            {"line": key, "sheet": feed.get("sheet"), "match": feed.get("match"),
             "month": feed.get("month"), "live": True, "how": feed.get("label")}
            for key, feed in sorted(bb_live_feeds.proven().items())],
    }
