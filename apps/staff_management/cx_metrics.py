"""Customer-experience figures: reading CX's workbook, and serving the card.

Two scorecard lines were unscoreable because the numbers lived in an Excel the
CX team e-mailed round — "NPS" (target 60%) and "Portfolio Coverage
(engagement)" (target 80%). This is where those figures live now.

The shape is CX's own file, ``RM Contactability, Satisfaction & Segment NPS &
CES Q2 2026.xlsx``, so the first load is their workbook and nothing is re-keyed:

===================  ==========================  ==========================
sheet                column                      scorecard line
===================  ==========================  ==========================
Contactability       ``RM Name``, ``%Contactability``  Portfolio Coverage
Satisfaction         ``RM Name``, ``% CSAT``           NPS
NPS & CES Summary    segment, ``NPS``, ``CES``         per segment, no RM
===================  ==========================  ==========================

Three things in that file are decisions, not data
─────────────────────────────────────────────────

**The NPS line is fed by CSAT.** The card line is called NPS; the figure behind
it is the RM's CSAT from the Satisfaction sheet, which is what the business
uses. The per-segment NPS in the summary sheet is a different measure and is
not per RM, so it cannot feed a personal card. Stored under its own name
rather than relabelled, so nobody later mistakes one for the other.

**"TSC- Give full marks" is a rule.** Four RMs in the Q2 file carry that text
where a percentage would be, because they are TSC-scheme RMs the measure does
not apply to. Writing 1.0 would make a business rule indistinguishable from a
measured 100%; writing 0 would score them nought on something that does not
apply. So the figure stays NULL, ``full_marks`` is set, and the card scores the
line at exactly full marks and says why.

**The file has no sales code.** It is keyed on the RM's name, so a name has to
be resolved against the roster. A name that matches nobody is reported, never
guessed at — the same rule the property return follows, and for the same
reason: a mis-spelt name and a genuinely missing figure look identical.
"""

from __future__ import annotations

import datetime
import re

#: The sheets, and which column holds the figure. Matched on the header text
#: rather than a column number, because a column gets inserted eventually.
SHEETS = {
    "contactability": {"sheet": "Contactability", "field": "contactability",
                       "headers": ("%contactability", "contactability")},
    "csat": {"sheet": "Satisfaction", "field": "csat",
             "headers": ("% csat", "csat", "%csat")},
}

SUMMARY_SHEET = "NPS & CES Summary"

#: What marks an RM the measure does not apply to. Matched loosely because it
#: is free text a person typed: "TSC- Give full marks", "TSC - give full
#: marks", and so on.
FULL_MARKS = re.compile(r"full\s*marks", re.I)


def fold_name(name):
    """A name reduced to something comparable.

    Collapses whitespace and case, drops punctuation. The Q2 file has
    "Winfred Kivuva  " with two trailing spaces, which is exactly the kind of
    thing that otherwise costs somebody their score.
    """
    text = re.sub(r"[^a-z ]", " ", str(name or "").lower())
    return " ".join(text.split())


def period_of(text="", today=None):
    """``2026-Q2`` from whatever is given, else the quarter we are in.

    Accepts "Q2 2026", "2026-Q2", "2026-06" and a bare filename containing
    one of those, because the period is usually read off the workbook's name.
    """
    raw = str(text or "").strip()
    found = re.search(r"(20\d{2})\s*[-_ ]?\s*Q([1-4])", raw, re.I)
    if found:
        return f"{found.group(1)}-Q{found.group(2)}"
    found = re.search(r"Q([1-4])\s*[-_ ]?\s*(20\d{2})", raw, re.I)
    if found:
        return f"{found.group(2)}-Q{found.group(1)}"
    found = re.search(r"(20\d{2})[-_](0[1-9]|1[0-2])", raw)
    if found:
        return f"{found.group(1)}-{found.group(2)}"
    today = today or datetime.date.today()
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


