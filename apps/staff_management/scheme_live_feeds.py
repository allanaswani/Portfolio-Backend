"""Scheme card lines read live, once proven against what the desk loaded.

Only disbursements can be tested. The desk's rule is in its own extract: net
drawdown on ``drawdown_daily``, Commercial above a 9.5% rate, credited to the
scheme RM. On the extract ``SCHEME RM`` follows ``ABBVR`` with no conflicts, but
``ABBVR`` is the desk's own column and is nowhere in the warehouse. So the extract
is kept when the Scheme workbooks are loaded, and a drawdown is placed by customer,
or by an employer code that only ever meant one RM.

Other lines stay on the desk's figures: deposit growth is a typed list of inflows,
and sign-ups, reconciliation, FID, audit and call-backs are desk returns.

A proven line must match on every stored month it has a figure for. It must also
pass with a mapping learned only from earlier months, because a customer first
drawing after the desk's last extract is the one that gets missed.
"""

from __future__ import annotations

import datetime

MAP_KIND = "scheme_drawdown_map"
STORE_KIND = "scheme_live_feeds"
EXTRACT_SHEET = "Scheme Drawdowns Portfolio"
#: The desk's own rule: RATE = IF(FINAL_INTEREST > 9.5, "Commercial", ...)
COMMERCIAL_ABOVE = 9.5
NON_SCHEME = "NON-SCHEME"
DSR = "DSR"
PASS_SHARE = 0.9
RELATIVE = 0.001
MIN_POINTS = 2
#: Of a month's desk money, how much a mapping from earlier months must find.
NEW_CUSTOMER_SHARE = 0.95
COMMERCIAL_KPI = "scheme_commercial_disbursement"
TOTAL_KPI = "scheme_total_disbursement"
KPIS = {COMMERCIAL_KPI: "Total Disbursement - Commercial", TOTAL_KPI: "Total Disbursement"}
PROBE_TIMEOUT_MS = 600_000
LIVE_TIMEOUT_MS = 20_000


def _id(value):
    return str(value if value is not None else "").split(".")[0].strip().upper()


def capture(actuals_workbook, loaded_by=""):
    """Keep who the desk credited each drawdown to → rows kept (0 if no extract)."""
    from .workbook_cards import save_file

    if EXTRACT_SHEET not in actuals_workbook.sheetnames:
        return 0
    rows = actuals_workbook[EXTRACT_SHEET].iter_rows(values_only=True)
    head = [str(h).strip() for h in next(rows, [])]
    try:
        cust, code, rm, when = (head.index(n) for n in
                                ("CUST_ID", "FKGD_CATEGORY", "SCHEME RM", "DRAWDOWN_DT"))
    except ValueError:
        return 0
    kept = []
    for row in rows:
        if len(row) <= max(cust, code, rm, when) or not row[rm] or not row[cust]:
            continue
        month = getattr(row[when], "month", None)
        kept.append([_id(row[cust]), _id(row[code]), str(row[rm]).strip().upper(), month])
    save_file(MAP_KIND, {"rows": kept}, "scheme extract", loaded_by)
    return len(kept)


def build_map(rows, before_month=None):
    """→ (customer → RM, employer code → RM), the code only if it meant one RM."""
    customers, codes = {}, {}
    for cust, code, rm, month in rows:
        if before_month is not None and (month is None or month >= before_month):
            continue
        counts = customers.setdefault(cust, {})
        counts[rm] = counts.get(rm, 0) + 1
        codes.setdefault(code, set()).add(rm)
    by_customer = {c: max(v, key=lambda rm: (v[rm], rm)) for c, v in customers.items()}
    by_code = {c: next(iter(v)) for c, v in codes.items() if len(v) == 1}
    return by_customer, by_code


def place(cust, code, by_customer, by_code):
    return by_customer.get(_id(cust)) or by_code.get(_id(code))


def _drawdowns(start, end, timeout_ms):
    """[(cust, employer code, rate, money)] from the desk's own source."""
    from .bo_live_feeds import _rows

    return _rows(
        """SELECT cust_id, fkgd_category, final_interest, COALESCE(net_drawdown, 0)
           FROM drawdown_daily WHERE drawdown_dt >= %s AND drawdown_dt < %s""",
        [start, end], timeout_ms)


def totals(rows, maps):
    """{RM: {"commercial", "all"}} plus {"__all__": every scheme drawdown}."""
    by_customer, by_code = maps
    out = {"__all__": {"commercial": 0.0, "all": 0.0}}
    for cust, code, rate, money in rows:
        rm = place(cust, code, by_customer, by_code)
        if not rm or rm == NON_SCHEME:
            continue
        money = float(money or 0)
        commercial = rate is not None and float(rate) > COMMERCIAL_ABOVE
        for key in (rm, "__all__"):
            slot = out.setdefault(key, {"commercial": 0.0, "all": 0.0})
            slot["all"] += money
            if commercial:
                slot["commercial"] += money
    return out


