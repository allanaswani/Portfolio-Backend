"""Branch managers' figures read live from the warehouse - only once proven.

A branch manager's card reads the branch manager's own row on the sales
actuals template, and that row is the BRANCH's figure, not the sum of the
branch's RMs: Rehani's August deposits there are 24.16bn, its RMs' rows add
to -0.52bn. The card then takes the 2025 base off it (24.16bn - 20.80bn is
the 3.36bn growth on the card). So the live month needs branch totals, and a
per-person reader can never give them.

The totals are the bank's own reports' totals, rule for rule, from the ETL
repo - not a reading of the tables of my own:

* deposits and loans - ``daily_balance_movement.py`` (the daily balance
  movement report): the branch is the ACCOUNT's ``brn_code`` through that
  report's ``get_branch_name`` table, never the customer's home branch;
  deposits keep the segments in ``zone_deposit_segments_order`` and the
  account buckets SA/CA/FD/STAFF of ``product_mapping``; loans keep Zones
  A-C and the same segments; every negative balance counts as nought
  (``replace_negative_with_zero``). The template's sheet is called
  Deposit_Growth_RETAIL and the report has a retail cut too, so both are
  tried.
* disbursement - ``drawdown_report_correct.py``: ``drawdown_daily`` this
  year by ``unit_code``, net drawdown, without staff segments, staff
  products or GLK1744.

Each is still proven before it is used: :func:`probe` compares it, branch by
branch, with the branch managers' rows for a month the desk has closed, and
only a definition giving the desk's figure for :data:`PASS_SHARE` of the
branches is stored.

    manage.py bo_feed_probe --month 2026-08 --branches
"""

from __future__ import annotations

import datetime
import re

PASS_SHARE = 0.9
#: Relative: a branch's balance is billions, so a cent-level match is the
#: wrong test; 0.5% still tells one definition from another.
TOLERANCE = 0.005
PROBE_TIMEOUT_MS = 600_000
LIVE_TIMEOUT_MS = 60_000
STORE_KIND = "bb_live_feeds"

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
          "oct", "nov", "dec")

# ── the daily balance movement report's own tables ─────────────────────────
#: get_branch_name, daily_balance_movement.py
BRANCH_OF_CODE = {
    300: "MOMBASA", 310: "MOMBASA", 22: "NANYUKI", 260: "THIKA ROAD MALL-TRM",
    24: "MACHAKOS", 23: "KOMAROCK", 230: "BURUBURU", 280: "WESTLANDS",
    25: "EMBU", 400: "NAKURU", 410: "ELDORET", 520: "MERU", 600: "KISUMU",
    200: "REHANI", 270: "SAMEER BUSINESS PARK", 17: "NAIVASHA", 500: "THIKA",
    16: "KITENGELA", 510: "NYERI", 20: "RIVERROAD", 19: "HURLINGHAM",
    210: "HURLINGHAM", 250: "RONGAI", 220: "HARAMBEE AVE", 100: "HEADOFFICE",
    109: "VIRTUAL",
}
#: map_code_to_zone - the codes in Zones A-C (the loans' branch filter).
ZONED_CODES = (300, 310, 22, 260, 24, 23, 230, 280, 25, 400, 410, 520, 600,
               200, 270, 17, 500, 16, 510, 20, 19, 210, 250, 220)
#: zone_deposit_segments_order
SEGMENTS = (
    "INSTITUTIONAL BANKING", "FINANCIAL INSTITUTIONS", "PROJECT FINANCE",
    "LARGE ENTERPRISES", "MEDIUM ENTERPRISES", "SMALL ENTERPRISES",
    "ULTIMATE", "SCHEME", "STANDARD", "MASS", "VIRTUAL", "STAFF", "DIASPORA",
    "NON RESIDENT KENYANS", "DIASPORA PERSONAL BANKING",
    "DIASPORA ULTIMATE BANKING", "DIASPORA BUSINESS BANKING",
    "New-Unsegmented")
#: The two of those whose get_banking_segment (FI, PF) is not in the
#: report's retail_segments - the retail cut leaves them out.
NOT_RETAIL = ("FINANCIAL INSTITUTIONS", "PROJECT FINANCE")
#: acc_bucket_order
BUCKETS = ("SA", "CA", "FD", "STAFF")
#: process_dataframe: this account is remapped to INTERNAL ACCOUNTS.
INTERNAL_ACCOUNT = "7040000288"
#: custodial_manual_row: prod 31210 is a CA whatever product_mapping says.
CUSTODIAL = "31210"

