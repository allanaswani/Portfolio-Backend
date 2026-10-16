"""Load an individual's own signed scorecard.

The master workbook (``Portfolio Management - Q3 2026_scorecards.xlsb``)
carries ONE card per role - a worked example - so loading it reaches ten
people. Everybody else has their own file, in the same twelve-column layout,
with their own targets on it:

    Lydia Apanja_Q3_Sep_26_Scorecard.xlsx
    Alice Kamau_Q3_Sep_26_Scorecard.xlsx
    Beldine Otieno_Q3_Sep_26_Scorecard.xlsx

Lydia's card says Income Contribution 3,654,925.71 -> 4,324,995.42, Active
Customers 102 -> 120.70, Digital Adoption 197 -> 287.29. Her platform card
said "no target is set" for all three, because the master workbook's Personal
Banking sheet is Vincent Ogare's, not hers. These figures were never going to
arrive from it.

Resolving who it belongs to
───────────────────────────
These files carry no sales code - only "Staff Name", a title and a branch. So
the person is found by NAME on the rosters, and only when exactly ONE person
matches. The title and branch are checked against that match and a
disagreement is reported rather than overridden: a scorecard loaded onto the
wrong person is worse than one not loaded.

What is written
───────────────
The ANNUAL target (column H), not the year-to-date beside it - the card
pro-rates a year's target to the date its actual is as at, so loading the YTD
figure would pro-rate it twice. And the actual (column J), which fills the
lines no feed here can reach; the warehouse still wins wherever it produces a
figure of its own.
"""

from __future__ import annotations

from .scorecard_workbook import (
    COL_ACTUAL, COL_ANNUAL_TARGET, COL_DESCRIPTION, COL_MEASURE,
    COL_PREV_FY, COL_WEIGHT, COL_YTD_TARGET, DESCRIPTION_ALIASES, FIRST_LINE,
    _number, kpi_lookup, slug,
)

#: Where the header block puts each thing, counting rows from zero.
ROW_TITLE = 0          # "2026 PB OBJECTIVES"
ROW_NAME = 1           # Staff Name: | <name> | Title: | <title>
ROW_BRANCH = 2         # BM Branch:  | <branch> | Reports to: | <manager>
ROW_PERIOD = 3         # Review Period | <period>

COL_LABEL_VALUE = 2    # the value beside "Staff Name:"
COL_SECOND_VALUE = 4   # the value beside "Title:"


def _text(row, index):
    if index >= len(row):
        return ""
    return str(row[index] if row[index] is not None else "").strip()


def read_card(path_or_stream):
    """One person's scorecard file → a card dict.

    Raises ``ValueError`` when the sheet is not a card at all, which is the
    honest answer for a file somebody picked up by mistake.
    """
    from openpyxl import load_workbook

    book = load_workbook(path_or_stream, data_only=True, read_only=True)
    sheet = book[book.sheetnames[0]]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    if len(rows) <= FIRST_LINE:
        raise ValueError("that sheet has no card on it")

    header = _text(rows[ROW_NAME], 0).lower()
    if "staff name" not in header:
        raise ValueError(
            "that sheet is not a scorecard - row 2 should begin "
            "\"Staff Name:\". The back-office cards (TELLER_SCORECARD, "
            "CSO_SCORECARD) are a different layout and are not read here.")

    card = {
        "title_line": _text(rows[ROW_TITLE], 0),
        "staff_name": _text(rows[ROW_NAME], COL_LABEL_VALUE),
        "staff_title": _text(rows[ROW_NAME], COL_SECOND_VALUE),
        "branch": _text(rows[ROW_BRANCH], COL_LABEL_VALUE),
        "manager": _text(rows[ROW_BRANCH], COL_SECOND_VALUE),
        "period": _text(rows[ROW_PERIOD], COL_LABEL_VALUE),
        "lines": [],
    }
    if not card["staff_name"]:
        raise ValueError("that card has no staff name on it")

    for row in rows[FIRST_LINE:]:
        description = _text(row, COL_DESCRIPTION)
        if not description:
            continue
        # The signature rows and the total carry text in other columns; a
        # line is a line because it has a DESCRIPTION and a numeric weight.
        weight = _number(row[COL_WEIGHT] if COL_WEIGHT < len(row) else None)
        if weight is None:
            continue
        if description.lower().startswith(("reviewee", "reviewer", "total")):
            continue
        card["lines"].append({
            "description": description,
            "measure": _text(row, COL_MEASURE),
            "weight": weight,
            "prev_fy": _number(row[COL_PREV_FY]
                               if COL_PREV_FY < len(row) else None),
            "annual_target": _number(row[COL_ANNUAL_TARGET]
                                     if COL_ANNUAL_TARGET < len(row) else None),
            "ytd_target": _number(row[COL_YTD_TARGET]
                                  if COL_YTD_TARGET < len(row) else None),
            "actual": _number(row[COL_ACTUAL]
                              if COL_ACTUAL < len(row) else None),
            "slug": DESCRIPTION_ALIASES.get(slug(description),
                                            slug(description)),
        })
    return card


