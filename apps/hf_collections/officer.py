"""What an officer is carrying, and what they have actually brought in.

"Contributions" on a collections desk is not the size of the book - that is
handed to you. It is the money that came IN off the book you were handed, and
whether the promises you took were kept. Both are read from feeds the officer
cannot edit: ``loan_repayments`` for the money, and the PTP settlement for
the promises.

Assignment is ``loans.delay_officer``, the core banking system's own field -
``DELAY_OFFICER_ID``, where "delay" is that system's word for delinquency. It
already holds a sales code, so an officer's own code is what scopes their
book, and nothing has to be re-keyed here to make that work.
"""

from __future__ import annotations

import datetime
from decimal import Decimal


def _rows(sql, params):
    """One read → list of dicts, or [] when the feed is not there."""
    from django.db import connection, transaction

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, params)
            columns = [c[0] for c in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001 - an absent feed costs its own section
        return []


def book(officer_code):
    """What this officer is carrying → a summary dict.

    Counted over DELINQUENT loans only (``overdue_days > 0``), because that is
    what a collections officer is given. Counting their whole portfolio would
    make the arrears ratio meaningless.
    """
    rows = _rows(
        """
        SELECT COUNT(DISTINCT l.cust_id)            AS customers,
               COUNT(*)                             AS loans,
               COALESCE(SUM(l.euro_book_balance),0) AS outstanding,
               COALESCE(SUM(l.total_arrears),0)     AS arrears,
               COALESCE(MAX(l.days_in_arrears),0)   AS worst_dpd
        FROM loans l
        WHERE LOWER(TRIM(COALESCE(l.delay_officer,''))) = LOWER(TRIM(%s))
          AND COALESCE(l.overdue_days, 0) > 0
        """, [officer_code])
    if not rows:
        return {"customers": 0, "loans": 0, "outstanding": 0.0,
                "arrears": 0.0, "worst_dpd": 0, "feed": False}

    row = rows[0]
    return {
        "customers": int(row["customers"] or 0),
        "loans": int(row["loans"] or 0),
        "outstanding": float(row["outstanding"] or 0),
        "arrears": float(row["arrears"] or 0),
        "worst_dpd": int(row["worst_dpd"] or 0),
        "feed": True,
    }


def collected(officer_code, since=None, until=None):
    """Money that came in off this officer's book → a summary dict.

    Principal AND interest: a borrower who clears arrears interest has paid.
    The window defaults to the year to date, which is how a collections desk
    reports.

    Joined through ``loans`` on the loan account, so a payment only counts
    while the loan was assigned to this officer. That is the honest reading -
    a book handed over mid-year does not take its past collections with it -
    and it is also the only one the feeds support, since the assignment is a
    current value and not a history.
    """
    today = datetime.date.today()
    since = since or datetime.date(today.year, 1, 1)
    until = until or today

    rows = _rows(
        """
        SELECT COALESCE(SUM(COALESCE(r.principal_paid,0)
                            + COALESCE(r.interest_paid,0)), 0) AS collected,
               COUNT(*)                                        AS payments,
               COUNT(DISTINCT r.loan_account_number)           AS loans_paying,
               MAX(r.transaction_date)                         AS latest
        FROM loan_repayments r
        JOIN loans l
          ON TRIM(l.loan_account_no::text) = TRIM(r.loan_account_number)
        WHERE LOWER(TRIM(COALESCE(l.delay_officer,''))) = LOWER(TRIM(%s))
          AND r.transaction_date >= %s
          AND r.transaction_date < %s
        """, [officer_code, since, until + datetime.timedelta(days=1)])
    if not rows:
        return {"collected": 0.0, "payments": 0, "loans_paying": 0,
                "latest": None, "from": since, "to": until, "feed": False}

    row = rows[0]
    return {
        "collected": float(row["collected"] or 0),
        "payments": int(row["payments"] or 0),
        "loans_paying": int(row["loans_paying"] or 0),
        "latest": row["latest"], "from": since, "to": until, "feed": True,
    }


def contribution(officer_code, since=None, until=None):
    """One officer's whole picture → book, collected, promises, diary.

    The four numbers a team leader actually compares officers on, and none of
    them is typed by the officer being measured.
    """
    from . import ptp
    from .models import Collection, PromiseToPay

    today = datetime.date.today()
    since = since or datetime.date(today.year, 1, 1)
    until = until or today

    carrying = book(officer_code)
    money = collected(officer_code, since, until)
    promises = ptp.kept_rate(
        PromiseToPay.objects.filter(
            collection_officer_code__iexact=(officer_code or "").strip()))

    # Diary activity. Not a measure of success on its own - a hundred calls
    # that collect nothing is not a good month - but a kept rate with no
    # calls behind it is a different story from one with two hundred, and a
    # team leader needs to be able to tell them apart.
    diary = Collection.objects.filter(
        collection_officer_code__iexact=(officer_code or "").strip(),
        recording_date__gte=since, recording_date__lte=until)
    entries = diary.count()
    contacted = diary.filter(
        contactibility__iregex=r"^(contacted|reachable)$").count()

    recovered = None
    if carrying["arrears"]:
        # What share of the arrears handed to this officer has come in.
        recovered = round(money["collected"] / carrying["arrears"], 4)

    return {
        "collection_officer_code": officer_code,
        "from": since, "to": until,
        "book": carrying,
        "collected": money,
        "promises": promises,
        "diary": {
            "entries": entries, "contacted": contacted,
            "not_contacted": entries - contacted,
            "contact_rate": (round(contacted / entries, 4)
                             if entries else None),
        },
        #: Collected over the arrears being carried. The headline number, and
        #: None rather than nought when the officer carries no arrears - a
        #: ratio with nothing underneath it is not a nought.
        "recovery_rate": recovered,
    }


def leaderboard(codes=None, since=None, until=None):
    """Every officer who holds delinquent loans → a row each.

    Ordered by what came in, which is the thing the desk is for. An officer
    with no assignment at all is left out rather than shown as a zero: they
    are not underperforming, they have not been given a book.
    """
    if codes is None:
        rows = _rows(
            """
            SELECT DISTINCT TRIM(l.delay_officer) AS code
            FROM loans l
            WHERE COALESCE(TRIM(l.delay_officer), '') <> ''
              AND COALESCE(l.overdue_days, 0) > 0
            """, [])
        codes = [row["code"] for row in rows if row.get("code")]

    out = [contribution(code, since, until) for code in codes]
    out.sort(key=lambda row: row["collected"]["collected"], reverse=True)
    return out
