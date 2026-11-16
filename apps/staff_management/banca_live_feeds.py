"""Live figures for the Banca DSR cards, read the way the desk's own report reads
them - ``hfcb_Insurance_weighted_sales_report.py`` (the Insurance weighted sales
report, which fills the insurance actuals template).

Which template sheet each reader stands for, and the report's rule for it
(year to date, January to the month asked):

* life_volume                - life policies, one per (seller, R-number), first
                               month kept (the report sorts on the 'Mon-YYYY' text)
* life_excl_nawiri_imarika   - paid premiums, life, product not NAWIRI / IMARIKA /
                               Imarika Investment
* nawiri_imarika             - paid premiums, life, product one of those three
* hfcb_elimu_akiba           - paid premiums, life, product HFCB ELIMU or Akiba
* gi_insurance               - paid premiums, non-life, product not Medical
* medical_insurance          - paid premiums, non-life, product Medical
* gwp_collection             - paid / total premiums over the year, rounded as the
                               report rounds (to 0.01 %)
* accounts                   - funded accounts: customer funded, not closed,
                               account CTO >= 2,000, by account-open month
* disbursements              - drawdowns counted, staff loans and SBP0001 out

Policies: ``insurance_policies``, one row per R-number + start date, the
report year's rows; premium type from ``premium_types_mapping``; BRITAM
HOLDINGS PLC premiums spread over the months left in the year, as the report
does. A seller counts only if their code is on ``branch_employee_dmc_data``
(the report's merge drops everyone else).

Persistency, NPS, training and property sales are not in that report: those
lines stay the desk's figure.

Nothing here reaches a card until ``banca_feed_probe`` has shown, for a month
the desk filled, that the reader gives the desk's figures.
"""
from __future__ import annotations

import calendar
import datetime

STORE_KIND = "banca_live_feeds"
#: A sheet reads live once this share of the Banca DSRs match the desk.
PASS_SHARE = 0.7
#: Counts must agree exactly; money within this share (or 1 shilling).
TOLERANCE = 0.01

NAWIRI_IMARIKA = ("NAWIRI", "IMARIKA", "Imarika Investment")
ELIMU_AKIBA = ("HFCB ELIMU", "Akiba")
ACCRUE_INSURED = ("BRITAM HOLDINGS PLC",)
#: The report's sales-code corrections on drawdowns.
DRAWDOWN_FIXES = {"AL3116": "AKL3116", "SC3568": "SJC3568", "PK3453": "PMK3453",
                  "AOL3199": "AL3199"}
#: zero_out_return_salespersons_in_same_role: Jan-Jun zeroed for these codes.
ZEROED_TO_JUNE = ("DSR309",)
SHEETS = ("life_volume", "life_excl_nawiri_imarika", "nawiri_imarika",
          "hfcb_elimu_akiba", "gi_insurance", "medical_insurance",
          "gwp_collection", "accounts", "disbursements")
COUNTS = ("life_volume", "accounts", "disbursements")


def _frame(sql, params=None):
    import pandas as pd
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def _roster_codes():
    return set(_frame("SELECT DISTINCT trim(sales_code::text) AS c FROM "
                      "branch_employee_dmc_data WHERE sales_code IS NOT NULL")["c"])


def _ytd(frame, month_col, year, month, codes_col="sales_code", value=None, how="sum"):
    """{code: total over Jan..month of ``year``} - the report's pivot 'total'."""
    import pandas as pd

    if frame.empty:
        return {}
    keep = frame[(frame[month_col].dt.year == year) & (frame[month_col].dt.month <= month)]
    if keep.empty:
        return {}
    zero = keep[codes_col].isin(ZEROED_TO_JUNE) & (keep[month_col].dt.month <= 6)
    keep = keep[~zero]
    grouped = keep.groupby(codes_col)
    if how == "count":
        out = grouped[value].count() if value else grouped.size()
    else:
        out = grouped[value].sum()
    return {str(k): float(v) for k, v in out.items() if pd.notna(k)}