#: The template's spelling of a branch → the report's, where they differ
#: (the three the first probe could not place).
TEMPLATE_BRANCH = {"harambee": "harambeeave",
                   "sameerpark": "sameerbusinesspark",
                   "trm": "thikaroadmalltrm"}


def branch_key(name):
    text = re.sub(r"\bbranch\b", "", str(name or "").lower())
    key = re.sub(r"[^a-z0-9]", "", text)
    return TEMPLATE_BRANCH.get(key, key)


def _codes_of(branch):
    key = branch_key(branch)
    return [str(c) for c, name in BRANCH_OF_CODE.items()
            if branch_key(name) == key]


def _rows(sql, params, timeout_ms):
    from django.db import connection, transaction

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
            cur.execute(sql, params)
            return cur.fetchall()


def _deposits(column, retail):
    segments = [s for s in SEGMENTS if not (retail and s in NOT_RETAIL)]
    return (f"""
        SELECT trim(d.brn_code::text),
               SUM(GREATEST(COALESCE(d.{column}, 0), 0))
        FROM daily_balance_movement d
        LEFT JOIN (SELECT DISTINCT ON (trim(code::text))
                          trim(code::text) AS code, product_map
                   FROM product_mapping ORDER BY trim(code::text)) p
          ON p.code = trim(d.prod_id::text)
        WHERE (CASE WHEN trim(d.acc_num::text) = %s THEN 'INTERNAL ACCOUNTS'
                    ELSE COALESCE(d.customer_segment, 'New-Unsegmented')
               END) = ANY(%s)
          AND (CASE WHEN trim(d.prod_id::text) = %s THEN 'CA'
                    ELSE p.product_map END) = ANY(%s)
        GROUP BY 1""",
            [INTERNAL_ACCOUNT, segments, CUSTODIAL, list(BUCKETS)])


def _loans(column):
    return (f"""
        SELECT trim(d.brn_code::text),
               SUM(GREATEST(COALESCE(d.{column}, 0), 0))
        FROM loan_daily_balance_movement d
        WHERE trim(d.brn_code::text) = ANY(%s)
          AND d.customer_segment = ANY(%s)
        GROUP BY 1""",
            [[str(c) for c in ZONED_CODES], list(SEGMENTS)])


def _drawdowns(year, up_to):
    return ("""
        SELECT trim(unit_code::text), SUM(COALESCE(net_drawdown, 0))
        FROM drawdown_daily
        WHERE drawdown_dt >= %s AND drawdown_dt < %s
          AND COALESCE(customer_segment, 'MASS') NOT ILIKE '%%STAFF%%'
          AND COALESCE(product_desc, '') NOT ILIKE '%%STAFF%%'
          AND COALESCE(salesperson, '') NOT ILIKE '%%GLK1744%%'
        GROUP BY 1""", [datetime.date(year, 1, 1), up_to])


#: sheet → [(label, kind, options)]. ``balance`` reads a month column (or,
#: live, yester_1_bal); ``ytd`` sums from 1 January to the month's end.
DEFINITIONS = {
    "Deposit_Growth_Retail": [
        ("deposits, all segments (daily balance movement report)",
         "deposits", {"retail": False}),
        ("deposits, retail cut (daily balance movement report)",
         "deposits", {"retail": True}),
    ],
    "Asset_Growth": [
        ("loans, Zones A-C (daily balance movement report)", "loans", {}),
    ],
    "Asset_Drawdown": [
        ("net drawdowns YTD by unit_code (drawdown report)", "drawdowns", {}),
    ],
}


def _sql(feed, year, month, live=False, today=None):
    if feed["kind"] == "drawdowns":
        if live:
            up_to = today + datetime.timedelta(days=1)
        else:
            up_to = (datetime.date(year, month, 28)
                     + datetime.timedelta(days=4)).replace(day=1)
        return _drawdowns(year, up_to)
    column = ("yester_1_bal" if live
              else f"{MONTHS[month - 1]}_{year % 100:02d}_bal")
    if feed["kind"] == "deposits":
        return _deposits(column, feed["retail"])
    return _loans(column)


