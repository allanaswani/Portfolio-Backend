"""Card layouts from the desk's own workbooks - which lines a card has, their
order, perspective, wording and weight - so a new year's template changes
the cards by upload rather than by code.

Two workbooks, the ones the cards were built from:

* the sales scorecard workbook (``Portfolio Management - Q3 2026_scorecards
  .xlsb``) - a role sheet per card, read the way ``scorecard_workbook`` reads
  it: description in column C, measure in D, weight in E, the year's target
  in H, the feed key in M, and the perspective heading in column B carried
  down the rows it spans;
* the back-office scorecard workbook (``2026_BO_Non_Sales_Scorecards ...
  .xlsb``) - read by ``extract_bo_scorecards``' own card reader, which is what
  migration 0031 seeded these cards from.

What it changes, and what it does not
─────────────────────────────────────
For each card it compares the workbook with what is configured and reports
every difference - a weight, an order, a perspective, a line's wording, a line
added, a line dropped. Applying writes exactly that.

* A line is matched to the platform's KPI by its wording (the KPI codes ARE
  slugs of the cards' wording) or, on the back-office cards, by the actuals
  sheet the card names. A line nothing matches becomes a NEW KPI that is
  loaded rather than measured - Figures to load and the actuals templates fill
  it - because a measure the platform has never read cannot be invented from a
  heading. The report names every one.
* Role-wide targets (NPS 60%, training hours, a threshold) are written from
  the card. A per-person target is not: it is somebody's own number, and comes
  from Summary Allocation as it always has.
* How a KPI is MEASURED - its feed, its scoring rule, its cap - is code, and
  this does not touch it.

Nothing is written until it is applied, and applying is one transaction.
"""

from __future__ import annotations

import importlib

#: Sales workbook sheet -> the cards it lays out. ARMs and BBCs carry their
#: segment RM's card, as the desk confirmed when the cards were seeded (0027).
SALES_SHEETS = {
    "Business_Banking": ("sme_rm", "sme_arm", "sme_bbc"),
    "Personal_Banking": ("pb_rm", "pb_arm", "pb_bbc"),
    "Ultimate_RM": ("ultimate_rm",),
    "Diaspora": ("diaspora_rm", "diaspora_arm"),
    "Mortgage_Business": ("mortgage_business_arm",),
    "Commercial": ("commercial_rm",),
    "Commercial_trade": ("commercial_rm_trade",),
    "HEAD_COMMERCIAL": ("head_commercial",),
}

#: Back-office workbook sheet -> its card. Explicit, because the sheets' own
#: titles do not tell them apart: BOM_SCORECARD and BOMCSO both say "Branch
#: Operations Manager", CASH_TELLER_SCORECARD and TELLER_SCORECARD both say
#: "Teller".
BO_SHEETS = {
    "BOM_SCORECARD": ("bo_bom",),
    "BOMCSO": ("bo_bom_cso",),
    "CSO_SCORECARD": ("bo_cso",),
    "CSO_UB_SCORECARD": ("bo_cso_ub",),
    "CSM_DB_SCORECARD": ("bo_csm_diaspora",),
    "CASH_TELLER_SCORECARD": ("bo_cash_teller",),
    "TELLER_SCORECARD": ("bo_teller",),
    "RBO_SCORECARD": ("bo_rbo",),
    "CASHTELLER_SCORECARD": ("bo_cash_centre_teller",),
    "TL_RBO_SCORECARD": ("bo_tl_rbo",),
}

SALES = "sales"
BACK_OFFICE = "back_office"


def _norm(text):
    """Wording compared without case, line breaks or doubled spaces - the
    workbook writes "Financials \n(25%)" where the card stored it flat."""
    return " ".join(str(text or "").split()).lower()


class LayoutError(Exception):
    """The workbook could not be read as a card workbook."""


def _role_wide():
    """KPIs whose target is one figure for everybody on the card - the list
    migration 0029 decided, so the two cannot drift."""
    module = importlib.import_module(
        "apps.staff_management.migrations.0029_role_target_basis")
    return set(module.ROLE_WIDE)


def detect(sheet_names):
    names = set(sheet_names)
    if names & set(BO_SHEETS):
        return BACK_OFFICE
    if names & set(SALES_SHEETS):
        return SALES
    return None