def _policies(as_at):
    """The report's bancassurance frame for ``as_at``'s year."""
    import pandas as pd

    year = as_at.year
    frame = _frame("""
        WITH cte AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY CONCAT(r_number, starting_date)
                                         ORDER BY r_number, starting_date DESC) AS rn
            FROM insurance_policies)
        SELECT r_number, insured, product, starting_date, premiums AS total_premiums,
               paid AS paid_premiums, code
        FROM cte WHERE rn = 1 AND year IN (%s)""", [str(year)])
    if frame.empty:
        return frame
    types = _frame("SELECT product, life_policy_check FROM premium_types_mapping")
    frame["product"] = frame["product"].astype(str).str.strip()
    frame["starting_date"] = pd.to_datetime(frame["starting_date"], errors="coerce")
    frame["code"] = frame["code"].apply(
        lambda x: str(x).replace(" ", "") if isinstance(x, str) else x)
    frame = frame.merge(types, on="product", how="left")
    paid = pd.to_numeric(frame["paid_premiums"], errors="coerce").fillna(0.0)
    days = calendar.monthrange(as_at.year, as_at.month)[1]
    fraction = as_at.day / days

    def accrued(row_paid, insured, start):
        if insured not in ACCRUE_INSURED:
            return row_paid
        if pd.isna(start) or as_at.month < start.month:
            return 0.0
        each = row_paid / (12 - start.month + 1)
        return (as_at.month - start.month) * each + each * fraction

    frame["paid_premiums"] = [accrued(p, i, s) for p, i, s in
                              zip(paid, frame["insured"], frame["starting_date"])]
    frame["total_premiums"] = pd.to_numeric(frame["total_premiums"],
                                            errors="coerce").fillna(0.0)
    roster = _roster_codes()
    frame["sales_code"] = frame["code"].apply(
        lambda c: str(c) if c is not None and str(c) in roster else None)
    return frame


def figures(as_at):
    """Every reader for ``as_at`` (a month end, or today) → {sheet: {code: value}}."""
    import pandas as pd

    year, month = as_at.year, as_at.month
    out = {s: {} for s in SHEETS}
    p = _policies(as_at)
    if not p.empty:
        life = p[p["life_policy_check"] == "life"]
        non_life = p[p["life_policy_check"] == "non-life"]
        # The report: sort_values('month') on the 'Mon-YYYY' text, then the first
        # row per (seller, R-number). Reproduced with a stable sort on that text.
        first = life.assign(_m=life["starting_date"].dt.strftime("%b-%Y")) \
            .sort_values("_m", kind="mergesort") \
            .drop_duplicates(subset=["sales_code", "r_number"], keep="first")
        out["life_volume"] = _ytd(first, "starting_date", year, month,
                                  value="r_number", how="count")
        out["life_excl_nawiri_imarika"] = _ytd(
            life[~life["product"].isin(NAWIRI_IMARIKA)], "starting_date", year, month,
            value="paid_premiums")
        out["nawiri_imarika"] = _ytd(life[life["product"].isin(NAWIRI_IMARIKA)],
                                     "starting_date", year, month, value="paid_premiums")
        out["hfcb_elimu_akiba"] = _ytd(life[life["product"].isin(ELIMU_AKIBA)],
                                       "starting_date", year, month, value="paid_premiums")
        out["gi_insurance"] = _ytd(non_life[non_life["product"] != "Medical"],
                                   "starting_date", year, month, value="paid_premiums")
        out["medical_insurance"] = _ytd(non_life[non_life["product"] == "Medical"],
                                        "starting_date", year, month, value="paid_premiums")
        # GWP collection: over every policy row of the year, no month cut.
        g = p[p["sales_code"].notna()].groupby("sales_code")[
            ["paid_premiums", "total_premiums"]].sum()
        out["gwp_collection"] = {
            str(k): float(round(r.paid_premiums / r.total_premiums * 100, 2) / 100)
            for k, r in g.iterrows() if r.total_premiums}

    a = _frame("""SELECT sale_code, customer_segment, cust_cto, account_cto, curr_24_bal,
                         account_status, acc_open_date FROM daily_sales_accounts_with_cto""")
    if not a.empty:
        a = a[~a["customer_segment"].isin(["STAFF", "INTERNAL ACCOUNTS"])].fillna(0)
        for col in ("cust_cto", "account_cto", "curr_24_bal"):
            a[col] = pd.to_numeric(a[col], errors="coerce").fillna(0.0)
        a["sales_code"] = a["sale_code"].astype(str).str.replace(" ", "", regex=False)
        a["acc_open_date"] = pd.to_datetime(a["acc_open_date"], errors="coerce")
        funded = a[((a["cust_cto"] > 0) | (a["curr_24_bal"] > 0))
                   & (a["account_status"] != "CLOSED") & (a["account_cto"] >= 2000)]
        out["accounts"] = _ytd(funded, "acc_open_date", year, month, how="count")

    d = _frame("""SELECT salesperson, customer_segment, description, drawdown_dt,
                         net_drawdown FROM drawdown_daily
                  WHERE drawdown_dt >= %s AND drawdown_dt < %s""",
               [datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1)])
    if not d.empty:
        d = d[(d["customer_segment"] != "STAFF") & (d["description"] != "Staff")
              & (d["salesperson"] != "SBP0001")].copy()
        d["salesperson"] = d["salesperson"].replace(DRAWDOWN_FIXES)
        d["sales_code"] = d["salesperson"].astype(str).str.strip()
        d.loc[d["salesperson"].isna(), "sales_code"] = None
        d["drawdown_dt"] = pd.to_datetime(d["drawdown_dt"], errors="coerce")
        out["disbursements"] = _ytd(d, "drawdown_dt", year, month,
                                    value="net_drawdown", how="count")
    return out


