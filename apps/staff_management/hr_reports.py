"""Aruti's HR reports: the leave balance list and the employee listing.

Both come out of Aruti named ``.xls`` and are two different formats:

* ``Employee_Leave_Balance_List_<stamp>.xls`` - a real BIFF ``.xls`` (read
  with xlrd). "Employee Leave Balance List [Leave Type Wise]", "As On Date :
  08-Oct-2026": a block per leave type (AL, CL, ML, PL, SL), a row per
  employee: B/F, adjustment, accrued to date, encashment, issued to date and
  the balance. The balance is B/F + adjustment + accrued - encashment -
  issued, and is checked as it is read.
* ``Employee_Listing_Report_<month>.xls`` - Excel 2003 XML that Aruti saves
  with an ``.xls`` name. "Employee Listing Report", "Date : 20-Aug-2026": a row
  per employee - code, name, branch, department, job, grade, email, dates.

Each file is a SNAPSHOT as at the date it states, so reports from different
months sit side by side and loading the same date again replaces only that
date. What a card does not use is not stored: the listing's birth date, age,
gender, bank and membership columns are dropped as they are read.
"""

from __future__ import annotations

import datetime
import re

LEAVE = "leave_balance"
LISTING = "employee_listing"

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # a real .xls
_DATE = re.compile(r"(\d{1,2}-[A-Za-z]{3}-\d{4})")

#: The listing's headings → what is kept. Everything else is dropped.
LISTING_KEEP = {
    "employee code": "pf_number", "employee name": "name",
    "branch": "branch", "department group": "department_group",
    "department": "department", "section": "section", "job": "job",
    "grade": "grade", "employment type": "employment_type",
    "date hired": "date_hired", "email": "email",
    "end of contract": "end_of_contract",
    "eoc/leaving reason": "leaving_reason",
}


class HrReportError(Exception):
    """The file could not be read - with a reason fit to show."""


def _date(text):
    text = str(text or "").strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text[:11], fmt).date()
        except ValueError:
            continue
    return None


def _num(value):
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except ValueError:
        return None


def detect(head):
    """The first bytes of the file → LEAVE, LISTING or None."""
    if head.startswith(_OLE):
        return LEAVE
    text = head[:400].decode("utf-8", "ignore").lstrip("﻿").lstrip()
    if text.startswith("<?xml") and "urn:schemas-microsoft-com:office" \
            in head[:2000].decode("utf-8", "ignore"):
        return LISTING
    return None


def read(path):
    """→ ``(kind, as_of, rows, report)``."""
    with open(path, "rb") as fh:
        head = fh.read(4096)
    kind = detect(head)
    if kind == LEAVE:
        return (kind,) + _read_leave(path)
    if kind == LISTING:
        return (kind,) + _read_listing(path)
    raise HrReportError(
        "That is neither of Aruti's reports - the Employee Leave Balance List "
        "or the Employee Listing Report, as Aruti exports them.")


def _read_leave(path):
    import xlrd

    try:
        sheet = xlrd.open_workbook(path).sheet_by_index(0)
    except Exception as exc:  # noqa: BLE001
        raise HrReportError(f"That leave report could not be opened: {exc}")
    cells = lambda r: [sheet.cell_value(r, c) for c in range(sheet.ncols)]

    as_of, header_at = None, None
    for r in range(min(sheet.nrows, 20)):
        joined = " ".join(str(v) for v in cells(r))
        if as_of is None and "As On Date" in joined:
            found = _DATE.search(joined.split("As On Date", 1)[1])
            as_of = _date(found.group(1)) if found else None
        if "Emp Code" in joined:
            header_at = r
            break
    if as_of is None or header_at is None:
        raise HrReportError("That is not Aruti's Employee Leave Balance List: "
                            "no 'As On Date' or 'Emp Code' heading.")

    # The columns, by heading - not by position, so a re-ordered export
    # still reads right.
    heading = {str(v).strip().lower(): c for c, v in enumerate(cells(header_at))
               if str(v).strip()}
    want = {"emp code": "pf", "employee": "name", "joining date": "joined",
            "start date": "start", "end date": "end", "leave b/f": "bf",
            "leave adjustment": "adjustment",
            "total accrued year to date": "accrued",
            "encashment": "encashment",
            "total issued year to date": "issued",
            "balance year to date": "balance"}
    missing = [h for h in want if h not in heading]
    if missing:
        raise HrReportError(f"The leave report is missing: {', '.join(missing)}")
    col = {key: heading[h] for h, key in want.items()}

    rows, mismatched, code, name = [], 0, None, ""
    for r in range(header_at + 1, sheet.nrows):
        row = cells(r)
        if str(row[2]).strip() == "Code :":          # a leave-type block
            code = str(row[3]).strip()
            name = next((str(v).strip() for v in row[8:]
                         if str(v).strip() and str(v).strip() != "Leave :"), "")
            continue
        pf = str(row[col["pf"]]).strip()
        if code is None or not pf.replace(".0", "").isdigit():
            continue
        record = {
            "pf_number": int(float(pf)), "leave_code": code, "leave_name": name,
            "name": str(row[col["name"]]).strip(),
            "joined": _date(row[col["joined"]]),
            "period_start": _date(row[col["start"]]),
            "period_end": _date(row[col["end"]]),
        }
        for key in ("bf", "adjustment", "accrued", "encashment", "issued",
                    "balance"):
            record[key] = _num(row[col[key]])
        expected = (record["bf"] + record["adjustment"] + record["accrued"]
                    - record["encashment"] - record["issued"])
        if abs(expected - record["balance"]) > 0.011:
            mismatched += 1
        rows.append(record)

    by_type = {}
    for row in rows:
        by_type[row["leave_code"]] = by_type.get(row["leave_code"], 0) + 1
    return as_of, rows, {"by_leave_type": by_type, "rows": len(rows),
                         "balance_does_not_add_up": mismatched}


