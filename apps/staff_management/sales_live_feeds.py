"""RM card lines read live from the warehouse - only once proven.

The RM cards are the sales workbook's own formulas over the desk's actuals
template. The live engine (live_scorecard) has a warehouse reader for most
of their lines, but several were never shown to give the desk's figures - its
"non-life" is every non-life policy, not VIC non-life - so since d9f2ee2 the
desk's year to date stands on every line it has a figure for, and the open
month waits for the next template.

:func:`probe` settles it line by line. For a month the desk has closed it
reads every RM's card twice: the workbook's actual over the desk's template,
and the engine's figure from the warehouse alone (no loaded figure, see
``_engine_card(warehouse_only=True)``). Every line's result is stored. The
open month reads the warehouse on every RM line it has a figure for; a
line on which the warehouse gave the desk's figure for fewer than
:data:`PASS_SHARE` of the RMs says so on the card, and the report says by
how much and for whom - the list of definitions still to port.

Run on the host (the warehouse is there):

    manage.py sales_feed_probe --month 2026-09
"""

from __future__ import annotations

import datetime

#: The share of RMs whose figure the warehouse must reproduce.
PASS_SHARE = 0.9
#: Two figures are the same within a hundredth, or a thousandth of the
#: figure for money - the template carries some as floats from a division.
TOLERANCE = 0.01
RELATIVE = 0.001
#: Lines compared on fewer RMs than this prove nothing either way.
MIN_PEOPLE = 5
STORE_KIND = "sales_live_feeds"


def line_key(wl):
    """A card line → the key its proof is stored under: the template sheet
    it reads and its KPI, since one sheet can feed two lines."""
    from .workbook_cards import _key

    return f"{_key(wl['feed'])}|{_key(wl['measure'] or wl['initiative'])}"


def same(desk, warehouse):
    return abs(desk - warehouse) <= max(TOLERANCE, RELATIVE * abs(desk))


def _pairs(sales_code, book, actuals, holder, month, as_at):
    """One RM's card lines → [(line, desk figure, warehouse figure)].

    The warehouse figure is paired with the card line the way live_card
    pairs them: by the template sheet the KPI reads, else by its name.
    """
    from .live_scorecard import _engine_card
    from .scorecard_automation.models import ScKpi
    from .workbook_cards import _key, compute

    engine = _engine_card(sales_code, as_at=as_at, warehouse_only=True)
    if not engine.get("has_card"):
        return []
    lines = [ln for p in engine.get("perspectives", []) for ln in p["lines"]]
    kpis = {k: (sheet, negate) for k, sheet, negate in ScKpi.objects.filter(
        kpi_code__in=[ln["kpi_code"] for ln in lines])
        .values_list("kpi_code", "actuals_sheet", "negate")}
    pool = [{"feed": _key((kpis.get(ln["kpi_code"]) or ("", False))[0] or ""),
             "name": _key(ln.get("kpi_name")), "line": ln,
             "negate": bool((kpis.get(ln["kpi_code"]) or ("", False))[1])}
            for ln in lines]
    out = []
    for wl in compute(book, actuals, holder, month)["lines"]:
        if wl["typed"] or not wl["feed"]:
            continue
        match = (next((p for p in pool if p["feed"]
                       and p["feed"] == _key(wl["feed"])), None)
                 or next((p for p in pool if p["name"]
                          and p["name"] == _key(wl["measure"])), None))
        if match is not None:
            pool.remove(match)
        value = match["line"].get("ytd_actual") if match else None
        # Compared in the template's own sign, as live_card writes it.
        if match and match["negate"] and isinstance(value, (int, float)):
            value = -value
        out.append((wl, wl["actual"], value))
    return out


def _people(book):
    from .workbook_cards import holders

    return [h for h in holders(book)
            if h.sheet in book["cards"] and h.sales_code]


