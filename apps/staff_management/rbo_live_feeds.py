"""Live figures for the Retail Back Office workbook's individual lines.

The workbook's "individual" lines read its actuals template (2026_Actual_
Template_Retail_Back_office.xlsx) by name, one sheet per line (column K). That
template is not loaded anywhere; these readers give the same figure from the
sources the platform already reads for the other cards:

* ``training_hrs`` - HR's training return, year to date, by PF
  (live_scorecard ``training_hours``);
* ``leave_management`` - Aruti's leave balance report, the share cleared
  (``leave_cleared``);
* ``VIC_life`` / ``VIC_non_life`` - VIC (Britam) policies with paid premiums,
  counted, by sales code (``vic_life_count`` / ``vic_non_life_count``) - the
  card's target is policies (2 a year), not premiums;
* ``HFDI_Volume`` / ``HFDI_Value`` - HFDI and affordable-housing property sold,
  units and value (``property_units`` / ``property_value``);
* ``Commercial_Contactability`` - the CX survey's contactability
  (``cx_contactability``);
* ``Commercial_Accounts`` - accounts opened, year to date (``new_accounts``);
* ``Commercial_CRM`` - the CX team's CRM logs return, the person's running
  total (cx_returns);
* the credit analysts' lines - ``TOTAL_TAT``, ``RTS`` and the turnaround per
  product category (``UBL``, ``SME_below_20M``, ``SME_above_20M``, ``UPL``,
  ``SP``, ``TRADE``, ``IPF``, ``ASSET_FINANCE``) - the iApply loan TAT report
  (loan_tat_iapply_automation.py) read by the user who acted:
  its ``tat_vol_rts_role_view`` is, per ActionUserName and month, the mean of
  the non-zero step times and the count of returned actions (DecisionType
  containing "return"). The categories are the desk's own mapping
  (2026_loan_tat_mapping.xlsx, column I), SME split at an approved amount of
  KES 20,000,000.

None of these is taken on trust. :func:`prove` reads each against the desk's
own figures for the month the workbook was last run (the cached cells, see
workbook_cards.rbo_desk_actuals) and keeps, per line, how many people it gave
the desk's figure for. A line whose reader gave the desk's figure for every
person with one (:data:`PASS_SHARE`) is LIVE: from the next month it replaces
the desk's figure. A line not proven yet does not replace a desk figure; it
fills only a person the desk has no figure for, and says how far it matched.
"""
from __future__ import annotations

import datetime
import logging

log = logging.getLogger(__name__)

STORE_KIND = "rbo_live_feeds"
PASS_SHARE = 0.9
TOLERANCE = 0.01
RELATIVE = 0.005

ENGINE_KEYS = {
    "training_hrs": "training_hours",
    "leave_management": "leave_cleared",
    "VIC_life": "vic_life_count",
    "VIC_non_life": "vic_non_life_count",
    "HFDI_Volume": "property_units",
    "HFDI_Value": "property_value",
    "Commercial_Contactability": "cx_contactability",
    "Commercial_Accounts": "new_accounts",
}
CRM_FEEDS = {"Commercial_CRM"}

#: 2026_loan_tat_mapping.xlsx, ProductCategory -> credit_analyst_mapping,
#: verbatim (Sheet1 D:I).
PRODUCT_CATEGORY = {
    "AF": "Asset Finance loans", "AP": "Asset Finance loans",
    "BD": "Unsecured Business Loans", "BL": "sme", "CD": "sme", "CF": "trade",
    "CL": "Unsecured Business Loans", "DE": "sme", "HL": "Secured Personal",
    "IP": "ipf", "LC": "trade", "LG": "trade", "LL": "Asset Finance loans",
    "ML": "Secured Personal", "PL": "Secured Personal",
    "PU": "Unsecured Personal Loan", "RI": "Unsecured Personal Loan",
    "SA": "Unsecured Personal Loan", "SP": "sme",
}
SME_SPLIT = 20_000_000
#: The card's template sheet -> the analyst category it reads.
CATEGORY_FEEDS = {
    "UBL": "Unsecured Business Loans",
    "SME_below_20M": "sme<20m", "SME_above_20M": "sme>=20m",
    "UPL": "Unsecured Personal Loan", "SP": "Secured Personal",
    "TRADE": "trade", "IPF": "ipf", "ASSET_FINANCE": "Asset Finance loans",
}
IAPPLY_FEEDS = {"TOTAL_TAT", "RTS"} | set(CATEGORY_FEEDS)
#: How a line's figure can be taken off a month of actions; the proof keeps
#: whichever gives the desk's figures.
#: "<span>/<rows>": the month's own figure or the year to date; every row
#: under the name or only the person's own actions.
IAPPLY_DEFINITIONS = ("month/own", "month/all", "year/own", "year/all")
DEFINITIONS = {feed: IAPPLY_DEFINITIONS for feed in ("TOTAL_TAT", "RTS", *CATEGORY_FEEDS)}