def _read_listing(path):
    import xml.etree.ElementTree as ET

    ns = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise HrReportError(f"That listing could not be read: {exc}")
    sheet = root.find("ss:Worksheet", ns)
    if sheet is None:
        raise HrReportError("That listing has no worksheet.")
    texts = [[(d.text or "").strip()
              for c in row.findall("ss:Cell", ns)
              for d in c.findall("ss:Data", ns)]
             for row in sheet.findall("ss:Table/ss:Row", ns)]

    as_of, header_at = None, None
    for i, row in enumerate(texts[:15]):
        if as_of is None and row and row[0].lower().startswith("date"):
            found = _DATE.search(" ".join(row))
            as_of = _date(found.group(1)) if found else None
        if row and row[0].lower() == "employee code":
            header_at = i
            break
    if as_of is None or header_at is None:
        raise HrReportError("That is not Aruti's Employee Listing Report: no "
                            "'Date' or 'Employee Code' heading.")
    heading = [h.strip().lower() for h in texts[header_at]]
    keep = {i: LISTING_KEEP[h] for i, h in enumerate(heading)
            if h in LISTING_KEEP}

    rows = []
    for row in texts[header_at + 1:]:
        if not row or not row[0].replace(".0", "").isdigit():
            continue
        record = {}
        for i, key in keep.items():
            value = row[i] if i < len(row) else ""
            if key in ("date_hired", "end_of_contract"):
                record[key] = _date(value)
            elif key == "pf_number":
                record[key] = int(float(value))
            else:
                record[key] = value
        rows.append(record)
    return as_of, rows, {"rows": len(rows),
                         "with_email": sum(1 for r in rows if r.get("email"))}


def replace_snapshot(kind, as_of, rows):
    """Replace the snapshot for that date - one transaction. → rows written."""
    from django.db import transaction

    from .models import HrEmployeeListing, HrLeaveBalance

    model = HrLeaveBalance if kind == LEAVE else HrEmployeeListing
    with transaction.atomic():
        model.objects.filter(as_of=as_of).delete()
        model.objects.bulk_create([model(as_of=as_of, **row) for row in rows],
                                  batch_size=2000)
    return len(rows)


def snapshots(kind):
    """The dates already held for that report → [date]."""
    from .models import HrEmployeeListing, HrLeaveBalance

    model = HrLeaveBalance if kind == LEAVE else HrEmployeeListing
    return sorted(model.objects.values_list("as_of", flat=True).distinct())


def leave_cleared(pf_number, upto=None):
    """Annual leave cleared, from the newest Aruti leave report on or before
    ``upto`` → ``(share, as_of, label, problem)``.

    The card's line is "Clear leave days before EOY", target 1. The share is
    days TAKEN over days AVAILABLE so far - brought forward, plus adjustment,
    plus accrued to the report's date - so at the year end, when everything
    has accrued, it is exactly the share of the year's leave cleared.

    Only a report dated on or before the card's month: an October report on
    an August card would score August on leave taken in September.
    """
    from .models import HrLeaveBalance

    pf = str(pf_number or "").strip()
    if not pf.isdigit():
        return None, None, None, ("the leave report is keyed on the PF number, "
                                  "and none is recorded for this person")
    rows = HrLeaveBalance.objects.filter(pf_number=int(pf), leave_code="AL")
    if upto is not None:
        rows = rows.filter(as_of__lte=upto)
    row = rows.order_by("-as_of").first()
    if row is None:
        newest = (HrLeaveBalance.objects.order_by("-as_of")
                  .values_list("as_of", flat=True).first())
        if newest is None:
            return None, None, None, (
                "no Aruti leave report has been loaded yet - Scorecards → "
                "Figures to load → Load Aruti HR reports")
        if upto is not None and newest > upto:
            return None, None, None, (
                f"the leave report loaded is as at {newest:%d %b %Y}, after "
                f"this card's month; none is loaded for {upto:%B %Y} or "
                f"before")
        return None, None, None, (
            f"PF {pf} is not on the annual-leave list of the Aruti leave "
            f"report as at {newest:%d %b %Y}")
    available = (row.bf or 0) + (row.adjustment or 0) + (row.accrued or 0)
    if available <= 0:
        return None, row.as_of, None, (
            f"no annual leave was available to PF {pf} as at "
            f"{row.as_of:%d %b %Y}, so there was none to clear")
    taken = row.issued or 0
    label = (f"{taken:g} of {available:.2f} days taken (Aruti, as at "
             f"{row.as_of:%d %b %Y})")
    return taken / available, row.as_of, label, None
