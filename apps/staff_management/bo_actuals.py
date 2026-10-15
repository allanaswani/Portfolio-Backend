"""The back-office actuals template, read for everybody at once.

``2026_BO_Actual_Template.xlsx`` is where the back-office figures live. Unlike
the sales workbook - which holds one card per role sheet - this one holds
**every person on every measure**: 37 sheets, one per feed, each with a row per
member of staff and a column per month::

    StaffPF-Number | StaffSalesCode | Staff - Name | Role | Branch | Zone |
    2026-01-01 | 2026-02-01 | … | 2026-12-01

    1329 | EKN1329 | Eric Nguithi | BOM | Meru | Zone A | 0.431 | 0.434 | …

So one upload fills 121 people's cards rather than ten.

Twelve months into one figure: the LATEST, always
────────────────────────────────────────────────
The rule the business gave is "latest month for rates and levels, sum for
counts". Measured against the template, that comes out as **the latest month
for everything** - because the counting sheets are already cumulative:

    Training_hours   4, 14, 20, 49, 49, 64, 70, 77
    PL_Charge        569k, 795k, 1.81m, 3.24m, 3.79m, 3.08m, 3.91m, 4.50m
    RE_activation    0.431, 0.434, 0.463, 0.477, 0.479, 0.481, 0.469, 0.486

The first is a running total of hours, so the year to date is 77 and not 347.
The second is a provision balance that can fall when something is released, so
it is 4.50m and not the 21.7m the months add to. The third is a dormancy
score, never a thing to add up at all.

Counted across the whole template: Training_hours is non-decreasing on 100% of
its rows, Digital_Customers 100%, Operation_Lossess 100%, Cash_management
100%, KYC 95%, Branch_Audit 95%, CRM 94%, CASA 92%. The rate sheets fluctuate
as rates do - RE_activation 0%, NPS 1%, Active_Customers 0% - and for those
the latest month is the current level, which is what the card wants.

So summing would double-count every counting measure in the file. The reader
takes the latest month, and :func:`increment_sheets` re-checks that assumption
on every upload: a sheet that stops being cumulative is REPORTED rather than
silently mis-read, because the next version of this template could be built
the other way.

The ``kpi_code`` for each sheet comes from migration 0031, which seeded the
back-office cards and keyed each KPI on its feed. That is the authority: a
measure name alone is ambiguous, because "Branch Audit" is the name of three
different lines.
"""

from __future__ import annotations

import csv
import datetime
import pathlib
import re

#: Columns before the months begin.
COL_PF = 0
COL_SALES_CODE = 1
COL_NAME = 2
COL_ROLE = 3
COL_BRANCH = 4
FIRST_MONTH = 6

#: Where the threshold/accrual evidence lives. Read only to decide whether a
#: sheet that has STOPPED being cumulative should be summed - see
#: :func:`increment_sheets`.
EVIDENCE = (pathlib.Path(__file__).resolve().parents[2]
            / "docs" / "bo-scorecard-kpi-map.csv")

#: A sheet is treated as a series of monthly increments, rather than a running
#: total, when fewer than this share of its rows are non-decreasing. No sheet
#: in the October 2026 template is below 87%; the rate sheets sit at 0-15% and
#: are levels rather than counts, so they are not summed either.
CUMULATIVE_SHARE = 0.6


def _number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def sheet_to_kpi():
    """``{actuals sheet: kpi_code}``, from the migration that seeded them.

    Migration 0031 keyed every back-office KPI on its FEED and carries the
    pairing in its own ``KPIS`` table. Read from there rather than copied,
    because a copy beside it is a second thing to drift - and a measure name
    alone cannot do this job: "Branch Audit" names three different lines.
    """
    from importlib import import_module

    module = import_module(
        "apps.staff_management.migrations.0031_seed_bo_scorecards")
    out = {}
    for entry in getattr(module, "KPIS", []):
        sheet = (entry.get("actuals_sheet") or "").strip()
        code = (entry.get("kpi_code") or "").strip()
        if sheet and code and "NOT A SHEET" not in sheet:
            out.setdefault(sheet, []).append(code)
    return out