# ── reading ──────────────────────────────────────────────────────────────────

def read_sales(book):
    """→ ``[{"sheet", "roles", "lines": [...]}]``, lines in card order."""
    from .scorecard_workbook import (
        COL_ANNUAL_TARGET, COL_DESCRIPTION, COL_FEED_KEY, COL_MEASURE,
        COL_WEIGHT, DESCRIPTION_ALIASES, FIRST_LINE, _number, slug)

    cards = []
    for sheet, roles in SALES_SHEETS.items():
        if sheet not in book.sheets:
            continue
        with book.get_sheet(sheet) as ws:
            rows = [[cell.v for cell in row] for row in ws.rows()]
        lines, perspective = [], ""
        for row in rows[FIRST_LINE:]:
            row = list(row) + [None] * (COL_FEED_KEY + 1 - len(row))
            heading = str(row[1] or "").strip()
            if heading:
                perspective = " ".join(heading.split())
            description = " ".join(str(row[COL_DESCRIPTION] or "").split())
            raw_measure = row[COL_MEASURE]
            # A number in the measure column (NPS's 0.6) is a target written
            # in the wrong place, not wording.
            measure = ("" if isinstance(raw_measure, (int, float))
                       else " ".join(str(raw_measure or "").split()))
            weight = _number(row[COL_WEIGHT])
            if weight is None:
                continue
            if not description:
                # VIC non-life: column C is merged with the line above, so
                # the row's only wording is its measure. The total row has
                # neither, and is not a line.
                if not measure:
                    continue
                description = measure
            line_slug = slug(description)
            lines.append({
                "order": len(lines) + 1,
                "perspective": perspective,
                "description": description,
                "measure": measure or description,
                "weight": weight,
                "target": _number(row[COL_ANNUAL_TARGET]),
                "feed": str(row[COL_FEED_KEY] or "").strip(),
                "slug": DESCRIPTION_ALIASES.get(line_slug, line_slug),
            })
        if lines:
            cards.append({"sheet": sheet, "roles": roles, "lines": lines})
    return cards


def read_back_office(book):
    """→ the same shape, off ``extract_bo_scorecards``' card reader."""
    from .management.commands.extract_bo_scorecards import Command
    from .scorecard_workbook import _number, slug

    reader = Command()
    cards = []
    for sheet, roles in BO_SHEETS.items():
        if sheet not in book.sheets:
            continue
        lines = []
        for row in reader._card(book, sheet):
            weight = _number(row.get("weight"))
            if weight is None:
                continue
            feed = str(row.get("actuals_sheet") or "").strip()
            perspective = " ".join(str(row.get("perspective") or "").split())
            share = row.get("perspective_weight")
            if share not in (None, ""):
                perspective = f"{perspective} {float(share) * 100:.1f}%"
            name = " ".join(str(row.get("measure") or "").split())
            wording = " ".join(str(row.get("key_initiative") or "").split())
            target = _number(row.get("target"))
            if row.get("target_from_ytd") == "yes":
                target = _number(row.get("ytd_target"))
            lines.append({
                "order": len(lines) + 1,
                "perspective": perspective.strip(),
                # The line's NAME ("Training hours") and the wording people
                # read under it ("Achieve training hours as per assigned
                # target") - the key initiative, which is what 0031 stored.
                "description": name,
                "measure": wording or name,
                "weight": weight,
                "target": target,
                "feed": feed,
                "slug": f"bo_{slug(feed)}" if feed else "",
            })
        if lines:
            cards.append({"sheet": sheet, "roles": roles, "lines": lines})
    return cards


def read(path):
    """The workbook → ``(kind, cards)``."""
    from pyxlsb import open_workbook

    try:
        with open_workbook(str(path)) as book:
            kind = detect(book.sheets)
            if kind is None:
                raise LayoutError(
                    "That workbook has none of the card sheets - it should be "
                    "the sales scorecard workbook or the back-office one.")
            cards = (read_sales(book) if kind == SALES
                     else read_back_office(book))
    except LayoutError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LayoutError(f"That workbook could not be read: {exc}")
    return kind, cards


# ── comparing ────────────────────────────────────────────────────────────────

