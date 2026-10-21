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

#: What ``ScEmployeePerformanceActual.source`` carries for a figure read off
#: somebody's own signed scorecard. The card trusts these over the warehouse;
#: everything else only fills a blank.
SIGNED_CARD = "signed-card"

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

    # These came off somebody's own signed card, which is the agreed record.
    return write(entries, who=who, month=month, source=SIGNED_CARD)


# -- The back-office layout --------------------------------------------------
# TELLER_SCORECARD and CSO_SCORECARD are a different sheet from the sales card
# above, and the differences matter:
#
#   * the header block is a two-column form, not the sales card's four rows;
#   * there is no "2025 FY" and no annual target. There is F, the assigned
#     level, and G, the YEAR-TO-DATE target, and the card has already
#     pro-rated one into the other;
#   * column L, "column_name", names the FEED - CASA, KYC, Branch_Audit,
#     Trx_Productivity - which is the same vocabulary the back-office actuals
#     template uses. A line is mapped by its feed, not by matching its
#     wording, because "Branch Audit" names three different lines.
#
# Only the ACTUAL is loaded from these. See :func:`plan_back_office`.

BO_ROW_NAME = 1            # Staff Name / Emp. Name: | <name>
BO_ROW_JOB = 2             # Job Title:              | <title>
BO_ROW_BRANCH = 3          # Branch | <branch> | Performance Period | <period>
BO_ROW_HEADER = 7          # Perspective | Measure | ... | column_name

BO_COL_VALUE = 2           # the value beside a label in the header block
BO_COL_SECOND = 5          # the value beside the second label
BO_COL_MEASURE = 2
BO_COL_INITIATIVE = 3
BO_COL_WEIGHT = 4
BO_COL_YTD_TARGET = 6
BO_COL_ACTUAL = 7
BO_COL_FEED = 11           # "column_name"


def looks_like_a_back_office_card(rows):
    """Is this the TELLER / CSO layout? -> bool."""
    if len(rows) <= BO_ROW_HEADER:
        return False
    header = " ".join(_text(rows[BO_ROW_HEADER], i) for i in range(0, 14))
    header = header.lower()
    return "column_name" in header and "perspective" in header


def read_back_office_card(path_or_stream):
    """A teller's or CSO's own scorecard -> a card dict.

    The same shape :func:`read_card` returns, so the rest of the loader does
    not care which layout a card arrived in - except that every line carries
    ``feed`` instead of ``slug``, and ``annual_target`` is always None.
    """
    from openpyxl import load_workbook

    book = load_workbook(path_or_stream, data_only=True, read_only=True)
    sheet = book[book.sheetnames[0]]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    if not looks_like_a_back_office_card(rows):
        raise ValueError(
            "that sheet is not a back-office scorecard - row 8 should carry "
            "Perspective and column_name")

    card = {
        "layout": "back_office",
        "title_line": _text(rows[0], 1),
        "staff_name": _text(rows[BO_ROW_NAME], BO_COL_VALUE),
        "staff_title": _text(rows[BO_ROW_JOB], BO_COL_VALUE),
        "branch": _text(rows[BO_ROW_BRANCH], BO_COL_VALUE),
        "manager": _text(rows[BO_ROW_NAME], BO_COL_SECOND),
        "period": _text(rows[BO_ROW_BRANCH], BO_COL_SECOND),
        "lines": [],
    }
    if not card["staff_name"]:
        raise ValueError("that card has no staff name on it")

    for row in rows[BO_ROW_HEADER + 1:]:
        weight = _number(row[BO_COL_WEIGHT]
                         if BO_COL_WEIGHT < len(row) else None)
        if weight is None:
            continue
        feed = _text(row, BO_COL_FEED)
        measure = _text(row, BO_COL_MEASURE)
        initiative = _text(row, BO_COL_INITIATIVE)
        if not (feed or measure or initiative):
            # The weight TOTAL at the foot of the card: a lone 1.0 in the
            # weight column with nothing beside it. It is not a line.
            continue
        card["lines"].append({
            "description": measure or initiative or feed,
            "feed": feed,
            "measure": initiative,
            "weight": weight,
            "prev_fy": None,
            # Deliberately None - see plan_back_office.
            "annual_target": None,
            "ytd_target": _number(
                row[BO_COL_YTD_TARGET]
                if BO_COL_YTD_TARGET < len(row) else None),
            "actual": _number(
                row[BO_COL_ACTUAL] if BO_COL_ACTUAL < len(row) else None),
            "slug": "",
        })
    return card


