"""Active Customers and Digital Adoption, from the registration data.

The desk's own answer, and a better one than the lake's. The routine
registration report (``routine_registration_data.py`` in the ETL) builds a
row per customer carrying a 1/0 flag for every month:

    total_trx_active_dec_2025 ... total_trx_active_dec_2026
    mobile_active_dec_2025    ... mobile_active_dec_2026

That is exactly the measure these two cards state - "2 month active" is a
flag in one month and the month before it - and unlike
``delta.gold_db.active_channels`` it reaches back to **December 2025**, so
the prior-year count a 20% growth target is applied to can be read rather
than left as "could not be read".

Why the columns are discovered, not listed
──────────────────────────────────────────
The month set grows: the report adds a column per month as the year runs.
Hard-coding them would mean this file needed editing every month and would
silently stop finding new ones in between. So the columns are read from
``information_schema`` and the month is parsed out of the NAME. A column
shape nobody anticipated is skipped and reported rather than guessed at.

The table's name is also taken as found: the desk calls it
``registation_data``, which is missing an R, and a table that is renamed to
the correct spelling later should not break this. Both are tried.
"""

from __future__ import annotations

import datetime
import re

#: The spellings this has been seen under, in the order they are tried. The
#: first is the desk's own, missing an R.
TABLE_NAMES = ("registation_data", "registration_data",
               "routine_registration_data")

#: ``<prefix>_<month>_<year>`` - the two flag families the report produces.
#: ANY transaction for the active-customer line; the mobile app for digital
#: adoption, which is what "digital" means on these cards.
PREFIX_ACTIVE = "total_trx_active"
PREFIX_DIGITAL = "mobile_active"

#: What this report calls the customer, in the order they are tried.
#:
#: The month columns were always discovered; the customer key was assumed to
#: be ``cust_id``. If the report spells it anything else the join raised, and
#: the card reported "This figure could not be read just now" - which names
#: neither the column nor the table, so it survived weeks of looking.
CUSTOMER_KEYS = ("cust_id", "cust_cif", "customer_id", "customer_no",
                 "cif", "cif_no")

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

#: The report writes some months out in full and some short, and has changed
#: its mind before - "march"/"mar", "june"/"jun", "sept"/"sep". Matched on
#: the first three letters, which is stable across all of them.
_COLUMN = re.compile(r"^(?P<prefix>[a-z_]+?)_(?P<month>[a-z]+)_(?P<year>\d{4})$")


def parse_column(name, prefix):
    """``total_trx_active_sept_2026`` → ``date(2026, 9, 1)``, or None."""
    match = _COLUMN.match((name or "").strip().lower())
    if match is None or match.group("prefix") != prefix:
        return None
    month = _MONTHS.get(match.group("month")[:3])
    if month is None:
        return None
    try:
        return datetime.date(int(match.group("year")), month, 1)
    except ValueError:
        return None


def _columns_of(table):
    """Every column on that table → list of names, or [] if it is not there."""
    from django.db import connection, transaction

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s",
                [table])
            return [row[0] for row in cur.fetchall()]
    except Exception:  # noqa: BLE001 - absence is an answer, not a crash
        return []


def customer_key(table):
    """What this table calls the customer → column name, or "".

    Discovered, like the month columns, rather than assumed.
    """
    columns = {c.lower() for c in _columns_of(table)}
    for name in CUSTOMER_KEYS:
        if name in columns:
            return name
    return ""


def find_table():
    """The registration table as this database actually spells it → name or "".

    Only a table that carries the flag columns counts: a table of the right
    name with none of them is not this feed, and reporting it as found would
    turn a missing feed into an empty one.
    """
    for table in TABLE_NAMES:
        columns = _columns_of(table)
        if any(parse_column(c, PREFIX_ACTIVE) for c in columns):
            return table
    return ""


def month_columns(table, prefix):
    """``{date: column}`` for one flag family on that table."""
    found = {}
    for column in _columns_of(table):
        month = parse_column(column, prefix)
        if month is not None:
            found[month] = column
    return found


def coverage():
    """What this feed spans → a dict, for telling a gap from a stale load."""
    table = find_table()
    if not table:
        return {"table": "", "months": [], "complete_pairs": [],
                "first_month": None, "last_month": None}

    months = sorted(month_columns(table, PREFIX_ACTIVE))
    known = set(months)
    pairs = [m for m in months if _previous(m) in known]
    return {
        "table": table, "months": months, "complete_pairs": pairs,
        "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "digital_months": sorted(month_columns(table, PREFIX_DIGITAL)),
    }


def _previous(month):
    return (month.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)