def same(sheet, desk, got):
    if sheet in COUNTS:
        return abs(desk - got) < 0.5
    if sheet == "gwp_collection":
        return abs(desk - got) <= 0.0001
    return abs(desk - got) <= max(1.0, TOLERANCE * abs(desk))


def probe(year, month, out=print, who=None):
    """Compare every reader with the stored Banca cards of a month the desk
    filled; store which sheets read live → {sheet: result}."""
    from .models import BancaScorecard
    from .workbook_cards import save_file

    first = datetime.date(year, month, 1)
    cards = list(BancaScorecard.objects.filter(month=first))
    if not cards:
        out(f"No Banca DSR cards are stored for {first:%b %Y} - load the desk's "
            f"workbooks first.")
        return {}
    end = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) \
        - datetime.timedelta(days=1)
    read = figures(end)
    found = {}
    for sheet in SHEETS:
        rows = []
        for c in cards:
            line = next((ln for ln in (c.card or {}).get("lines", [])
                         if ln.get("sheet") == sheet and ln.get("actual") is not None), None)
            if line is None:
                continue
            desk = float(line["actual"])
            got = read[sheet].get(c.sales_code.upper(), 0.0)
            rows.append((c.sales_code, c.staff_name, desk, float(got),
                         bool(same(sheet, desk, float(got)))))
        if not rows:
            continue
        # Plain Python numbers: the result is stored as JSON (a numpy bool
        # from a pandas figure crashed the first save, 16 Nov 2026).
        share = float(sum(1 for r in rows if r[4]) / len(rows))
        live = bool(share >= PASS_SHARE and any(r[2] for r in rows))
        found[sheet] = {"match": share, "live": live, "month": f"{year}-{month:02d}",
                        "people": len(rows)}
        out(f"  {sheet:26} {share:6.1%} of {len(rows)} DSRs give the desk's figure "
            f"-> {'LIVE' if live else 'stays on the desk figure'}")
        for code, name, desk, got, ok in rows:
            if who and who.upper() not in (code.upper(), name.upper()):
                continue
            if who or not ok:
                out(f"      {'ok ' if ok else '   '}{code:8} {name[:22]:22} desk "
                    f"{desk:>16,.2f}  warehouse {got:>16,.2f}")
    save_file(STORE_KIND, found, f"probe {year}-{month:02d}", "probe")
    out(f"Reading live: {', '.join(s for s, v in found.items() if v['live']) or 'none'}.")
    return found