def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def plan(kind, cards):
    """What applying would change, card by card → list of role plans."""
    from .scorecard_automation.models import ScKpi, ScRole, ScRoleKpiMapping
    from .scorecard_workbook import kpi_lookup

    lookup = kpi_lookup()
    kpis = {k.kpi_code: k for k in ScKpi.objects.all()}
    role_wide = _role_wide()
    plans = []
    for card in cards:
        for role in card["roles"]:
            existing = {m.kpi_code: m for m in
                        ScRoleKpiMapping.objects.filter(role_code=role)}
            by_feed = {}
            for code, m in existing.items():
                feed = (kpis[code].actuals_sheet if code in kpis else "") or ""
                by_feed.setdefault(feed.lower(), []).append(code)
            known = lookup.get(role, {})
            used, lines = set(), []
            for line in card["lines"]:
                code = None
                for candidate in (known.get(line["slug"]), line["slug"]):
                    if candidate and candidate in existing \
                            and candidate not in used:
                        code = candidate
                        break
                if code is None and line["feed"]:
                    free = [c for c in by_feed.get(line["feed"].lower(), [])
                            if c not in used]
                    if len(free) == 1:
                        code = free[0]
                if code is None:
                    # By the role's own wording for the line.
                    free = [c for c, m in existing.items() if c not in used
                            and _norm(m.kpi_description)
                            and _norm(m.kpi_description)
                            == _norm(line["measure"])]
                    if len(free) == 1:
                        code = free[0]
                if code is None:
                    # By position, but only when the weight agrees too - a
                    # line in the same place carrying the same weight is the
                    # same line, whatever its feed is called this year.
                    free = [c for c, m in existing.items() if c not in used
                            and m.kpi_order == line["order"]
                            and _same(m.kpi_weight, line["weight"])]
                    if len(free) == 1:
                        code = free[0]
                status, changes = "unchanged", {}
                if code is not None:
                    used.add(code)
                    m = existing[code]
                    shown = (m.kpi_description
                             or (kpis[code].kpi_description
                                 if code in kpis else ""))
                    wanted = {
                        "kpi_order": line["order"],
                        "kpi_weight": line["weight"],
                        "mapping_category": line["perspective"],
                    }
                    for field, value in wanted.items():
                        current = getattr(m, field)
                        if field == "mapping_category":
                            if _norm(current) != _norm(value):
                                changes[field] = (current, value)
                        elif not _same(current, value):
                            changes[field] = (current, value)
                    if line["measure"] and _norm(shown) != _norm(line["measure"]):
                        changes["kpi_description"] = (shown, line["measure"])
                    rate = _stated_rate(line["measure"])
                    if ((getattr(m, "target_basis", "") or "")
                            == "rate_on_base"
                            and (getattr(m, "target_base", "") or "")
                            in ("december_loan_book", "december_deposit_book")
                            and rate is not None
                            and not _same(m.kpi_target, rate)):
                        # "Grow by 21% of the Dec book Balance" - the card's
                        # own rate, or its wording and its score part company.
                        changes["kpi_target"] = (m.kpi_target, rate)
                    if (code in role_wide and line["target"] is not None
                            and (getattr(m, "target_basis", "") or "")
                            != "rate_on_base"
                            and not _same(m.kpi_target, line["target"])):
                        changes["kpi_target"] = (m.kpi_target, line["target"])
                    status = "changed" if changes else "unchanged"
                else:
                    # Known to the platform on another card - a line this card
                    # is gaining - or new to the platform altogether.
                    reuse = next((c for c in (known.get(line["slug"]),
                                              line["slug"]) if c in kpis), None)
                    code = reuse or _new_code(line, kpis)
                    status = "added" if reuse else "new_kpi"
                lines.append({**line, "kpi_code": code, "status": status,
                              "changes": {k: [_show(a), _show(b)]
                                          for k, (a, b) in changes.items()}})
            removed = sorted(set(existing) - used)
            plans.append({
                "role": role,
                "role_name": (ScRole.objects.filter(role_code=role)
                              .values_list("role_name", flat=True).first()
                              or role),
                "sheet": card["sheet"],
                "lines": lines,
                "removed": [{"kpi_code": c,
                             "weight": float(existing[c].kpi_weight or 0)}
                            for c in removed],
                "weight": round(sum(l["weight"] for l in card["lines"]), 6),
                "exists": bool(existing),
            })
    return plans


