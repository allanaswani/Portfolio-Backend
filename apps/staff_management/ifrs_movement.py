"""Finance's IFRS movement workbook → ``loans_mom_ifrs_movement``, a month at
a time.

``3. FS_MOM_IFRS_MOVEMENT_Branch & TREND (with Special Assets).xlsb`` has a
sheet per month ("Jan 2026" … "Aug 2026"), a row per loan account, and its
first 26 columns ARE the table's columns, in the same order.

**Why this exists.** The table stopped at **1 July 2025**: on the host,
``max(eom_date)`` is 2025-07-01 and there is not one 2026 row. It was never fed
by an ETL - the old system had a CSV upload (``LoansMomIFRSMovementCSVUpload
View``) that somebody used every month, and that upload was not carried into
this backend. So every card's PAR and Loan Loss line, and every arrears page
that reads this table, has been reading July 2025 all year.

**Same behaviour as the old upload**: a month is REPLACED - its rows deleted,
the workbook's inserted - so loading a month twice never doubles it.
``eom_date`` is the FIRST of the month, as the table already holds it.

One month per call: the file is ~21 MB and a month sheet tens of thousands of
rows, so the screen loads the months one request at a time rather than ask one
request to read all eight.
"""

from __future__ import annotations

import datetime
import re

#: The workbook's header → the table's column. The first 26 columns; the
#: rest (NET, Targets, SYNOPSIS_*, segmentations, Finance, Source) are the
#: workbook's own working and have no column in the table.
COLUMNS = {
    "lns_accoun": "lns_account",
    "prev_gross": "prev_gross",
    "current_gross": "current_gross",
    "prev_ifrs": "prev_ifrs",
    "current_ifrs": "current_ifrs",
    "prev_grade": "prev_grade",
    "current_grade": "current_grade",
    "movt_in_gross": "movt_in_gross",
    "movt_in_ifrs": "movt_in_ifrs",
    "narration_status": "narration_status",
    "write_off_amount": "write_off_amount",
    "adjusted_opening_ifrs": "adjusted_opening_ifrs",
    "customer_name": "customer_name",
    "p&l_charge": "pl_charge",
    "cust_code": "cust_code",
    "description": "description",
    "segment": "segment",
    "int. adj": "int_adj",
    "cust code - strategy": "cust_code_strategy",
    "new segmentation": "new_segmentation",
    "branch": "branch",
    "branch2": "branch2",
    "comments": "comments",
    "increase_writeback": "increase_writeback",
    "product": "product",
    "product_desc": "product_desc",
}

NUMBERS = {"prev_gross", "current_gross", "prev_ifrs", "current_ifrs",
           "movt_in_gross", "movt_in_ifrs", "write_off_amount",
           "adjusted_opening_ifrs", "pl_charge", "int_adj"}

#: Columns that hold an identifier: a whole number is written as digits, so
#: 250003405.0 becomes "250003405" - the card joins TRIM(lns_account) to the
#: loan account number, and "250003405.0" would match nothing.
IDENTIFIERS = {"lns_account", "cust_code_strategy", "product", "cust_code"}

_SHEET = re.compile(r"^(?P<mon>[A-Za-z]{3})[a-z]*\s+(?P<year>\d{4})$")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


class IfrsWorkbookError(Exception):
    """The workbook could not be read - with a reason fit to show."""


def month_of(sheet_name):
    """"Aug 2026" → date(2026, 8, 1), or None for a sheet that is not a
    month (rm_summary, CUSTOMER SUMMARY_2026, ...)."""
    match = _SHEET.match(str(sheet_name or "").strip())
    if not match:
        return None
    month = _MONTHS.get(match.group("mon").lower())
    return datetime.date(int(match.group("year")), month, 1) if month else None


def months_in(path):
    """The month sheets the workbook holds → {date: sheet name}."""
    from pyxlsb import open_workbook

    try:
        with open_workbook(str(path)) as book:
            names = list(book.sheets)
    except Exception as exc:  # noqa: BLE001
        raise IfrsWorkbookError(f"That workbook could not be opened: {exc}")
    found = {month_of(name): name for name in names if month_of(name)}
    if not found:
        raise IfrsWorkbookError(
            "That workbook has no month sheets (\"Jan 2026\", \"Feb 2026\" ...). "
            "It should be Finance's FS_MOM_IFRS_MOVEMENT file.")
    return found


def _clean(field, value):
    if value is None or value == "":
        return None
    if field in NUMBERS:
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if field in IDENTIFIERS and isinstance(value, float) \
            and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def read_month(path, sheet):
    """One month sheet → (rows as dicts, totals for checking)."""
    from pyxlsb import open_workbook

    with open_workbook(str(path)) as book:
        with book.get_sheet(sheet) as ws:
            rows = [[cell.v for cell in row] for row in ws.rows()]
    if not rows:
        raise IfrsWorkbookError(f"{sheet} is empty")
    header = [str(v or "").strip().lower() for v in rows[0]]
    where = {COLUMNS[h]: i for i, h in enumerate(header) if h in COLUMNS}
    missing = sorted(set(COLUMNS.values()) - set(where))
    if missing:
        raise IfrsWorkbookError(
            f"{sheet} is missing column(s) the table needs: "
            f"{', '.join(missing)}")

    out = []
    for raw in rows[1:]:
        raw = list(raw) + [None] * (len(header) - len(raw))
        record = {field: _clean(field, raw[i]) for field, i in where.items()}
        if not record["lns_account"]:
            continue
        out.append(record)
    totals = {
        "rows": len(out),
        "current_gross": sum(r["current_gross"] or 0 for r in out),
        "pl_charge": sum(r["pl_charge"] or 0 for r in out),
        "int_adj": sum(r["int_adj"] or 0 for r in out),
    }
    return out, totals


def replace_month(month, rows):
    """Delete the month's rows and insert these - one transaction, so a
    failure leaves the month as it was. → rows written."""
    from django.db import transaction

    from apps.portfolio.models import LoansMomIFRSMovement

    with transaction.atomic():
        LoansMomIFRSMovement.objects.filter(eom_date=month).delete()
        LoansMomIFRSMovement.objects.bulk_create(
            [LoansMomIFRSMovement(eom_date=month, **row) for row in rows],
            batch_size=5000)
    return len(rows)


def months_held():
    """The months the table already holds → [date], newest last."""
    from apps.portfolio.models import LoansMomIFRSMovement

    return sorted(LoansMomIFRSMovement.objects.values_list(
        "eom_date", flat=True).distinct())
