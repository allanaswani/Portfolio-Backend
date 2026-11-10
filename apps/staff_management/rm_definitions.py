"""RM lines no report computes: the proof tries every candidate, the card uses the winner.

PAR, Deposit Growth and Errors (loan applications) have no ETL script that
works them out per RM, and the card's readers did not give the desk's figures
(PAR 15%, Deposit Growth 19%, Errors 0% on the September 2026 proof). Tried
from the laptop first: the loan officer's book on the lake gave PAR for 4 of 68;
the Weighted TAT Dashboard's loans error rate equals the desk's Errors for 7 of
83 - so neither is the desk's rule.

So each line has a set of candidate definitions, each computed for every RM at
once. The sales proof (sales_live_feeds.probe) scores every candidate against
the desk's figures for the month and stores the one that reproduces at least
PASS_SHARE of them; from then the card reads that line with it. A line no
candidate reproduces keeps its reader, and the proof log shows how close each
came.
"""
from __future__ import annotations

import calendar
import datetime

STORE = "rm_definitions"
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
          "nov", "dec")
TIMEOUT_MS = 180_000


def _rows(sql, params):
    from django.db import connection, transaction

    with transaction.atomic(), connection.cursor() as cur:
        from .feed_cache import timeout

        cur.execute(f"SET LOCAL statement_timeout = {timeout(TIMEOUT_MS)}")
        cur.execute(sql, params)
        return cur.fetchall()


def _end(year, month):
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


_ALLOCATED = ("SELECT DISTINCT UPPER(REPLACE(TRIM(sales_code), ' ', '')) AS code, "
              "cust_id::text AS cust FROM retail_allocated_portfolio "
              "WHERE sales_code IS NOT NULL")


# ── PAR ─────────────────────────────────────────────────────────────────────
_OVERDUE = {
    "arrears": "COALESCE(l.total_arrears, 0)",
    "1+ days": "CASE WHEN COALESCE(l.days_in_arrears, 0) > 0 THEN {bal} ELSE 0 END",
    "31+ days": "CASE WHEN COALESCE(l.days_in_arrears, 0) > 30 THEN {bal} ELSE 0 END",
    "91+ days": "CASE WHEN COALESCE(l.days_in_arrears, 0) > 90 THEN {bal} ELSE 0 END",
}
_BALANCES = ("capital_balance", "total_capital_balance", "euro_book_balance")


def par(year, month):
    """{candidate: {CODE: ratio}} over ``loans`` at the month's last eom_date."""
    at = _rows("SELECT MAX(eom_date)::date FROM loans WHERE eom_date::date <= %s",
               [_end(year, month)])[0][0]
    out = {}
    if at is None:
        return out
    for book in ("allocated", "officer"):
        for over_name, tpl in _OVERDUE.items():
            for bal in _BALANCES:
                over = tpl.format(bal=f"COALESCE(l.{bal}, 0)")
                if book == "allocated":
                    sql = (f"WITH b AS ({_ALLOCATED}) SELECT b.code, SUM({over}), "
                           f"SUM(COALESCE(l.{bal}, 0)) FROM loans l JOIN b "
                           f"ON b.cust = l.cust_id::text WHERE l.eom_date::date = %s "
                           f"GROUP BY 1")
                else:
                    sql = (f"SELECT UPPER(REPLACE(TRIM(l.account_officer), ' ', '')), "
                           f"SUM({over}), SUM(COALESCE(l.{bal}, 0)) FROM loans l "
                           f"WHERE l.eom_date::date = %s GROUP BY 1")
                out[f"PAR: {book} book, {over_name} / {bal}"] = {
                    code: float(o) / float(b) for code, o, b in _rows(sql, [at])
                    if code and b}
    return out


# ── Deposit growth: the month's balance less December's ─────────────────────
def deposits(year, month):
    """{candidate: {CODE: growth}} off daily_balance_movement's month columns."""
    now = f"{MONTHS[month - 1]}_{year % 100:02d}_bal"
    base = f"dec_{(year - 1) % 100:02d}_bal"
    # The month still open has no month-end column yet: the latest balance.
    today = datetime.date.today()
    if (year, month) == (today.year, today.month):
        now = "yester_1_bal"
    growth = f"SUM(COALESCE(d.{now}, 0)) - SUM(COALESCE(d.{base}, 0))"
    out = {}
    for staff in (True, False):
        where = "" if staff else "AND COALESCE(d.customer_segment, '') NOT ILIKE '%%STAFF%%'"
        label = "all segments" if staff else "staff segment out"
        for book, code_sql, join in (
                ("rm_code", "UPPER(REPLACE(TRIM(d.rm_code), ' ', ''))", ""),
                ("sale_code", "UPPER(REPLACE(TRIM(d.sale_code), ' ', ''))", ""),
                ("allocated", "b.code", f"JOIN ({_ALLOCATED}) b ON b.cust = d.cust_cif::text")):
            sql = (f"SELECT {code_sql}, {growth} FROM daily_balance_movement d {join} "
                   f"WHERE 1=1 {where} GROUP BY 1")
            out[f"Deposits: {book}, {label}"] = {
                code: float(v or 0) for code, v in _rows(sql, []) if code}
    return out