def rm_key(name, known):
    """A card's name → the extract's RM. Names differ (Dennis Kimathi on the card,
    Dennis Mutembei on the extract), so a first name that only one RM has."""
    first = (str(name or "").split() or [""])[0].upper()
    found = [rm for rm in known if rm not in (NON_SCHEME, DSR, "__all__")
             and rm.split()[:1] == [first]]
    return found[0] if len(found) == 1 else None


def figure(kpi, name, figures):
    """One card's reading out of :func:`totals` → a number or None."""
    if kpi == TOTAL_KPI:
        return figures["__all__"]["all"]
    rm = rm_key(name, figures)
    return figures[rm]["commercial"] if rm else None


def same(desk, got):
    return got is not None and abs(desk - got) <= max(1.0, RELATIVE * abs(desk))


def _desk_points(year, up_to):
    """[(kpi, month number, name, desk figure)] off the stored cards."""
    from .models import SchemeScorecard

    out = []
    for card in SchemeScorecard.objects.filter(month__year=year, month__month__lte=up_to):
        for line in (card.card or {}).get("lines", []):
            actual = line.get("actual")
            if (line.get("kpi") in KPIS and not line.get("empty")
                    and isinstance(actual, (int, float)) and actual):
                out.append((line["kpi"], card.month.month, card.staff_name, float(actual)))
    return out


def _new_customer_share(kpi, points, kept, year, latest, out):
    """Of the latest month's desk money, how much a mapping from earlier months finds."""
    now = {n: v for k, m, n, v in points if k == kpi and m == latest}
    before = {n: v for k, m, n, v in points if k == kpi and m == latest - 1}
    want = sum(v - before.get(n, 0.0) for n, v in now.items())
    if latest <= 1 or not want:
        out(f"  {KPIS[kpi]}: no earlier month to learn from, so new customers are untested.")
        return None
    first = datetime.date(year, latest, 1)
    end = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    figures = totals(_drawdowns(first, end, PROBE_TIMEOUT_MS), build_map(kept, before_month=latest))
    got = sum(figure(kpi, n, figures) or 0.0 for n in now)
    return got / want


def probe(year, month, out=print):
    """Compare the warehouse with every stored month up to ``month`` → results stored."""
    from .workbook_cards import save_file, saved

    mapping = saved(MAP_KIND)
    if not mapping or not mapping.get("rows"):
        out("Load the Scheme template and actuals once more under Scorecards, so the "
            "desk's drawdown list is kept. Then run this again.")
        return {}
    kept = mapping["rows"]
    points = _desk_points(year, month)
    if not points:
        out(f"No Scheme disbursement figures are stored up to {year}-{month:02d}.")
        return {}
    latest = max(m for _, m, _, _ in points)
    maps = build_map(kept)
    results = {}
    readings = {}
    for kpi, title in KPIS.items():
        mine = [p for p in points if p[0] == kpi]
        hits = 0
        for _, m, name, desk in mine:
            if m not in readings:
                end = (datetime.date(year, m, 28) + datetime.timedelta(days=4)).replace(day=1)
                readings[m] = totals(_drawdowns(datetime.date(year, 1, 1), end,
                                                PROBE_TIMEOUT_MS), maps)
            got = figure(kpi, name, readings[m])
            if same(desk, got):
                hits += 1
            else:
                said = f"{got:,.0f}" if got is not None else "nothing"
                out(f"    {name}, month {m}: desk {desk:,.0f}, warehouse {said}")
        match = hits / len(mine) if mine else 0.0
        enough = len(mine) >= MIN_POINTS and match >= PASS_SHARE
        found = _new_customer_share(kpi, points, kept, year, latest, out) if enough else None
        live = enough and found is not None and found >= NEW_CUSTOMER_SHARE
        share = f"{found:.0%}" if found is not None else "not tested"
        out(f"  {title}: {hits} of {len(mine)} figures match; new-customer test {share}"
            f" -> {'LIVE' if live else 'stays on the desk figure'}")
        results[kpi] = {"name": title, "sheet": "Disbursments", "match": match,
                        "people": len(mine), "month": f"{year}-{latest:02d}", "live": live,
                        "how": ("net drawdown, placed by the desk's customer list or a "
                                "single-RM employer code")}
    save_file(STORE_KIND, results, f"probe {year}-{month:02d}", "probe")
    out("Other Scheme lines stay on the desk's figures: deposit growth is a typed list of "
        "inflows, and the rest are desk returns or have no history to test against.")
    return results


def proven():
    from .workbook_cards import saved

    return saved(STORE_KIND) or {}


def live_value(kpi, name, as_at):
    """Year to date for one card's line, or None."""
    from django.core.cache import cache

    from .workbook_cards import saved

    key = f"scheme_live:{as_at.isoformat()}"
    figures = cache.get(key)
    if figures is None:
        mapping = saved(MAP_KIND) or {}
        if not mapping.get("rows"):
            return None
        try:
            rows = _drawdowns(datetime.date(as_at.year, 1, 1),
                              as_at + datetime.timedelta(days=1), LIVE_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 - a slow warehouse leaves the desk's figure
            return None
        figures = totals(rows, build_map(mapping["rows"]))
        cache.set(key, figures, 6 * 3600)
    return figure(kpi, name, figures)