def resolve(card):
    """Who this card belongs to → ``(person, why)``.

    By NAME, because these files carry no sales code, and only when exactly
    one person on the rosters matches. ``why`` explains a refusal.
    """
    from .live_scorecard import name_tokens, names_agree, resolve_person
    from .models import (BranchEmployeeDmcData, BranchFinalEmployeeDmcData,
                         StaffEmployeeData)

    name = card.get("staff_name") or ""
    tokens = name_tokens(name)
    if len(tokens) < 2:
        return None, f"\"{name}\" is not enough of a name to match on"

    longest = max(tokens, key=len)
    codes = set()
    for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData,
                  StaffEmployeeData):
        for row in (model.objects.filter(staff_name__icontains=longest)
                    .exclude(sales_code="")
                    .exclude(sales_code__isnull=True)
                    .only("staff_name", "sales_code")[:400]):
            if names_agree(name, row.staff_name):
                codes.add((row.sales_code or "").strip().upper())
    codes.discard("")

    if not codes:
        return None, (f"nobody on the rosters is called {name}. The card "
                      f"carries no sales code, so the name is the only way "
                      f"to find them")
    if len(codes) > 1:
        return None, (f"{len(codes)} people on the rosters are called {name} "
                      f"({', '.join(sorted(codes))}). A scorecard loaded onto "
                      f"the wrong person is worse than one not loaded")

    code = codes.pop()
    person = resolve_person(code)
    if person is None or not person.role_code:
        return None, (f"{name} resolves to {code}, which holds no card on "
                      f"this platform")
    return person, ""


def plan(cards):
    """What would be written → ``(entries, report)``. Writes nothing."""
    lookup = kpi_lookup()
    entries, report = [], {
        "cards": [], "targets": 0, "actuals": 0,
        "unmapped": [], "no_person": [], "mismatched_title": [],
    }

    for card in cards:
        person, why = resolve(card)
        summary = {
            "staff_name": card["staff_name"],
            "staff_title": card["staff_title"],
            "branch": card["branch"], "period": card["period"],
            "sales_code": person.sales_code if person else "",
            "role_code": person.role_code if person else "",
            "matched": bool(person), "targets": 0, "actuals": 0,
            "unmapped": 0,
        }
        if person is None:
            report["no_person"].append(
                {"staff_name": card["staff_name"], "why": why})
            report["cards"].append(summary)
            continue

        # The title on the card against the role the roster holds. Reported,
        # not enforced: titles drift, and refusing on one would reject a card
        # whose figures are right.
        stated = (card.get("staff_title") or "").strip().lower()
        if stated and stated.replace(" ", "_") not in person.role_code.lower():
            report["mismatched_title"].append({
                "staff_name": card["staff_name"],
                "card_says": card["staff_title"],
                "roster_says": person.role_code,
            })

        by_slug = lookup.get(person.role_code, {})
        for line in card["lines"]:
            code = by_slug.get(line["slug"])
            if code is None:
                summary["unmapped"] += 1
                report["unmapped"].append({
                    "staff_name": card["staff_name"],
                    "line": line["description"]})
                continue

            # The ANNUAL target, never the YTD beside it - see the note on
            # the column constants in ``scorecard_workbook``.
            if line["annual_target"] is not None:
                entries.append({
                    "kind": "target", "sales_code": person.sales_code,
                    "kpi_code": code, "value": line["annual_target"],
                    "ytd_was": line["ytd_target"],
                    "line": line["description"]})
                summary["targets"] += 1
                report["targets"] += 1

            if line["actual"] is not None:
                entries.append({
                    "kind": "actual", "sales_code": person.sales_code,
                    "kpi_code": code, "value": line["actual"],
                    "line": line["description"]})
                summary["actuals"] += 1
                report["actuals"] += 1

        report["cards"].append(summary)
    return entries, report


def save(entries, who="", month=None):
    """Write them. Upserts, so a reload corrects rather than stacks.

    Reuses the workbook loader's writer: a target loaded from somebody's own
    card and one loaded from the master workbook have to land in the same
    place, or the card would read two different figures depending on which
    file it came from.
    """
    from .scorecard_workbook import save as write

    return write(entries, who=who, month=month)