def _by_code(feed, year, month, timeout_ms, live=False, today=None):
    sql, params = _sql(feed, year, month, live=live, today=today)
    return {str(code): float(value or 0)
            for code, value in _rows(sql, params, timeout_ms)}


def _branch_total(totals, branch):
    codes = _codes_of(branch)
    if not codes or not any(c in totals for c in codes):
        return None
    return sum(totals.get(c, 0.0) for c in codes)


def _branch_managers():
    """([holder], the sales actuals template) or (None, None)."""
    from .workbook_cards import BRANCH_BUSINESS, SPECS, holders, saved

    spec = SPECS[BRANCH_BUSINESS]
    book, actuals = saved(spec.files[0]), saved(spec.files[1])
    if book is None or actuals is None:
        return None, None
    return [h for h in holders(book) if h.sales_code], actuals


def _desk(actuals, sheet, code, month):
    for row in (actuals.get(sheet) or [])[1:]:
        if len(row) > 1 and str(row[1] or "").strip().upper() == code:
            v = row[6 + month - 1] if 6 + month - 1 < len(row) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
    return None


def probe(year, month, out=print):
    from .workbook_cards import save_file, saved

    people, actuals = _branch_managers()
    if people is None:
        out("Load the branch business scorecards workbook and the sales "
            "actuals template (2026_Actual_Template.xlsx) first - the probe "
            "compares against them.")
        return {}
    found = {}
    for sheet, definitions in DEFINITIONS.items():
        targets = [(h, _desk(actuals, sheet, h.sales_code, month))
                   for h in people]
        targets = [(h, t) for h, t in targets if t]
        if not targets:
            out(f"  {sheet:24} the template has no {MONTHS[month - 1]} "
                f"figure for any branch manager - skipped")
            continue
        for label, kind, options in definitions:
            feed = dict(options, sheet=sheet, kind=kind, label=label)
            try:
                totals = _by_code(feed, year, month, PROBE_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001 - the reason is the answer
                out(f"  {sheet:24} {label}: could not be read - {exc}")
                continue
            rows, hits = [], 0
            for h, t in targets:
                got = _branch_total(totals, h.branch)
                ok = got is not None and abs(got - t) <= abs(t) * TOLERANCE
                hits += ok
                rows.append((str(h.branch), t, got, ok))
            share = hits / len(targets)
            verdict = "LIVE" if share >= PASS_SHARE else "not good enough"
            out(f"  {sheet:24} {share:6.1%} of {len(targets):3} branches "
                f"match - {label}  -> {verdict}")
            for branch, desk, got, ok in rows:
                out(f"      {'ok ' if ok else '   '}{branch:20} desk "
                    f"{desk:>20,.2f}   warehouse "
                    f"{'none' if got is None else format(got, '>20,.2f')}")
            if share >= PASS_SHARE and (
                    sheet not in found or share > found[sheet]["match"]):
                found[sheet] = dict(feed, match=share,
                                    month=f"{year}-{month:02d}")

    stored = {k: v for k, v in (saved(STORE_KIND) or {}).items()
              if k in DEFINITIONS}
    stored.update(found)
    save_file(STORE_KIND, stored, f"probe {year}-{month:02d}", "probe")
    out(f"{len(found)} branch sheet(s) now read live: "
        f"{', '.join(sorted(found)) or 'none'}. The rest stay waiting on "
        f"the live card.")
    return found


def live_value(feed, branch, as_at):
    """Today's branch figure on one proven feed, or None."""
    from django.core.cache import cache

    key = (f"bb_live:{feed['sheet']}:{feed['kind']}:"
           f"{int(bool(feed.get('retail')))}:{branch_key(branch)}:"
           f"{as_at.isoformat()}")
    hit = cache.get(key)
    if hit is not None:
        return hit if hit != "none" else None
    try:
        totals = _by_code(feed, as_at.year, as_at.month, LIVE_TIMEOUT_MS,
                          live=True, today=as_at)
        if feed["kind"] != "drawdowns" and not any(totals.values()):
            # The report's own fallback: a yester_1_bal column the ETL has
            # not filled yet reads as the month's column.
            totals = _by_code(feed, as_at.year, as_at.month, LIVE_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 - a slow warehouse is a waiting line
        return None
    value = _branch_total(totals, branch)
    cache.set(key, value if value is not None else "none", 6 * 3600)
    return value


def proven():
    from .workbook_cards import saved

    return saved(STORE_KIND) or {}
