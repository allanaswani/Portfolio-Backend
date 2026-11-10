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
    if head.startswith(b"PK"):
        found = _read_liability(path)
        if found is not None:
            return (LEAVE,) + found
    raise HrReportError(
        "That is none of Aruti's reports this reads - the Employee Leave "
        "Balance List, the Leave Liability Report or the Employee Listing "
        "Report, as Aruti exports them.")


#: The Leave Liability Report's leave types: the heading word -> the code the
#: Leave Balance List uses, so both land in one table.
_LIABILITY_TYPES = {"annual": ("AL", "Annual Leave"),
                    "maternity": ("ML", "Maternity Leave"),
                    "paternity": ("PL", "Paternity Leave"),
                    "sick": ("SL", "Sick Leave")}


def _read_liability(path):
    """Aruti's ``Leave_Liability_Report_<stamp>.xlsb`` → ``(as_of, rows,
    report)``, or None when the file is not that report.

    First sheet "Leave_Liability_Report": "Date : 12-Oct-2026 11:00:03 AM",
    a heading row naming each leave type's Accrued / Consumed / Balance
    ("Annual Leave Accrued"), then "Employee ID" and a row per employee. The
    Leave line reads annual leave: taken (Consumed) over available (Accrued),
    as it does off the Leave Balance List, where B/F + adjustment + accrued
    is what this report calls Accrued (31 = 21 consumed + 10 balance).
    """
    try:
        from pyxlsb import open_workbook

        with open_workbook(path) as wb:
            name = next((n for n in wb.sheets
                         if n.strip().lower() == "leave_liability_report"), None)
            if name is None:
                return None
            with wb.get_sheet(name) as sheet:
                grid = [[c.v for c in r] for r in sheet.rows()]
    except Exception:  # noqa: BLE001 - not an xlsb this reads
        return None

    as_of, header_at = None, None
    for r, row in enumerate(grid[:20]):
        joined = " ".join(str(v) for v in row if v is not None)
        if as_of is None and joined.strip().startswith("Date"):
            found = _DATE.search(joined)
            as_of = _date(found.group(1)) if found else None
        if row and str(row[0] or "").strip().lower() == "employee id":
            header_at = r
            break
    if as_of is None or header_at is None or header_at == 0:
        raise HrReportError("That is not Aruti's Leave Liability Report: no "
                            "'Date :' or 'Employee ID' heading.")
    heading = [str(v or "").strip().lower() for v in grid[header_at]]
    kinds = [str(v or "").strip().lower() for v in grid[header_at - 1]]
    col = {"pf": 0}
    for c, h in enumerate(heading):
        if h == "staff name":
            col["name"] = c
        elif h == "hire date":
            col["joined"] = c
    types = {}
    for c, k in enumerate(kinds):
        parts = k.split()
        if len(parts) == 3 and parts[1] == "leave" and parts[0] in _LIABILITY_TYPES                 and parts[2] in ("accrued", "consumed", "balance"):
            types.setdefault(parts[0], {})[parts[2]] = c
    if "annual" not in types or len(types["annual"]) != 3 or "name" not in col:
        raise HrReportError("The Leave Liability Report is missing its Staff "
                            "Name or Annual Leave Accrued / Consumed / Balance "
                            "columns.")

    rows, mismatched = [], 0
    for row in grid[header_at + 1:]:
        pf = str(row[0] if row else "").strip().replace(".0", "")
        if not pf.isdigit():
            continue
        for word, cols in types.items():
            if len(cols) != 3:
                continue
            code, label = _LIABILITY_TYPES[word]
            get = lambda c: _num(row[c]) if c < len(row) and row[c] is not None else 0.0
            record = {"pf_number": int(pf), "leave_code": code, "leave_name": label,
                      "name": str(row[col["name"]] or "").strip(),
                      "joined": _date(row[col["joined"]]) if "joined" in col else None,
                      "period_start": None, "period_end": None,
                      "bf": 0.0, "adjustment": 0.0, "encashment": 0.0,
                      "accrued": get(cols["accrued"]), "issued": get(cols["consumed"]),
                      "balance": get(cols["balance"])}
            if None in (record["accrued"], record["issued"], record["balance"]):
                continue
            if abs(record["accrued"] - record["issued"] - record["balance"]) > 0.011:
                mismatched += 1
            rows.append(record)

    # One row per person and leave type: a PF listed twice keeps its first.
    seen, unique = set(), []
    for record in rows:
        key = (record["pf_number"], record["leave_code"])
        if key not in seen:
            seen.add(key)
            unique.append(record)
    by_type = {}
    for record in unique:
        by_type[record["leave_code"]] = by_type.get(record["leave_code"], 0) + 1
    return as_of, unique, {"by_leave_type": by_type, "rows": len(unique),
                           "balance_does_not_add_up": mismatched,
                           "source": "Leave Liability Report"}


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