def probe(year, month, out=print, book=None, store=STORE_KIND):
    """Find which card lines the warehouse reproduces → {key: proof}
    stored, and a report printed through ``out``. The sales workbook unless
    ``book`` names another, whose proofs then go under ``store``."""
    from .workbook_cards import SALES, SPECS, _month_end, _num, save_file, saved

    spec = SPECS[book or SALES]
    book, actuals = saved(spec.files[0]), saved(spec.files[1])
    if book is None or actuals is None:
        out("Load the scorecards workbook and actuals template first - "
            "the probe compares against them.")
        return {}
    as_at = _month_end(datetime.date(year, month, 1))
    people = _people(book)
    out(f"Comparing {len(people)} cards for {as_at:%B %Y}: the desk's "
        f"template against the warehouse alone ...")

    seen = {}  # key -> {"name", "sheet", "rows": [(who, desk, warehouse)]}
    for n, holder in enumerate(people, 1):
        try:
            pairs = _pairs(holder.sales_code, book, actuals, holder, month,
                           as_at)
        except Exception as exc:  # noqa: BLE001 - one card must not stop it
            out(f"  {holder.sales_code}: could not be read ({exc})")
            continue
        for wl, desk, warehouse in pairs:
            entry = seen.setdefault(line_key(wl), {
                "name": wl["measure"] or wl["initiative"],
                "sheet": wl["feed"], "rows": []})
            entry["rows"].append((f"{holder.name} ({holder.sales_code})",
                                  desk, warehouse))
        if n % 25 == 0:
            out(f"  ... {n} of {len(people)}")

    results = {}
    for key, entry in sorted(seen.items(), key=lambda kv: kv[1]["name"]):
        # Only a figure that is not nought is proof: a line nought for
        # nearly everybody would otherwise "match" a warehouse that has
        # nothing at all.
        rows = [r for r in entry["rows"] if _num(r[1]) and r[1] != 0]
        label = f"{entry['name'][:38]:38} [{entry['sheet']}]"
        if len(rows) < MIN_PEOPLE:
            out(f"  {label}  only {len(rows)} RM(s) with a desk figure - "
                f"not enough to compare")
            results[key] = {"name": entry["name"], "sheet": entry["sheet"],
                            "people": len(rows), "live": False, "few": True,
                            "month": f"{year}-{month:02d}"}
            continue
        hits = [r for r in rows if _num(r[2]) and same(r[1], r[2])]
        none = sum(1 for r in rows if not _num(r[2]))
        share = len(hits) / len(rows)
        verdict = ("same as the desk" if share >= PASS_SHARE
                   else "differs from the desk")
        out(f"  {label} {share:6.1%} of {len(rows):3} match"
            f"{f', {none} with no warehouse figure' if none else ''}"
            f"  -> {verdict}")
        if share < PASS_SHARE:
            misses = sorted((r for r in rows if r not in hits),
                            key=lambda r: -abs(r[1]))[:3]
            for who, desk, warehouse in misses:
                said = (f"{warehouse:,.2f}" if _num(warehouse)
                        else "nothing")
                out(f"      {who}: desk {desk:,.2f}, warehouse {said}")
        results[key] = {"name": entry["name"], "sheet": entry["sheet"],
                        "match": share, "people": len(rows),
                        "live": share >= PASS_SHARE,
                        "month": f"{year}-{month:02d}"}

    stored = saved(store) or {}
    stored.update(results)
    save_file(store, stored, f"probe {year}-{month:02d}", "probe")
    proven_now = sorted(v["name"] for v in results.values()
                        if v["live"])
    out(f"{len(proven_now)} line(s) give the desk's own figures: "
        f"{', '.join(proven_now) or 'none'}.")
    return results


def explain(year, month, who, out=print):
    """One RM's card, line by line: the desk's figure beside the
    warehouse's, for a month the desk has closed."""
    from .workbook_cards import SALES, SPECS, _month_end, _num, saved

    spec = SPECS[SALES]
    book, actuals = saved(spec.files[0]), saved(spec.files[1])
    if book is None or actuals is None:
        out("Load the sales scorecards workbook and actuals template first.")
        return
    wanted = (who or "").strip().upper()
    holder = next((h for h in _people(book)
                   if wanted in (h.sales_code.upper(),
                                 str(h.name or "").strip().upper())), None)
    if holder is None:
        out(f"{who!r} is not on the sales workbook's List.")
        return
    as_at = _month_end(datetime.date(year, month, 1))
    out(f"{holder.name} ({holder.sales_code}), {as_at:%B %Y}:")
    for wl, desk, warehouse in _pairs(holder.sales_code, book, actuals,
                                      holder, month, as_at):
        d = f"{desk:,.2f}" if _num(desk) else str(desk)
        w = f"{warehouse:,.2f}" if _num(warehouse) else "nothing"
        flag = ("same" if _num(desk) and _num(warehouse)
                and same(desk, warehouse) else "DIFFERENT")
        out(f"  {(wl['measure'] or wl['initiative'])[:40]:40} desk {d:>20}"
            f"   warehouse {w:>20}   {flag}")


def proven():
    """Every line the probe has compared → its result."""
    from .workbook_cards import saved

    return saved(STORE_KIND) or {}


def note(results, wl):
    """What a live RM line's card should say about its figure: nothing
    where the warehouse gave the desk's own figures on a closed month,
    otherwise how far apart they were, or that nobody has compared them."""
    found = results.get(line_key(wl))
    if found is None:
        return "warehouse figure, not yet compared with the desk's"
    if found.get("live", True):
        return ""
    if found.get("few"):
        return ("warehouse figure - too few RMs carry this line to compare "
                "it with the desk's")
    when = datetime.date(*map(int, found["month"].split("-")), 1)
    return (f"warehouse definition, differs from the desk's (matched "
            f"{found['match']:.0%} of RMs for {when:%b %Y})")