def handles(feed):
    return feed in ENGINE_KEYS or feed in CRM_FEEDS or feed in IAPPLY_FEEDS


def _month_end(year, month):
    nxt = datetime.date(year + (month == 12), month % 12 + 1, 1)
    return nxt - datetime.timedelta(days=1)


# ── iApply, by the user who acted ─────────────────────────────────────────

def _columns():
    from . import loan_tat_seller as lts

    extra = ["ActionUserName", "DecisionType", "ProductCategory", "ApprovedAmount"]
    return list(lts.COLUMNS) + [c for c in extra if c not in lts.COLUMNS]


def _category(product, approved):
    code = str(product or "").strip().upper()
    category = PRODUCT_CATEGORY.get(code)
    if category == "sme":
        try:
            amount = float(str(approved).replace(",", ""))
        except (TypeError, ValueError):
            return None
        return "sme>=20m" if amount >= SME_SPLIT else "sme<20m"
    return category


def user_month(rows, year, month):
    """The report's role view for one month → {ACTION USER NAME (upper):
    {"tat": days, "rts": count, "actions": count, "by_category": {category:
    days}}}."""
    from . import loan_tat_seller as lts

    cols = _columns()
    month_rows = lts._month_steps(rows, year, month, columns=cols)
    if month_rows is None or month_rows.empty:
        return {}
    month_rows = month_rows.assign(
        category=[_category(p, a) for p, a in zip(month_rows["ProductCategory"],
                                                   month_rows["ApprovedAmount"])],
        returned=month_rows["DecisionType"].str.lower().str.contains("return", na=False))
    def figures(group):
        entry = {"tat": lts._mean_non_zero(group["TAT"]),
                 "rts": int(group["returned"].sum()),
                 "actions": int(len(group)), "by_category": {}}
        for category, part in group.groupby("category", sort=True):
            if category:
                entry["by_category"][category] = lts._mean_non_zero(part["TAT"])
        return entry

    out = {}
    for name, group in month_rows.groupby("ActionUserName", sort=True):
        key = " ".join(str(name).split()).upper()
        if not key or key in ("NONE", "NAN"):
            continue
        # "all": every row under the name, as the report's sheet sums them;
        # "own": only the actions the person took, without the rows the
        # report generates for an application's current status.
        out[key] = {"all": figures(group), "own": figures(group[~group["generated"]])}
    return out


def iapply_users(year, month, timeout_ms=180_000, wait=False):
    """:func:`user_month`, read once and kept (feed_cache) → dict, or None
    while it is being read in the background. ``wait`` reads it now."""
    from . import loan_tat_seller as lts
    from .feed_cache import cached

    def compute():
        cols = _columns()
        return user_month(lts._rows(year, month, timeout_ms, columns=cols), year, month)

    key = f"rbo_iapply_users:{year}-{month:02d}"
    if wait:
        # Read now AND keep it, so the cards have it too: the proof used to
        # read every month and keep none, and the cards said "being read".
        from .feed_cache import waiting

        with waiting():
            return cached(key, compute)
    return cached(key, compute)


def _user_entry(users, name):
    from .live_scorecard import names_agree

    found = [v for k, v in (users or {}).items() if names_agree(k, name)]
    return found[0] if len(found) == 1 else None


def iapply_value(feed, name, year, month, definition="month/own", wait=False):
    """(value, label, why): the analyst's figure for ``feed`` under one of
    :data:`IAPPLY_DEFINITIONS`. A year-to-date turnaround is the mean of the
    months' figures."""
    span_kind, _, which = (definition or "month/own").partition("/")
    which = which or "own"
    months = [month] if span_kind == "month" else list(range(1, month + 1))
    values = []
    for m in months:
        users = iapply_users(year, m, wait=wait)
        if users is None:
            return None, "", (f"the iApply loan TAT report for "
                              f"{datetime.date(year, m, 1):%B %Y} is being read")
        entry = (_user_entry(users, name) or {}).get(which)
        if entry is None:
            continue
        if feed == "RTS":
            values.append(entry["rts"])
        elif feed == "TOTAL_TAT":
            if entry["tat"]:
                values.append(entry["tat"])
        else:
            v = entry["by_category"].get(CATEGORY_FEEDS[feed])
            if v:
                values.append(v)
    span = (f"{datetime.date(year, month, 1):%B %Y}" if span_kind == "month"
            else f"year to {datetime.date(year, month, 1):%b %Y}")
    label = f"iApply loan TAT report, by the user who acted, {span}"
    if feed == "RTS":
        return float(sum(values)), label, ""
    if not values:
        # No action of theirs in the period: no turnaround to score - not 0
        # days, which the card's =IF(H<=G,1,...) would score in full.
        return None, "", (f"no iApply action by {name} in {span} on the loan "
                          f"TAT report, so there is no turnaround to score")
    return float(sum(values) / len(values)), label, ""


# ── The engine's own readers ───────────────────────────────────────────────