# ── Errors: loan applications sent back ─────────────────────────────────────
def errors(year, month):
    """{candidate: {CODE: rate}} off iapply_loan_tat by SellerCode."""
    acted = ('CASE WHEN "ActionDate"::text ~ \'^[0-9]{4}-[0-9]{2}-[0-9]{2}\' '
             'THEN "ActionDate"::text::timestamp END')
    flags = {"decision": 'COALESCE("DecisionType", \'\') ILIKE \'%%return%%\'',
             "status": 'COALESCE("StatusTo", \'\') ILIKE \'%%returned%%\''}
    first = datetime.date(year, month, 1)
    spans = {"year": (datetime.date(year, 1, 1), _end(year, month)),
             "month": (first, _end(year, month))}
    out = {}
    for flag_name, flag in flags.items():
        for span_name, (start, end) in spans.items():
            sql = f"""
                WITH t AS (
                    SELECT UPPER(REPLACE(TRIM("SellerCode"::text), ' ', '')) AS code,
                           "ApplicationId" AS app, ({flag}) AS returned, {acted} AS at
                    FROM iapply_loan_tat)
                SELECT code,
                       COUNT(*) FILTER (WHERE returned)::float / NULLIF(COUNT(*), 0),
                       COUNT(DISTINCT app) FILTER (WHERE returned)::float
                           / NULLIF(COUNT(DISTINCT app), 0)
                FROM t WHERE at >= %s AND at < %s::date + 1 AND code <> ''
                GROUP BY 1"""
            rows = _rows(sql, [start, end])
            out[f"Errors: returned actions / actions, {span_name}, by {flag_name}"] = {
                c: float(a) for c, a, _ in rows if a is not None}
            out[f"Errors: applications returned / applications, {span_name}, by {flag_name}"] = {
                c: float(b) for c, _, b in rows if b is not None}
    return out


# ── Bancassurance Premiums: which part of the book ──────────────────────────
def banca(year, month):
    """{candidate: {CODE: premiums}} from bancassurance_report.py's paid premiums
    (bb_live_feeds._banca_policies), split by its own VIC / life classification.
    All paid premiums read 11.6m against the desk's 4.0m for one RM in
    September, so the desk counts a part of the book."""
    from .bb_live_feeds import _banca_policies

    parts = {}
    for _branch, code, kind, value in _banca_policies(year, month, TIMEOUT_MS):
        if code:
            row = parts.setdefault(code, {"vic_life": 0.0, "vic_non_life": 0.0,
                                          "non_vic": 0.0, None: 0.0})
            row[kind if kind in row else None] += value
    pick = {
        "Banca: all paid premiums": lambda r: sum(r.values()),
        "Banca: non-VIC": lambda r: r["non_vic"],
        "Banca: non-VIC and unclassified": lambda r: r["non_vic"] + r[None],
        "Banca: all but VIC life": lambda r: sum(r.values()) - r["vic_life"],
        "Banca: all but VIC non-life": lambda r: sum(r.values()) - r["vic_non_life"],
        "Banca: VIC (life and non-life)": lambda r: r["vic_life"] + r["vic_non_life"],
        "Banca: VIC life and non-VIC": lambda r: r["vic_life"] + r["non_vic"],
        "Banca: VIC non-life and non-VIC": lambda r: r["vic_non_life"] + r["non_vic"],
        "Banca: unclassified only": lambda r: r[None],
    }
    return {name: {code: fn(row) for code, row in parts.items()}
            for name, fn in pick.items()}


#: Template sheet (as _key gives it) → its candidates, and the card's actual key.
SHEETS = {"par": (par, "par"),
          "depositgrowthretail": (deposits, "deposit_growth"),
          "loanapplicationerrors": (errors, "loan_application_errors")}
#: A line that shares its sheet with lines already read correctly (VIC Premium is
#: live on the same Banca sheet) is keyed by its own measure instead.
LINES = {"bancassurancepremiums": (banca, "banca_paid_all")}
CANDIDATES = {**SHEETS, **LINES}


def chosen():
    """{sheet key: candidate name} the proof has stored."""
    from .workbook_cards import saved

    return saved(STORE) or {}


def value(sheet, code, as_at):
    """The chosen candidate's figure for one RM → float, None (no figure), or the
    feed_cache PREPARING sentinel while it is read in the background."""
    from .feed_cache import cached

    name = chosen().get(sheet)
    if not name:
        return None
    compute, _key = CANDIDATES[sheet]
    found = cached(f"rm_definition:{sheet}:{as_at.year}-{as_at.month:02d}",
                   lambda: compute(as_at.year, as_at.month).get(name, {}))
    if found is None:
        return "preparing"
    return found.get(code.replace(" ", "").upper())


def choose(sheet, people, year, month, close, out=print):
    """Score every candidate on ``people`` [(CODE, desk)] → (share, name) of the
    best, and store it when it reaches the proof's pass share."""
    from .bo_live_feeds import PASS_SHARE
    from .workbook_cards import save_file, saved

    compute, _key = CANDIDATES[sheet]
    try:
        candidates = compute(year, month)
    except Exception as exc:  # noqa: BLE001 - reported, the line keeps its reader
        out(f"    candidates could not be read: {type(exc).__name__}: {exc}")
        return None
    ranked = []
    for name, figures in candidates.items():
        hits = sum(1 for code, desk in people
                   if figures.get(code) is not None and close(desk, figures[code]))
        ranked.append((hits / len(people) if people else 0.0, name))
    ranked.sort(reverse=True)
    for share, name in ranked[:3]:
        out(f"    {share:6.1%}  {name}")
    if ranked and ranked[0][0] >= PASS_SHARE:
        stored = saved(STORE) or {}
        stored[sheet] = ranked[0][1]
        save_file(STORE, stored, f"proof {year}-{month:02d}", "proof")
        out(f"    -> stored: the card now reads this line with it")
    return ranked[0] if ranked else None
