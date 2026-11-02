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
``_engine_card(warehouse_only=True)``). A line on which the warehouse gives
the desk's figure for at least :data:`PASS_SHARE` of the RMs is stored as
proven; the live card then reads it from the warehouse in the open month.
A line that does not match stays on the desk's figure, and the report says
by how much and for whom.

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
    feeds = dict(ScKpi.objects.filter(
        kpi_code__in=[ln["kpi_code"] for ln in lines])
        .values_list("kpi_code", "actuals_sheet"))
    pool = [{"feed": _key(feeds.get(ln["kpi_code"]) or ""),
             "name": _key(ln.get("kpi_name")), "line": ln} for ln in lines]
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
        out.append((wl, wl["actual"], value))
    return out


def _people(book):
    from .workbook_cards import holders

    return [h for h in holders(book)
            if h.sheet in book["cards"] and h.sales_code]


def probe(year, month, out=print):
    """Find which RM card lines the warehouse reproduces → {key: proof}
    stored, and a report printed through ``out``."""
    from .workbook_cards import SALES, SPECS, _month_end, _num, save_file, saved

    spec = SPECS[SALES]
    book, actuals = saved(spec.files[0]), saved(spec.files[1])
    if book is None or actuals is None:
        out("Load the sales scorecards workbook and actuals template first - "
            "the probe compares against them.")
        return {}
    as_at = _month_end(datetime.date(year, month, 1))
    people = _people(book)
    out(f"Comparing {len(people)} RM cards for {as_at:%B %Y}: the desk's "
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

    found, tested = {}, set()
    for key, entry in sorted(seen.items(), key=lambda kv: kv[1]["name"]):
        # Only a figure that is not nought is proof: a line nought for
        # nearly everybody would otherwise "match" a warehouse that has
        # nothing at all.
        rows = [r for r in entry["rows"] if _num(r[1]) and r[1] != 0]
        label = f"{entry['name'][:38]:38} [{entry['sheet']}]"
        if len(rows) < MIN_PEOPLE:
            out(f"  {label}  only {len(rows)} RM(s) with a desk figure - "
                f"not enough to prove; stays on the desk's figure")
            continue
        tested.add(key)
        hits = [r for r in rows if _num(r[2]) and same(r[1], r[2])]
        none = sum(1 for r in rows if not _num(r[2]))
        share = len(hits) / len(rows)
        verdict = "LIVE" if share >= PASS_SHARE else "stays on the desk"
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
        else:
            found[key] = {"name": entry["name"], "sheet": entry["sheet"],
                          "match": share, "people": len(rows),
                          "month": f"{year}-{month:02d}"}

    # A line proven before and failing now is switched off again.
    stored = {k: v for k, v in (saved(STORE_KIND) or {}).items()
              if k not in tested}
    stored.update(found)
    save_file(STORE_KIND, stored, f"probe {year}-{month:02d}", "probe")
    out(f"{len(found)} line(s) now read live on the RM cards. Lines marked "
        f"'stays on the desk' keep the desk's latest figure until the "
        f"warehouse gives the desk's numbers.")
    return found


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
    from .workbook_cards import saved

    return saved(STORE_KIND) or {}