def read_any(path_or_stream):
    """Read a card of either layout -> a card dict.

    The sales layout first, because it is the common one; the back-office
    layout when that refuses.
    """
    try:
        return read_card(path_or_stream)
    except ValueError:
        if hasattr(path_or_stream, "seek"):
            path_or_stream.seek(0)
        return read_back_office_card(path_or_stream)


def plan_back_office(cards):
    """What a teller's or CSO's own card would write.

    -> ``(entries, report)``. **Actuals only. The targets are deliberately
    left alone.**

    These cards carry no annual target. They carry an assigned level
    (column F) and a YEAR-TO-DATE target (column G), and the card has already
    pro-rated the one into the other. ``ScEmployeeKpiTarget`` holds a YEAR's
    target which the platform pro-rates to the date the actual is as at - so
    loading column G would pro-rate a second time, and loading column F would
    be wrong the other way, because F is a MONTHLY level on some lines
    (Jane Karathe: CRM "100 complaints logged MOM", 100 -> 900 by September)
    and an annual one on others (Training, 48 -> 36 by September).

    Nor is the fraction the same for everybody: Jane Karathe's card is
    pro-rated to nine months and Eunice Maina's to three, because it follows
    the person rather than the calendar. There is no rule that could be
    applied safely to both, so the targets stay as migration 0031 seeded them
    - from these very cards - and only the measured figures are taken.
    """
    from .bo_actuals import sheet_to_kpi
    from .scorecard_automation.models import ScRoleKpiMapping

    feeds = sheet_to_kpi()
    entries, report = [], {
        "cards": [], "targets": 0, "actuals": 0,
        "unmapped": [], "no_person": [], "mismatched_title": [],
        "targets_left_alone": 0,
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

        mappings = list(ScRoleKpiMapping.objects
                        .filter(role_code=person.role_code))
        on_card = {m.kpi_code for m in mappings}

        # Some lines name no feed. A teller's card carries "Customer
        # feedback" twice - "Nil client complaints" and "Achieve 5 client
        # compliments" - and only the measure above them names a column, so
        # the feed cannot tell the two apart and neither could be placed.
        #
        # Their KEY INITIATIVE can: the seeded card holds that same wording
        # as its own description, which is how migration 0031 told them
        # apart in the first place. Exact on the normalised text, so this is
        # a match rather than a guess, and only consulted when the feed has
        # not already answered.
        by_initiative = {}
        for mapping in mappings:
            text = slug(getattr(mapping, "kpi_description", "") or "")
            if text:
                by_initiative.setdefault(text, []).append(mapping.kpi_code)

        for line in card["lines"]:
            if line["actual"] is None:
                continue
            codes = [c for c in feeds.get(line["feed"], []) if c in on_card]
            if not codes:
                # The card's own wording for this line, where the feed did
                # not place it. Only when exactly one line on their card
                # carries that wording.
                candidates = by_initiative.get(slug(line["measure"]), [])
                if len(candidates) == 1:
                    codes = candidates
            if not codes:
                summary["unmapped"] += 1
                report["unmapped"].append({
                    "staff_name": card["staff_name"],
                    "line": line["description"],
                    "feed": line["feed"],
                    "why": ("the card names no feed for this line"
                            if not line["feed"] else
                            f"no line on the {person.role_code} card reads "
                            f"{line['feed']}")})
                continue
            for code in codes:
                entries.append({
                    "kind": "actual", "sales_code": person.sales_code,
                    "kpi_code": code, "value": line["actual"],
                    "line": line["description"]})
                summary["actuals"] += 1
                report["actuals"] += 1
            if line["ytd_target"] is not None:
                report["targets_left_alone"] += 1

        report["cards"].append(summary)
    return entries, report


def plan_any(cards):
    """Plan a mixed pile of cards -> ``(entries, report)``.

    Each layout is planned by its own rules and the reports are added
    together, so somebody uploading everything at once gets one answer rather
    than having to sort the files first.
    """
    sales = [c for c in cards if c.get("layout") != "back_office"]
    back_office = [c for c in cards if c.get("layout") == "back_office"]

    if sales:
        entries, report = plan(sales)
    else:
        entries, report = [], {
            "cards": [], "targets": 0, "actuals": 0, "unmapped": [],
            "no_person": [], "mismatched_title": []}
    report.setdefault("targets_left_alone", 0)

    if back_office:
        more, other = plan_back_office(back_office)
        entries = entries + more
        for key in ("targets", "actuals", "targets_left_alone"):
            report[key] = report.get(key, 0) + other.get(key, 0)
        for key in ("cards", "unmapped", "no_person", "mismatched_title"):
            report[key] = list(report.get(key, [])) + list(other.get(key, []))
    return entries, report