def accrual_sheets():
    """Sheets the CARDS treat as a total to reach rather than a level.

    Only consulted for a sheet that has stopped being cumulative, which none
    currently are. A threshold is a level to be at; an accrual is a total.
    """
    if not EVIDENCE.exists():
        return set()
    votes = {}
    with EVIDENCE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            sheet = (row.get("actuals_sheet") or "").strip()
            if not sheet or "NOT A SHEET" in sheet:
                continue
            tally = votes.setdefault(sheet, {"yes": 0, "no": 0})
            flag = (row.get("threshold") or "").strip().lower()
            if flag in tally:
                tally[flag] += 1
    return {sheet for sheet, tally in votes.items()
            if tally["no"] > tally["yes"]}


def is_cumulative(series):
    """Is this column of figures a running total rather than increments?

    Measured, not assumed, so the day somebody rebuilds the template the
    other way round this says so instead of quietly halving everyone's year.
    """
    rows = [values for values in series if len(values) >= 3]
    if not rows:
        return True
    climbing = sum(
        1 for values in rows
        if all(b >= a - 1e-9 for a, b in zip(values, values[1:])))
    return climbing >= len(rows) * CUMULATIVE_SHARE


def _month_columns(header):
    out = {}
    for index, value in enumerate(header):
        if isinstance(value, datetime.datetime):
            out[index] = value.date().replace(day=1)
        elif isinstance(value, datetime.date):
            out[index] = value.replace(day=1)
    return out


def read_workbook(path_or_stream):
    """Read the template → ``(rows, report)``.

    One entry per person per sheet that carries a figure for them. Nothing is
    written and nothing is resolved against the database.
    """
    from openpyxl import load_workbook

    book = load_workbook(path_or_stream, data_only=True)
    sheets = sheet_to_kpi()
    accruals = accrual_sheets()

    rows, report = [], {
        "sheets_read": [], "sheets_skipped": [], "people": set(),
        "figures": 0, "months": set(), "reporting_month": None,
        # Sheets that no longer look like a running total. Nothing is summed
        # on the strength of it - it is a flag for a human to look.
        "not_cumulative": [],
    }
    pending = []

    for name in book.sheetnames:
        codes = sheets.get(name)
        if not codes:
            report["sheets_skipped"].append(
                {"sheet": name, "why": "no back-office KPI reads this sheet"})
            continue
        sheet = book[name]
        grid = [[cell.value for cell in row] for row in sheet.iter_rows()]
        if len(grid) < 2:
            report["sheets_skipped"].append(
                {"sheet": name, "why": "no rows"})
            continue

        months = _month_columns(grid[0])
        if not months:
            report["sheets_skipped"].append(
                {"sheet": name, "why": "no month columns in the header"})
            continue
        # Measured per sheet rather than assumed - see is_cumulative.
        series = []
        for line in grid[1:]:
            values = [_number(line[column]) for column in sorted(months)
                      if column < len(line)]
            values = [v for v in values if v is not None]
            if values:
                series.append(values)
        # ALWAYS the latest month. Every sheet in this template is a figure
        # as at that month - a running total for the counting measures, a
        # level for the rates - so summing is never right here.
        #
        # PL_Charge is why this is unconditional rather than inferred. It is a
        # provision BALANCE that falls when something is released: 569k, 795k,
        # 1.81m, 3.24m, 3.79m, 3.08m, 3.91m, 4.50m. A "mostly rising" test
        # calls that increments and sums it to 21.7m - five times thetrue figure
        # - on a line that is 8% of a branch operations manager's card.
        #
        # The check below is kept as a WARNING only. If a future template is
        # built as monthly increments, taking the latest understates the year,
        # which somebody queries; summing a balance overstates it by a
        # multiple, which looks plausible and does not get queried. Of the two
        # ways to be wrong, this is the one that surfaces.
        how = "latest"
        cumulative = is_cumulative(series)
        if not cumulative and name in accruals:
            report["not_cumulative"].append(name)
        report["sheets_read"].append({"sheet": name, "how": how,
                                      "cumulative": cumulative,
                                      "kpi_codes": codes})

        for line in grid[1:]:
            def at(index):
                return line[index] if index < len(line) else None

            code = str(at(COL_SALES_CODE) or "").strip().upper()
            pf = re.sub(r"\D", "", str(at(COL_PF) or ""))
            if not code and not pf:
                continue

            found = {month: _number(at(column))
                     for column, month in months.items()
                     if _number(at(column)) is not None}
            if not found:
                continue
            latest = max(found)
            value = found[latest] if how == "latest" else sum(found.values())

            report["people"].add(code or pf)
            report["months"].add(latest)
            report["figures"] += 1
            pending.append({
                "sheet": name, "how": how, "kpi_codes": codes,
                "sales_code": code, "staff_pf": pf,
                "staff_name": str(at(COL_NAME) or "").strip(),
                "role": str(at(COL_ROLE) or "").strip(),
                "branch": str(at(COL_BRANCH) or "").strip(),
                "value": value, "as_at_month": latest,
                "months_with_a_figure": len(found),
            })

    # ── the month the template as a whole reaches ─────────────────────
    # Several sheets are pre-filled with zeros to December. Read row by row,
    # those report an as-at of December and the card then pro-rates a target
    # to the full year against a figure that stops in August. The reporting
    # month is the one most rows actually reach, and every row is capped to
    # it.
    tally = {}
    for row in pending:
        tally[row["as_at_month"]] = tally.get(row["as_at_month"], 0) + 1
    reporting = max(tally, key=lambda m: (tally[m], m)) if tally else None
    for row in pending:
        if reporting and row["as_at_month"] > reporting:
            row["as_at_month"] = reporting
    rows = pending

    report["people"] = len(report["people"])
    report["months"] = sorted(m.isoformat() for m in report["months"])
    report["reporting_month"] = reporting.isoformat() if reporting else None
    return rows, report


