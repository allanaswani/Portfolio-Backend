"""The desk's own scorecard workbook, read as a source of figures.

``Portfolio Management - Q3 2026_scorecards.xlsb`` is where the scorecards were
worked out before this platform computed them. It is still the authority for
the handful of lines nothing here can measure — banking covenant tracking,
account planning, leave, weighted sales — and it already holds them, per
person, with the desk's own targets beside them.

The shape of a role sheet
─────────────────────────
One card per sheet, for one named person::

    r1   Staff Name: | Juspher Muriithi | Title: | COMMERCIAL RM | Performance Score: | 0.495
    r2   BM Branch:  | H/Q              | Reports to: | Floyd Mathias
    r3   Review Period | Q3_Aug_26
    r4   COUNT | KPI | KPI Description | Measure of Success | Weight |
         2025 FY | GROWTH | 2026 FY | YTD Target | ACTUAL | % SCORE | Weighted
    r5+  the lines, with a FEED KEY in column 12

Eleven sheets carry a card. ``List`` carries the roster — sales code, name,
role, branch, line manager and two e-mail addresses — which is what resolves a
card to a person.

Two rules this follows, and they are the same ones the rest of the module
follows
───────────────────────────────────────────────────────────────────────────
**The warehouse still wins.** A figure is only taken from the workbook for a
line this platform cannot measure for itself. Loading a deposit figure out of
a spreadsheet when the balance tables hold it would undo the thing that makes
the card trustworthy, so those lines are read, counted and deliberately
skipped — and the report says how many and why.

**A line that cannot be mapped is reported, never guessed.** The KPI codes are
slugs of the cards' own wording, so the mapping is built from the seeded
descriptions at run time rather than from a hand-written table that would rot
the first time somebody edited a card. Anything the slug does not find is
named in the report.
"""

from __future__ import annotations

import re

#: Sheets that carry a card. Anything else in the workbook is working.
ROLE_SHEETS = (
    "Business_Banking", "Personal_Banking", "Ultimate_RM", "Diaspora",
    "Home_Loan_Specialist", "Mortgage_Business", "Commercial",
    "Commercial_trade", "BMs", "SNR_MGR_ULTIMATE", "BDM_Mortgages",
)

#: Columns on a card row, counting from zero::
#:
#:   0 COUNT  1 KPI  2 Description  3 Measure of Success  4 Weight
#:   5 2025 FY  6 GROWTH  7 2026 FY  8 YTD Target  9 ACTUAL
#:   10 % SCORE  11 Weighted  12 feed key
#:
#: **The target written is the ANNUAL one, column 7, not the YTD in column
#: 8.** ``ScEmployeeKpiTarget`` holds a year's target and the card pro-rates
#: it to the date the actual is as at - so loading the workbook's YTD figure
#: would have it pro-rated a second time. Business Banking's operating profit
#: is 6,245,102 for the year and 4,163,401 to August; loading the latter as
#: the annual target would have scored that person against 2.8m.
COL_DESCRIPTION = 2
COL_MEASURE = 3
COL_WEIGHT = 4
COL_PREV_FY = 5
COL_GROWTH = 6
COL_ANNUAL_TARGET = 7
COL_YTD_TARGET = 8
COL_ACTUAL = 9
COL_FEED_KEY = 12

#: Where the header row sits, and where the lines start.
ROW_NAME = 1
ROW_BRANCH = 2
ROW_PERIOD = 3
FIRST_LINE = 5

ROSTER_SHEET = "List"

#: Workbook wording -> the seeded wording, where the two have drifted.
#:
#: The mapping is built from the seeded descriptions at run time, which
#: resolves 153 of the workbook's 154 lines on its own. This is the
#: remainder: the same measure written two ways in two places, which no
#: amount of slug-matching will reconcile because neither spelling is wrong.
#:
#: Kept deliberately short. Every entry here is a place where somebody should
#: eventually make the two agree, and a long list would be a sign this had
#: become a substitute for that rather than a bridge to it.
DESCRIPTION_ALIASES = {
    "active_customers_2_months_active": "active_customers_two_month",
}


def slug(text):
    """A KPI description reduced to the shape of a kpi_code."""
    return re.sub(r"_+", "_",
                  re.sub(r"[^a-z0-9]+", "_", str(text or "").lower())).strip("_")


def fold(text):
    return " ".join(str(text or "").split()).strip().upper()