def _number(value):
    """A percentage, or None. ``full_marks`` is handled by the caller."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        # CX write 0.33 for a third. A value above 1 is a percentage somebody
        # typed as 33 rather than 0.33, so it is brought to the same scale -
        # otherwise it scores 3,300% against a 60% target.
        return number / 100 if number > 1.5 else number
    text = str(value).strip().replace("%", "").replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number / 100 if number > 1.5 else number


def roster_names():
    """Every name the platform knows, folded → sales code.

    All three rosters, because a CX file covers RMs who may be on any of them.
    Built once per load rather than per row.
    """
    from .live_scorecard import role_code_for
    from .models import (
        BranchEmployeeDmcData, BranchFinalEmployeeDmcData, EmployeeRoleHistory,
        StaffEmployeeData,
    )

    out = {}

    def remember(name, code):
        folded = fold_name(name)
        code = (code or "").strip().upper()
        if folded and code and folded not in out:
            out[folded] = code

    for model in (BranchEmployeeDmcData, BranchFinalEmployeeDmcData):
        for name, code, role in model.objects.exclude(sales_code="").values_list(
                "staff_name", "sales_code", "staff_role"):
            # Only people who hold a card: a name that matches a non-sales
            # employee would attach a CX figure to somebody with no scorecard.
            if role_code_for(role) is not None:
                remember(name, code)
    for name, code in StaffEmployeeData.objects.exclude(
            sales_code="").values_list("staff_name", "sales_code"):
        remember(name, code)
    # The back-office roster keeps the name in notes - see migration 0032.
    for code, notes in EmployeeRoleHistory.objects.filter(
            role_code__startswith="bo_").values_list("sales_code", "notes"):
        remember((notes or "").split("|")[0], code)
    return out


def read_workbook(stream, filename=""):
    """Read CX's workbook → ``(rm_rows, segment_rows, report)``.

    Nothing is written. Every RM name is resolved against the roster here, so
    the report can say what did not match before anybody commits to saving it.
    """
    from openpyxl import load_workbook

    book = load_workbook(stream, data_only=True)
    names = roster_names()
    period = period_of(filename or "")

    rows, report = {}, {
        "period": period, "sheets_read": [], "sheets_missing": [],
        "rm_names": 0, "unmatched_names": [], "full_marks": [],
        "ignored_values": [],
    }

    for key, spec in SHEETS.items():
        if spec["sheet"] not in book.sheetnames:
            report["sheets_missing"].append(spec["sheet"])
            continue
        sheet = book[spec["sheet"]]
        report["sheets_read"].append(spec["sheet"])

        # Find the header row and the two columns by their text. The sheet also
        # carries pivot tables further right, which must not be mistaken for
        # the data - so only the FIRST matching column is taken.
        name_column = value_column = header_row = None
        for row in range(1, min(sheet.max_row, 12) + 1):
            labels = {
                column: str(sheet.cell(row=row, column=column).value or "")
                .strip().lower()
                for column in range(1, min(sheet.max_column, 10) + 1)
            }
            for column, label in sorted(labels.items()):
                if label in ("rm name", "rm") and name_column is None:
                    name_column, header_row = column, row
                if label in spec["headers"] and value_column is None:
                    value_column = column
            if name_column and value_column:
                break
        if not (name_column and value_column):
            report["sheets_missing"].append(
                f"{spec['sheet']} (no 'RM Name' and "
                f"'{spec['headers'][0]}' header)")
            continue

        for row in range(header_row + 1, sheet.max_row + 1):
            raw_name = sheet.cell(row=row, column=name_column).value
            if raw_name is None or not str(raw_name).strip():
                continue
            name = str(raw_name)
            if fold_name(name) in ("grand total", "total", "average"):
                continue
            raw = sheet.cell(row=row, column=value_column).value

            entry = rows.setdefault(name, {
                "period": period, "rm_name": name,
                "sales_code": names.get(fold_name(name), ""),
                "contactability": None, "csat": None,
                "full_marks": False, "note": "",
                "source": (filename or "")[:160],
            })
            if isinstance(raw, str) and FULL_MARKS.search(raw):
                entry["full_marks"] = True
                entry["note"] = raw.strip()[:160]
                continue
            value = _number(raw)
            if value is None:
                if raw not in (None, ""):
                    report["ignored_values"].append(
                        {"sheet": spec["sheet"], "rm_name": name,
                         "value": str(raw)[:60]})
                continue
            entry[spec["field"]] = value

    report["rm_names"] = len(rows)
    report["unmatched_names"] = sorted(
        entry["rm_name"] for entry in rows.values() if not entry["sales_code"])
    report["full_marks"] = sorted(
        entry["rm_name"] for entry in rows.values() if entry["full_marks"])

    segments = []
    if SUMMARY_SHEET in book.sheetnames:
        report["sheets_read"].append(SUMMARY_SHEET)
        sheet = book[SUMMARY_SHEET]
        for row in range(1, sheet.max_row + 1):
            label = sheet.cell(row=row, column=1).value
            if label is None or not str(label).strip():
                continue
            text = str(label).strip()
            if fold_name(text) in ("row labels", "segment"):
                continue
            nps = _number(sheet.cell(row=row, column=2).value)
            ces = _number(sheet.cell(row=row, column=3).value)
            if nps is None and ces is None:
                continue
            segments.append({
                "period": period, "segment": text[:80], "nps": nps, "ces": ces,
                "is_overall": "overall" in fold_name(text),
            })
    else:
        report["sheets_missing"].append(SUMMARY_SHEET)
    report["segments"] = len(segments)

    return list(rows.values()), segments, report


def save(rm_rows, segment_rows, who=""):
    """Write one period, replacing what was there for it.

    Upsert on (period, RM) and (period, segment), so a correction replaces the
    figure rather than stacking a second one beside it. A row the new file does
    not mention is LEFT ALONE rather than deleted: CX sometimes send a
    partial correction, and deleting the rest would silently blank scores.
    """
    from django.db import transaction

    from .models import CxRmMetric, CxSegmentMetric

    written = {"rm": 0, "segments": 0}
    with transaction.atomic():
        for row in rm_rows:
            row = dict(row)
            period, name = row.pop("period"), row.pop("rm_name")
            row["updated_by"] = who[:150]
            CxRmMetric.objects.update_or_create(
                period=period, rm_name=name, defaults=row)
            written["rm"] += 1
        for row in segment_rows:
            row = dict(row)
            period, segment = row.pop("period"), row.pop("segment")
            row["updated_by"] = who[:150]
            CxSegmentMetric.objects.update_or_create(
                period=period, segment=segment, defaults=row)
            written["segments"] += 1
    return written


# ─────────────────────────────────────────────────────────────────────────────
# What the scorecard reads
# ─────────────────────────────────────────────────────────────────────────────


def latest_period():
    """The newest period loaded, or None.

    Newest by string, which sorts correctly for both ``2026-Q2`` and
    ``2026-06`` — the reason the period is stored in that shape.

    Both tables are asked. A period can hold segment figures and no RM rows —
    CX's summary sheet is filled in before the per-RM sheets on a bad quarter —
    and reading only the RM table would make that period invisible.
    """
    from .models import CxRmMetric, CxSegmentMetric

    found = [
        model.objects.order_by("-period").values_list(
            "period", flat=True).first()
        for model in (CxRmMetric, CxSegmentMetric)
    ]
    found = [period for period in found if period]
    return max(found) if found else None


def for_rm(sales_code, period=None):
    """This RM's CX figures → a dict, or None if CX have nothing for them.

    ``{"period", "contactability", "csat", "full_marks", "note", "rm_name"}``
    """
    from .models import CxRmMetric

    code = (sales_code or "").strip()
    if not code:
        return None
    period = period or latest_period()
    if not period:
        return None
    row = (CxRmMetric.objects
           .filter(period=period, sales_code__iexact=code)
           .order_by("-updated_at").first())
    if row is None:
        return None
    return {
        "period": row.period, "rm_name": row.rm_name,
        "contactability": row.contactability, "csat": row.csat,
        "full_marks": row.full_marks, "note": row.note,
    }


def coverage(period=None):
    """How much of the roster CX have figures for, and what is unmatched.

    The number worth watching: a name CX spell differently from the roster is
    an RM with no score, and it looks exactly like an RM CX did not survey.
    """
    from .models import CxRmMetric, CxSegmentMetric

    period = period or latest_period()
    if not period:
        return {"period": None, "rm_rows": 0, "matched": 0, "unmatched": [],
                "full_marks": 0, "with_contactability": 0, "with_csat": 0,
                "segments": 0, "periods": []}

    periods = set(CxRmMetric.objects.values_list("period", flat=True))
    periods |= set(CxSegmentMetric.objects.values_list("period", flat=True))

    rows = list(CxRmMetric.objects.filter(period=period))
    return {
        "period": period,
        "periods": sorted(periods, reverse=True),
        "rm_rows": len(rows),
        "matched": sum(1 for row in rows if row.sales_code),
        "unmatched": sorted(row.rm_name for row in rows if not row.sales_code),
        "full_marks": sum(1 for row in rows if row.full_marks),
        "with_contactability": sum(
            1 for row in rows if row.contactability is not None),
        "with_csat": sum(1 for row in rows if row.csat is not None),
        "segments": CxSegmentMetric.objects.filter(period=period).count(),
    }