def plan(rows):
    """What would be written → ``(entries, report)``.

    A figure is only written for a KPI the person's own card carries, and only
    where the platform cannot measure it for itself.
    """
    from .live_scorecard import resolve_person
    from .scorecard_automation.models import ScRoleKpiMapping
    from .scorecard_manual import MANUAL_ACTUALS

    entries, report = [], {
        "written": 0, "measured_here": 0, "not_on_their_card": 0,
        "no_person": [], "people": set(),
    }
    people = {}

    for row in rows:
        key = row["sales_code"] or row["staff_pf"]
        if key not in people:
            person = resolve_person(row["sales_code"]) if row["sales_code"] \
                else None
            people[key] = person
            if person is None or not person.role_code:
                report["no_person"].append({
                    "sales_code": row["sales_code"],
                    "staff_name": row["staff_name"], "role": row["role"],
                    "why": ("no sales code in the template"
                            if not row["sales_code"]
                            else "that sales code holds no card here"),
                })
        person = people[key]
        if person is None or not person.role_code:
            continue

        on_card = set(ScRoleKpiMapping.objects
                      .filter(role_code=person.role_code,
                              kpi_code__in=row["kpi_codes"])
                      .values_list("kpi_code", flat=True))
        if not on_card:
            # The sheet exists and this person's card does not read it. Not a
            # fault: a teller's card and a BOM's card share a template.
            report["not_on_their_card"] += 1
            continue

        for code in sorted(on_card):
            if code not in MANUAL_ACTUALS:
                report["measured_here"] += 1
                continue
            entries.append({
                "kind": "actual", "sales_code": row["sales_code"],
                "kpi_code": code, "value": row["value"],
                "sheet": row["sheet"], "how": row["how"],
                "as_at_month": row["as_at_month"]})
            report["written"] += 1
            report["people"].add(row["sales_code"])

    report["people"] = len(report["people"])
    # One line per person who reached nothing, not one per sheet they are on.
    seen, unique = set(), []
    for item in report["no_person"]:
        key = item["sales_code"] or item["staff_name"]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    report["no_person"] = unique
    return entries, report


def save(entries, who="", month=None):
    """Write the planned actuals, upserting so a reload corrects."""
    from django.db import transaction

    from .scorecard_automation.models import ScEmployeePerformanceActual
    from .scorecard_manual import _default_month

    month = month or _default_month()
    written = 0
    with transaction.atomic():
        for entry in entries:
            # ScEmployeePerformanceActual.save refuses an UPDATE without a
            # change reason - a correction to a figure somebody is paid on
            # should say who changed it - so update_or_create cannot be used.
            row, created = ScEmployeePerformanceActual.objects.get_or_create(
                sales_code=entry["sales_code"], kpi_code=entry["kpi_code"],
                eom_date=month, defaults={"kpi_value": entry["value"]})
            if not created:
                row.kpi_value = entry["value"]
                reason = (f"Back-office actuals template loaded by "
                          f"{who or 'an administrator'}")
                row._change_reason = reason[:100]
                row.save()
            written += 1
    return written


def read_upload(upload):
    """Read an uploaded template (an .xlsx, so openpyxl takes it directly)."""
    return read_workbook(upload)