#: Sheets read live by decision, not by the proof - with why. The desk's
#: figure for these is known to be wrong, so it is neither the test nor a floor.
DECIDED = {
    "nawiri_imarika": ("16 Nov 2026, Administration: the desk's nawiri_imarika "
                       "sheet is a copy of hfcb_elimu_akiba for all 35 DSRs (the "
                       "products do not overlap), so the warehouse figure by the "
                       "insurance report's rule is used"),
}
#: The template's own life-premium growth constants (constants!G1, G2), read
#: and checked against all 35 October cards on 16 Nov 2026. Used only for a
#: card stored before the cards kept them.
TEMPLATE_GROWTH = (1.5, 12.0)


def proven():
    from .workbook_cards import saved

    found = {k: v for k, v in (saved(STORE_KIND) or {}).items() if v.get("live")}
    for sheet, why in DECIDED.items():
        found[sheet] = {"live": True, "decided": why}
    return found


def live_payload(record, as_at):
    """A month after the newest stored card, with the proven sheets read to
    ``as_at`` → a payload, or None. Other lines keep the desk's latest figure,
    scored against their own month's target, and say so."""
    import copy

    from . import banca_cards as bc
    from django.core.cache import cache

    sheets = proven()
    if (not sheets or as_at.year != record.month.year
            or as_at.replace(day=1) <= record.month):
        return None
    data = copy.deepcopy(record.card or {})
    rate, months = data.get("growth") or TEMPLATE_GROWTH
    key = f"banca_live:{as_at.isoformat()}"
    read = cache.get(key)
    if read is None:
        read = figures(as_at)
        cache.set(key, read, 3 * 3600)
    changed = {}
    for line in data.get("lines", []):
        sheet = line.get("sheet")
        if sheet not in sheets:
            continue
        value = read.get(sheet, {}).get(record.sales_code.upper(), 0.0)
        # A running total cannot fall below what the desk recorded.
        if sheet != "gwp_collection" and sheet not in DECIDED \
                and bc._num(line.get("actual")) and value < line["actual"]:
            value = line["actual"]
        rule = bc.YTD_RULE[line["row"]]
        spec = bc.Line(row=line["row"], perspective="", category="", description="",
                       weight=line["weight"], target=line.get("fy_target"), rule=rule,
                       sheet=sheet)
        ytd = bc.ytd_target(spec, line.get("fy_target"), as_at.month, record.joined,
                            rate, months)
        score = bc.score(value, ytd)
        line.update(ytd_target=ytd, actual=value, error="", empty=False, score=score,
                    weighted=score * line["weight"])
        changed[line["kpi"]] = line
    if not changed:
        return None
    weights = sum(ln["weight"] for ln in data["lines"])
    total = sum(ln["weighted"] for ln in data["lines"]) / weights if weights else 0.0
    stored = type("Stored", (), {})()
    stored.card, stored.total, stored.month = data, total, record.month
    stored.sales_code, stored.staff_name = record.sales_code, record.staff_name
    stored.reports_to, stored.joined = record.reports_to, record.joined
    payload = bc.card_payload(stored)
    for perspective in payload["perspectives"]:
        for ln in perspective["lines"]:
            if ln["kpi_code"] in changed:
                ln["as_at"] = f"live, as at {as_at:%d %b %Y} (the insurance report's rules)"
                ln["as_at_date"] = as_at.isoformat()
            elif ln["weight"]:
                ln["as_at"] = f"the desk's latest figure ({record.month:%b %Y})"
    payload.update({
        "live": True, "live_lines": len(changed),
        "period": {"label": f"{as_at:%B %Y}", "as_at": as_at.isoformat()},
        "months_loaded": sorted({*payload["months_loaded"], f"{as_at:%Y-%m}"}),
        "coverage_note": "",
        "how_scored": (f"{len(changed)} line(s) read today's figures by the insurance "
                       f"report's own rules; the others show the desk's latest figure "
                       f"({record.month:%B %Y}). Scored by the Banca DSR workbook's "
                       f"targets, caps and weights."),
    })
    return payload
