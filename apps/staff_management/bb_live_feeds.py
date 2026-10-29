"""Branch managers' figures read live from the warehouse - only once proven.

A branch manager's card reads the branch manager's own row on the sales
actuals template, and that row is the BRANCH's figure, not the sum of the
branch's RMs: Rehani's August deposits there are 24.16bn, its RMs' rows add
to -0.52bn. The card then takes the 2025 base off it (24.16bn - 20.80bn is
the 3.36bn growth on the card). So the live month needs branch totals, and a
per-person reader can never give them.

As with the tellers (bo_live_feeds), nothing is assumed. :func:`probe` takes
a month the desk has closed, totals the warehouse per branch every way that
is plausible, and compares each total with the branch manager's row for that
month. A definition that gives the desk's figure for at least
:data:`PASS_SHARE` of the branches is stored; one that does not is reported
and left off.

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
LIVE_TIMEOUT_MS = 20_000
STORE_KIND = "bb_live_feeds"

#: The template sheet → the balance table and the segments the bank's own
#: branch pages leave out of it (apps/branch_portfolio/views.py).
BALANCE_SHEETS = {
    "Deposit_Growth_Retail": ("daily_balance_movement",
                              ("INTERNAL ACCOUNTS", "VIRTUAL")),
    "Asset_Growth": ("loan_daily_balance_movement", ("INTERNAL ACCOUNTS",)),
}
#: Columns that may name a branch on the balance table itself.
BRANCH_COLUMNS = ("branch", "branch_name", "brn_name", "cust_branch",
                  "account_branch", "acct_branch")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
          "oct", "nov", "dec")


def branch_key(name):
    text = re.sub(r"\bbranch\b", "", str(name or "").lower())
    return re.sub(r"[^a-z0-9]", "", text)


def _rows(sql, params, timeout_ms):
    from django.db import connection, transaction

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
            cur.execute(sql, params)
            return cur.fetchall()


def _columns(table):
    return {c for (c,) in _rows(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %s", [table], LIVE_TIMEOUT_MS)}


def _sql(feed, column):
    """Per-branch total of one balance column → SQL with params."""
    table, segments = BALANCE_SHEETS[feed["sheet"]]
    amount = (f"SUM(d.{column}) FILTER (WHERE d.{column} > 0)"
              if feed["positive_only"] else f"SUM(d.{column})")
    where = ("d.customer_segment <> ALL(%s)" if feed["exclude_segments"]
             else "TRUE")
    params = [list(segments)] if feed["exclude_segments"] else []
    if feed["group"] == "hf_customer":
        # One branch per customer: hf_customer can repeat a cust_id, and a
        # repeat would count that customer's balance twice.
        return (f"""SELECT c.branch, {amount}
                    FROM {table} d
                    JOIN (SELECT DISTINCT ON (cust_id) cust_id, branch
                          FROM hf_customer ORDER BY cust_id) c
                      ON c.cust_id = d.cust_cif
                    WHERE {where}
                    GROUP BY 1""", params)
    return (f"""SELECT d.{feed['group']}, {amount} FROM {table} d
                WHERE {where} GROUP BY 1""", params)


def _branch_managers():
    """[(holder, the branch manager's row on the template)]."""
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
    column = f"{MONTHS[month - 1]}_{year % 100:02d}_bal"
    found = {}
    for sheet, (table, _segments) in BALANCE_SHEETS.items():
        have = _columns(table)
        if column not in have:
            out(f"  {sheet:24} {table} has no {column} column - skipped")
            continue
        groups = ["hf_customer"] + [c for c in BRANCH_COLUMNS if c in have]
        targets = [(h, _desk(actuals, sheet, h.sales_code, month))
                   for h in people]
        targets = [(h, t) for h, t in targets if t]
        best = None
        for group in groups:
            for positive_only in (True, False):
                for exclude in (True, False):
                    feed = {"sheet": sheet, "group": group,
                            "positive_only": positive_only,
                            "exclude_segments": exclude}
                    sql, params = _sql(feed, column)
                    try:
                        totals = {}
                        for name, value in _rows(sql, params,
                                                 PROBE_TIMEOUT_MS):
                            key = branch_key(name)
                            totals[key] = totals.get(key, 0.0) + float(
                                value or 0)
                    except Exception as exc:  # noqa: BLE001
                        out(f"  {sheet:24} by {group}: {exc}")
                        continue
                    hits, unmatched = 0, []
                    for h, t in targets:
                        got = totals.get(branch_key(h.branch))
                        if got is None:
                            unmatched.append(str(h.branch))
                        elif abs(got - t) <= abs(t) * TOLERANCE:
                            hits += 1
                    share = hits / len(targets) if targets else 0.0
                    if best is None or share > best["match"]:
                        best = dict(feed, match=share, people=len(targets),
                                    unmatched=unmatched,
                                    sample=[(str(h.branch), t, totals.get(
                                        branch_key(h.branch)))
                                        for h, t in targets[:3]])
        if best is None:
            continue
        verdict = "LIVE" if best["match"] >= PASS_SHARE else "not good enough"
        out(f"  {sheet:24} {best['match']:6.1%} of {best['people']:3} "
            f"branches match - {table} by {best['group']}"
            f"{', balances > 0 only' if best['positive_only'] else ''}"
            f"{', internal segments out' if best['exclude_segments'] else ''}"
            f"  -> {verdict}")
        for branch, desk, got in best["sample"]:
            out(f"      {branch:20} desk {desk:,.2f}   warehouse "
                f"{got if got is None else format(got, ',.2f')}")
        if best["unmatched"]:
            out(f"      branch names the warehouse does not have: "
                f"{', '.join(sorted(set(best['unmatched'])))}")
        if best["match"] >= PASS_SHARE:
            found[sheet] = {k: best[k] for k in (
                "sheet", "group", "positive_only", "exclude_segments",
                "match")}
            found[sheet]["month"] = f"{year}-{month:02d}"

    stored = saved(STORE_KIND) or {}
    stored.update(found)
    save_file(STORE_KIND, stored, f"probe {year}-{month:02d}", "probe")
    out(f"{len(found)} branch sheet(s) now read live: "
        f"{', '.join(sorted(found)) or 'none'}. The rest stay waiting on "
        f"the live card.")
    return found


def live_value(feed, branch, as_at):
    """Today's branch total on one proven feed, or None."""
    from django.core.cache import cache

    key = f"bb_live:{feed['sheet']}:{branch_key(branch)}:{as_at.isoformat()}"
    hit = cache.get(key)
    if hit is not None:
        return hit if hit != "none" else None
    sql, params = _sql(feed, "yester_1_bal")
    try:
        totals = {}
        for name, value in _rows(sql, params, LIVE_TIMEOUT_MS):
            k = branch_key(name)
            totals[k] = totals.get(k, 0.0) + float(value or 0)
    except Exception:  # noqa: BLE001 - a slow warehouse is a waiting line
        return None
    value = totals.get(branch_key(branch)) or None
    cache.set(key, value if value is not None else "none", 6 * 3600)
    return value


def proven():
    from .workbook_cards import saved

    return saved(STORE_KIND) or {}