def two_month_active(sales_code, year, digital=False, upto=None):
    """Customers on this RM's book active in TWO consecutive months.

    → ``{year: (count, as_at)}`` for every year the feed covers, or
    ``{"error": reason}``.

    The same contract the other readers use, so the card does not care which
    feed answered.

    One query, built from the columns that are actually there: a pair is a
    month whose flag is set AND whose previous month's flag is set, and the
    latest qualifying pair within each year is the one reported - so a figure
    read in the first days of a month does not collapse to nought because the
    new month has barely started.
    """
    from django.db import connection, transaction

    from services import portfolio_service as svc

    table = find_table()
    if not table:
        return {"error": (
            "the registration data is not on this database, so two months of "
            "activity cannot be tested")}

    prefix = PREFIX_DIGITAL if digital else PREFIX_ACTIVE
    columns = month_columns(table, prefix)
    if not columns:
        return {"error": (
            f"{table} carries no {prefix} columns, so "
            f"{'digital ' if digital else ''}activity cannot be read")}

    pairs = [(month, columns[month], columns[_previous(month)])
             for month in sorted(columns)
             if _previous(month) in columns]
    if not pairs:
        return {"error": (
            f"{table} has no two CONSECUTIVE months of "
            f"{'digital ' if digital else ''}activity to compare")}

    # One SELECT, a column pair per month. The column names come from
    # information_schema, so they are real identifiers rather than anything a
    # caller supplied - quoted all the same, because several of them would
    # otherwise fold.
    # Two counts per month: this RM's, and the bank's.
    #
    # The bank's is not decoration. The report creates a column for every
    # month of the year in advance, so a column existing does not mean that
    # month has happened - without this the latest column always won and
    # every card reported nought as at December. The latest month ANY
    # customer is active in is how far the feed actually reaches.
    #
    # The column names come from information_schema, so they are real
    # identifiers rather than anything a caller supplied - quoted all the
    # same, because several of them would otherwise fold.
    key = customer_key(table)
    if not key:
        return {"error": (
            f"{table} has none of the customer columns this reads - "
            f"{', '.join(CUSTOMER_KEYS)} - so its rows cannot be matched to "
            f"an RM's book")}

    # ACTIVE = the customer's last transaction falls in EITHER of the two
    # months, not in both.
    #
    # This was AND, which is a stricter measure than the bank's: it counted
    # only customers who turned up in two consecutive months and dropped
    # anyone who transacted in one of them. The business states it as "the
    # last customer transaction in the last 2 months", and Lydia Apanja's
    # signed card bears that out - 358 active against a target of 116, far
    # more than a both-months rule over her book could produce.
    # ``bank_`` counts THIS month alone, deliberately, while ``mine_`` counts
    # the two-month window. The bank figure is only used to decide how far
    # the feed actually REACHES, and under an OR window a month with no rows
    # at all still inherits the month before it - so measuring reach on the
    # window would report a figure for a month that has not happened, which
    # is the fault this file already guards against for the columns the
    # report creates a year in advance.
    counts = ",\n               ".join(
        f'COUNT(*) FILTER (WHERE k.cust_id IS NOT NULL '
        f'AND (COALESCE(r."{this}", 0) > 0 '
        f'OR COALESCE(r."{prev}", 0) > 0)) AS "mine_{month:%Y_%m}", '
        f'COUNT(*) FILTER (WHERE COALESCE(r."{this}", 0) > 0) '
        f'AS "bank_{month:%Y_%m}"'
        for month, this, prev in pairs)

    sql = f"""
        WITH book AS ({svc.RM_BOOK}
        )
        SELECT {counts}
        FROM {table} r
        LEFT JOIN book k
               ON k.cust_id = NULLIF(
                      regexp_replace(r."{key}"::text, '\\D', '', 'g'), '')::bigint
    """

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [sales_code.strip()])
            row = cur.fetchone()
            names = [c[0] for c in cur.description]
    except Exception as exc:  # noqa: BLE001 - a feed that cannot be read
        # must not blank the card, and nothing is reported as nought on the
        # strength of a read that did not finish.
        #
        # The REASON is carried. This used to return a bare "could not be
        # read", which reaches the card as "This figure could not be read
        # just now" and reaches whoever has to fix it as nothing at all -
        # a missing column, a renamed table and a dead connection all look
        # identical. The person's own card still shows the gentle wording;
        # the Administration screens and scorecard_coverage print this.
        return {"error": f"the registration data could not be read: "
                         f"{type(exc).__name__}: {exc}".strip()}

    if row is None:
        return {}

    mine, bank = {}, {}
    for name, value in zip(names, row):
        parts = (name or "").split("_")
        if len(parts) != 3:
            continue
        which, year_text, month_text = parts
        try:
            when = datetime.date(int(year_text), int(month_text), 1)
        except ValueError:
            continue
        (mine if which == "mine" else bank)[when] = int(value or 0)

    # How far the feed REACHES: the latest month any customer at all is
    # active in. The report creates a column for every month of the year in
    # advance, so a column existing does not mean that month has happened -
    # without this the latest column always won and every card reported
    # nought as at December.
    reached = [month for month in sorted(bank) if bank[month] > 0]
    if not reached:
        return {}
    furthest = reached[-1]

    out = {}
    for month in sorted(mine, reverse=True):
        # ``upto`` is the month END a card for a NAMED MONTH is for. Without
        # it the latest pair in the year always won, so a September card was
        # given a September-October pair - a figure from after the period the
        # card reports. The guard sits beside the ``furthest`` one because it
        # is the same kind of rule: do not report a month that is not this
        # card's to report.
        if month > furthest or month.year in out:
            continue
        if upto is not None and month > upto:
            continue
        # As at the END of the month the pair closes on, because that is the
        # month the figure is complete for.
        last_day = (month.replace(day=28) + datetime.timedelta(days=4))
        last_day = last_day.replace(day=1) - datetime.timedelta(days=1)
        out[month.year] = (mine[month], last_day)
    return out