def _stated_rate(text):
    """ "Grow by 21% of the Dec book Balance" → 0.21, else None."""
    import re

    found = re.search(r"grow by\s*(\d+(?:\.\d+)?)\s*%\s*of",
                      str(text or ""), re.IGNORECASE)
    return float(found.group(1)) / 100 if found else None


def _new_code(line, kpis):
    base = line["slug"] or "card_line"
    code, n = base[:90], 2
    while code in kpis:
        code, n = f"{base[:86]}_{n}", n + 1
    return code


def _show(value):
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def summary(plans):
    """Counts for the report."""
    out = {"cards": len(plans), "unchanged": 0, "changed": 0, "added": 0,
           "new_kpi": 0, "removed": 0}
    for p in plans:
        for line in p["lines"]:
            out[line["status"]] += 1
        out["removed"] += len(p["removed"])
    return out


# ── applying ─────────────────────────────────────────────────────────────────

def apply(plans, who=""):
    """Write the plans - one transaction → counts."""
    import datetime

    from django.db import transaction
    from simple_history.utils import (
        bulk_create_with_history, bulk_update_with_history)

    from .scorecard_automation.models import ScKpi, ScRole, ScRoleKpiMapping

    # In batches, with their history, rather than one save() at a time. The
    # model refuses any save that takes a card past a total weight of 1, and
    # an upload legitimately passes through that (0.5 -> 0.6 is written before
    # the 0.5 -> 0.4 beside it) and can end there: the bank's own PB, Diaspora
    # and Commercial cards total 1.025. The workbook is the authority, and the
    # preview states every card's total before anything is applied.
    reason = f"card layout loaded{' by ' + who if who else ''}"
    to_update, update_fields, to_create = [], set(), []
    year = datetime.date.today().year
    start, end = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    counts = summary(plans)
    with transaction.atomic():
        for p in plans:
            role = p["role"]
            ScRole.objects.get_or_create(
                role_code=role,
                defaults={"role_name": p["role_name"], "role_type": "IC",
                          "is_active": True})
            removed = [r["kpi_code"] for r in p["removed"]]
            if removed:
                ScRoleKpiMapping.objects.filter(
                    role_code=role, kpi_code__in=removed).delete()
            template = (ScRoleKpiMapping.objects.filter(role_code=role)
                        .order_by("kpi_order").first())
            for line in p["lines"]:
                code = line["kpi_code"]
                if line["status"] == "new_kpi":
                    ScKpi.objects.get_or_create(kpi_code=code, defaults={
                        "kpi_name": line["description"][:100],
                        "kpi_description": line["measure"],
                        "kpi_calculation_mode": "actual_over_target",
                        "kpi_rating_type": "prorate", "score_cap": "1.20",
                        "is_active": True, "actuals_sheet": line["feed"],
                        "actuals_block": None, "negate": False,
                        "allocation_column": "", "allocation_base_column": "",
                        "has_base_value": False,
                        "not_configured_reason": (
                            "added from the card layout; which block of its "
                            "actuals sheet it reads is not established, so it "
                            "is loaded under Figures to load"),
                    })
                if line["status"] in ("added", "new_kpi"):
                    to_create.append(ScRoleKpiMapping(
                        role_code=role, kpi_code=code,
                        kpi_order=line["order"],
                        mapping_category=line["perspective"],
                        kpi_description=line["measure"],
                        kpi_weight=line["weight"], kpi_target=None,
                        is_bonus=False,
                        effective_from=getattr(template, "effective_from",
                                               start),
                        effective_to=getattr(template, "effective_to", end),
                        bonus_effective_from=getattr(
                            template, "bonus_effective_from", start),
                        bonus_effective_to=getattr(
                            template, "bonus_effective_to", end),
                        plan_category="p1", target_category="full_year",
                        prorate=True))
                    continue
                if line["status"] == "changed":
                    for m in ScRoleKpiMapping.objects.filter(
                            role_code=role, kpi_code=code):
                        for field, (_old, new) in line["changes"].items():
                            setattr(m, field, new)
                            update_fields.add(field)
                        to_update.append(m)
        if to_update:
            bulk_update_with_history(
                to_update, ScRoleKpiMapping, sorted(update_fields),
                default_change_reason=reason)
        if to_create:
            bulk_create_with_history(
                to_create, ScRoleKpiMapping, default_change_reason=reason)
    return counts