def engine_value(feed, holder, as_at):
    """(value, label, why) off live_scorecard.live_actuals."""
    from .live_scorecard import live_actuals

    key = ENGINE_KEYS[feed]
    got = live_actuals(holder.sales_code, staff_name=holder.name,
                       staff_pf=holder.pf, branch=str(holder.branch or ""),
                       wanted={key}, as_at=as_at).get(key) or {}
    if got.get("value") is None:
        return None, "", got.get("problem") or "no figure"
    return float(got["value"]), got.get("as_at_label") or "", ""


def crm_value(holder, year, month):
    from . import cx_returns

    value = cx_returns.running_total(cx_returns.CRM, year, month,
                                     names=(holder.name,), branches=(holder.branch,))
    if value is None:
        return None, "", "no row for this name on the CX team's CRM logs return"
    return float(value), "the CX team's CRM logs return, year to date", ""


def value(feed, holder, year, month, definition=None, wait=False):
    """(value, label, why) - the line's figure for ``month``."""
    if feed in ENGINE_KEYS:
        return engine_value(feed, holder, _month_end(year, month))
    if feed in CRM_FEEDS:
        return crm_value(holder, year, month)
    if feed in IAPPLY_FEEDS:
        definition = definition or (proven().get(feed) or {}).get("definition") or "month/own"
        return iapply_value(feed, holder.name, year, month, definition, wait=wait)
    return None, "", "no reader for this line"


# ── The proof ─────────────────────────────────────────────────────────────

def proven():
    """{feed: {"live", "matched", "people", "definition", "month"}}."""
    from .workbook_cards import saved

    try:
        return saved(STORE_KIND) or {}
    except Exception:  # noqa: BLE001 - before the table exists
        return {}


def _close(desk, got):
    if got is None or desk is None:
        return False
    return abs(desk - got) <= max(TOLERANCE, abs(desk) * RELATIVE)


def prove(year=None, out=print):
    """Read every line against the desk's own figures for the month the
    workbook was last run → the stored result. Run on the server
    (``manage.py prove_rbo_feeds``): it reads the warehouse."""
    from . import workbook_cards as wc

    spec = wc.SPECS[wc.RETAIL_BO]
    year = year or datetime.date.today().year
    book, actuals = wc.saved(spec.files[0], year), wc.saved(spec.files[1], year)
    if book is None or actuals is None:
        raise RuntimeError("Load the retail back office scorecards workbook first.")
    month = wc.rbo_run_month(book)
    people = {h.name.strip().lower(): h for h in wc.holders(book, keep_off=True)}
    result = {}
    for feed, rows in sorted(actuals.items()):
        if not handles(feed):
            out(f"{feed}: no reader - stays on the desk's figure")
            continue
        desk = []
        for row in rows[1:]:
            v = row[6 + month - 1] if len(row) > 6 + month - 1 else None
            holder = people.get(str(row[2] or "").strip().lower())
            if holder is not None and isinstance(v, (int, float)):
                desk.append((holder, float(v)))
        if not desk:
            continue
        best = None
        for definition in DEFINITIONS.get(feed, (None,)):
            got = []
            for holder, d in desk:
                try:
                    v, _label, why = value(feed, holder, year, month, definition, wait=True)
                except Exception as exc:  # noqa: BLE001 - say it, try the next
                    v, why = None, f"{type(exc).__name__}: {exc}"
                # No action at all is the desk's 0 on a TAT line.
                if v is None and feed in IAPPLY_FEEDS and "no iApply action" in why:
                    v = 0.0
                got.append((holder, d, v, why))
            matched = sum(1 for _h, d, v, _w in got if _close(d, v))
            if best is None or matched > best[0]:
                best = (matched, definition, got)
        matched, definition, got = best
        share = matched / len(got)
        result[feed] = {"live": share >= PASS_SHARE, "matched": matched,
                        "people": len(got), "definition": definition,
                        "month": f"{year}-{month:02d}"}
        out(f"{feed}: {matched} of {len(got)} people give the desk's figure"
            f"{f' ({definition})' if definition else ''} - "
            f"{'LIVE' if share >= PASS_SHARE else 'not live'}")
        for holder, d, v, why in got:
            out(f"    {holder.sales_code:<9} desk {d:>14,.2f}  read "
                f"{('-' if v is None else f'{v:,.2f}'):>14}  "
                f"{'same' if _close(d, v) else why or 'different'}")
    wc.save_file(STORE_KIND, result, loaded_by="prove_rbo_feeds")
    # Every month up to now read and kept, so no card waits on one.
    today = datetime.date.today()
    last = today.month if year == today.year else 12
    for m in range(1, last + 1):
        try:
            iapply_users(year, m, wait=True)
            out(f"iApply {year}-{m:02d}: read and kept")
        except Exception as exc:  # noqa: BLE001 - said, the run goes on
            out(f"iApply {year}-{m:02d}: FAILED {type(exc).__name__}: {exc}")
    return result