def _number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in (">80%", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_roster(workbook):
    """The ``List`` sheet → ``{folded name: {...}}``.

    The workbook's own roster, which is what ties a card to a sales code. It
    also carries the two e-mail addresses a card would be sent to.
    """
    if ROSTER_SHEET not in workbook.sheets:
        return {}
    with workbook.get_sheet(ROSTER_SHEET) as sheet:
        rows = [[cell.v for cell in row] for row in sheet.rows()]
    if not rows:
        return {}

    header = [str(cell or "").strip().lower() for cell in rows[0]]
    def at(*names):
        for name in names:
            if name in header:
                return header.index(name)
        return None

    columns = {
        "sales_code": at("sales_code"), "name": at("name"),
        "role": at("role"), "branch": at("branch"),
        # e-mail1 sits beside the BBM column and holds the LINE MANAGER's
        # address, not the person's - Charles Muchiri's row carries his
        # BBM Stephen Mutava's. e-mail2 is a central copy. The person's own
        # address is not in this sheet, and saying otherwise would send
        # somebody's scorecard to their manager believing it went to them.
        "manager": at("bbm"), "manager_email": at("e-mail1"),
        "copy_email": at("e-mail2"),
    }
    if columns["sales_code"] is None or columns["name"] is None:
        return {}

    out = {}
    for row in rows[1:]:
        def value(key):
            index = columns.get(key)
            if index is None or index >= len(row):
                return ""
            return str(row[index] or "").strip()

        name = value("name")
        if not name or not value("sales_code"):
            continue
        out[fold(name)] = {
            "sales_code": value("sales_code").upper(),
            "name": name, "role": value("role"), "branch": value("branch"),
            "manager": value("manager"),
            "manager_email": value("manager_email"),
            "copy_email": value("copy_email"),
        }
    return out


def kpi_lookup():
    """``{role_code: {slug: kpi_code}}``, built from what is seeded.

    Built at run time on purpose. The codes are slugs of each card's own
    wording, so the seeded descriptions ARE the mapping - a hand-written
    table beside them would be a second copy to drift.
    """
    from .scorecard_automation.models import ScKpi, ScRoleKpiMapping

    names = {k.kpi_code: k.kpi_name for k in ScKpi.objects.all()}
    out = {}
    for mapping in ScRoleKpiMapping.objects.all():
        bucket = out.setdefault(mapping.role_code, {})
        for candidate in (getattr(mapping, "kpi_description", "") or "",
                          names.get(mapping.kpi_code, "")):
            if candidate:
                bucket.setdefault(slug(candidate), mapping.kpi_code)
        bucket.setdefault(mapping.kpi_code, mapping.kpi_code)
    return out


def read_workbook(path_or_stream):
    """Read every card in the workbook → ``(cards, report)``.

    Nothing is written and nothing is resolved against the database here, so
    this can be run against a file on a laptop to see what it holds.
    """
    from pyxlsb import open_workbook

    cards, report = [], {
        "sheets_read": [], "sheets_skipped": [], "roster_rows": 0,
        "lines": 0, "unreadable": [],
    }

    with open_workbook(path_or_stream) as workbook:
        roster = read_roster(workbook)
        report["roster_rows"] = len(roster)

        for name in ROLE_SHEETS:
            if name not in workbook.sheets:
                report["sheets_skipped"].append(
                    {"sheet": name, "why": "not in this workbook"})
                continue
            with workbook.get_sheet(name) as sheet:
                rows = [[cell.v for cell in row] for row in sheet.rows()]

            def cell(row_index, column):
                if row_index >= len(rows) or column >= len(rows[row_index]):
                    return None
                return rows[row_index][column]

            staff_name = str(cell(ROW_NAME, 2) or "").strip()
            if not staff_name:
                report["sheets_skipped"].append(
                    {"sheet": name, "why": "no staff name in the header"})
                continue

            lines = []
            for row in rows[FIRST_LINE:]:
                if len(row) <= COL_FEED_KEY:
                    continue
                feed_key = str(row[COL_FEED_KEY] or "").strip()
                description = str(row[COL_DESCRIPTION] or "").strip()
                if not feed_key or not description:
                    continue
                line_slug = slug(description)
                lines.append({
                    "description": description,
                    "measure": str(row[COL_MEASURE] or "").strip(),
                    "weight": _number(row[COL_WEIGHT]),
                    "prev_fy": _number(row[COL_PREV_FY]),
                    "growth": _number(row[COL_GROWTH]),
                    "annual_target": _number(row[COL_ANNUAL_TARGET]),
                    # Kept for the report, so a reader can see the desk's own
                    # pro-rating beside the annual figure that is written.
                    "ytd_target": _number(row[COL_YTD_TARGET]),
                    "actual": _number(row[COL_ACTUAL]),
                    "feed_key": feed_key,
                    "slug": DESCRIPTION_ALIASES.get(line_slug, line_slug),
                })
            if not lines:
                report["sheets_skipped"].append(
                    {"sheet": name, "why": "no KPI lines found"})
                continue

            report["sheets_read"].append(name)
            report["lines"] += len(lines)
            known = roster.get(fold(staff_name), {})
            cards.append({
                "sheet": name,
                "staff_name": staff_name,
                "title": str(cell(ROW_NAME, 4) or "").strip(),
                "branch": str(cell(ROW_BRANCH, 2) or "").strip(),
                "manager": str(cell(ROW_BRANCH, 4) or "").strip(),
                "period": str(cell(ROW_PERIOD, 2) or "").strip(),
                "stated_score": _number(cell(ROW_NAME, 10)),
                # From the workbook's own List sheet, which is the only place
                # in the file that ties a card to a sales code.
                "sales_code": known.get("sales_code", ""),
                "manager_email": known.get("manager_email", ""),
                "copy_email": known.get("copy_email", ""),
                "lines": lines,
            })
    return cards, report


def plan(cards):
    """Decide what would be written for each card → ``(entries, report)``.

    Resolves each card to a person on OUR roster and each line to a kpi_code,
    then splits the lines two ways: a figure to write, and a line that could
    not be mapped.

    A figure is written whether or not the platform also measures that line.
    The card prefers its own measurement wherever it has one - the warehouse
    wins the actual ladder, and a loaded target gives way to the person's own
    DMC column - so what is loaded here can only ever fill a blank. The count
    of lines that sit behind a live source is reported rather than refused.
    """
    from .live_scorecard import SOURCES, resolve_person

    lookup = kpi_lookup()
    entries, report = [], {
        "cards": [], "actuals": 0, "targets": 0,
        "behind_a_live_source": 0, "unmapped": [], "no_person": [],
    }

    for card in cards:
        person = (resolve_person(card["sales_code"])
                  if card["sales_code"] else None)
        summary = {
            "sheet": card["sheet"], "staff_name": card["staff_name"],
            "sales_code": card["sales_code"], "period": card["period"],
            "role_code": person.role_code if person else "",
            "matched": bool(person and person.role_code),
            "actuals": 0, "targets": 0, "unmapped": 0,
        }
        if not summary["matched"]:
            report["no_person"].append({
                "sheet": card["sheet"], "staff_name": card["staff_name"],
                "sales_code": card["sales_code"],
                "why": ("no sales code on the workbook's List sheet"
                        if not card["sales_code"] else
                        "that sales code holds no card on this platform"),
            })
            report["cards"].append(summary)
            continue

        by_slug = lookup.get(person.role_code, {})
        for line in card["lines"]:
            code = by_slug.get(line["slug"])
            if code is None:
                summary["unmapped"] += 1
                report["unmapped"].append({
                    "sheet": card["sheet"], "line": line["description"],
                    "feed_key": line["feed_key"],
                })
                continue

            source = SOURCES.get(code)
            if (line["actual"] is not None and source is not None
                    and not source.pending and source.actual_key):
                report["behind_a_live_source"] += 1
            if line["actual"] is not None:
                entries.append({
                    "kind": "actual", "sales_code": card["sales_code"],
                    "kpi_code": code, "value": line["actual"],
                    "sheet": card["sheet"], "line": line["description"]})
                summary["actuals"] += 1
                report["actuals"] += 1
            # The ANNUAL target - see the note on the column constants.
            if line["annual_target"] is not None:
                entries.append({
                    "kind": "target", "sales_code": card["sales_code"],
                    "kpi_code": code, "value": line["annual_target"],
                    "ytd_was": line["ytd_target"],
                    "sheet": card["sheet"], "line": line["description"]})
                summary["targets"] += 1
                report["targets"] += 1
        report["cards"].append(summary)
    return entries, report


def save(entries, who="", month=None, source=""):
    """Write the planned figures. Upserts, so a reload corrects.

    ``source`` records WHERE the figure came from, and that decides how far
    the card trusts it: a figure off somebody's own signed card beats the
    warehouse, anything else only fills a blank. See
    ``ScEmployeePerformanceActual.source``.
    """
    from django.db import transaction

    from .scorecard_automation.models import (
        ScEmployeeKpiTarget, ScEmployeePerformanceActual)
    from .scorecard_manual import _default_month

    month = month or _default_month()
    written = {"actuals": 0, "targets": 0}
    with transaction.atomic():
        for entry in entries:
            if entry["kind"] == "actual":
                # ScEmployeePerformanceActual.save REFUSES an update without a
                # change reason - a correction to a figure somebody is paid on
                # should say who changed it - so update_or_create cannot be
                # used here. The row is fetched, the reason set, then saved,
                # which is the same shape the Figures-to-load upload uses.
                row, created = ScEmployeePerformanceActual.objects.get_or_create(
                    sales_code=entry["sales_code"],
                    kpi_code=entry["kpi_code"], eom_date=month,
                    defaults={"kpi_value": entry["value"],
                              "source": source})
                if not created:
                    row.kpi_value = entry["value"]
                    row.source = source
                    reason = (f"Scorecard workbook load by "
                              f"{who or 'an administrator'}")
                    row._change_reason = reason[:100]
                    row.save()
                written["actuals"] += 1
            else:
                ScEmployeeKpiTarget.objects.update_or_create(
                    sales_code=entry["sales_code"],
                    kpi_code=entry["kpi_code"], year=month.year,
                    defaults={"kpi_target": entry["value"]})
                written["targets"] += 1
    return written


# ─────────────────────────────────────────────────────────────────────────────
# The screen
# ─────────────────────────────────────────────────────────────────────────────


def read_upload(upload):
    """Read an uploaded workbook.

    ``pyxlsb`` wants a real file rather than a Django upload, so the bytes are
    written to a temporary one and removed afterwards. A 15 MB .xlsb through
    memory is cheaper than asking somebody to get a file onto a server.
    """
    import os
    import tempfile

    handle, path = tempfile.mkstemp(suffix=".xlsb")
    try:
        with os.fdopen(handle, "wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)
        return read_workbook(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
