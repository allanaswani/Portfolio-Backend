"""Finance's monthly Branch Accounts workbook → the branch manager's Operating Profit.

The branch card's Operating Profit line reads the template's Revenue_Contribution
sheet, which the desk labels "Without Hqcost". Finance's Branch Accounts workbook
(``Branch Accounts October 2026 - share.xlsx``) is where that figure comes from:

    September year to date, for all 22 branches, to the shilling =
        the sum of Branch_PBT_Movement's monthly "PBT after Provisions
        (ex-HQ cost, Income & Bancassurance)", January to September, x 1,000
      + the branch's Bancassurance commission, January to September
        (the "Bancassurance " sheet).

Without the commission 17 of 22 were within 2%; with it, 22 of 22 exact
(checked 19 Nov 2026 against the desk's September figures).

The branch manager's "Reduce P&L provisions" line (template sheet PL_Charge)
is the same workbook's Provisions sheet: each month's "Loan Loss" (P&L charge
less interest adjustment) summed from January - River Road's January to
September is 20,485,640.48, the desk's September figure, which the template
holds as a negative. Its "Loan Loss Provisions YTD" total (39,574,887.20) is
the card's 2025 base.

Branch_PBT_Movement is in thousands of shillings; the Bancassurance and
Provisions sheets are in shillings. No warehouse or lake table holds the branch P&L after head-office
cost - Finance's allocation is in this workbook only - so each month's file is
the source for that month, the way the desk's Weighted TAT Dashboard is.
"""

from __future__ import annotations

import re

#: BoWorkbookFile.kind for a year's figures: ``branch_accounts:2026``.
KIND = "branch_accounts:{year}"

#: Branch_PBT_Movement is in KES '000 (River Road January 6,619.65 is the
#: desk's 6,619,654.77).
PBT_UNIT = 1000

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")
_MTD = re.compile(r"^\s*([A-Za-z]+)\s+(\d{4})\s+MTD\s*$", re.I)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _code(value):
    """A branch code cell (200, 200.0, "200") → 200, else None."""
    if _number(value):
        return int(value) if float(value).is_integer() else None
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _sheet(workbook, wanted):
    for ws in workbook.worksheets:
        if ws.title.strip().lower() == wanted:
            return ws
    raise ValueError(f"the workbook has no '{wanted}' sheet")


def _pbt(ws):
    """Branch_PBT_Movement → (year, {code: {month: KES}}, {code: name})."""
    rows = list(ws.iter_rows(max_row=60, max_col=40, values_only=True))
    for h, header in enumerate(rows):
        cells = [str(c or "").strip().lower() for c in header]
        if "branch code" in cells:
            break
    else:
        raise ValueError("Branch_PBT_Movement has no 'Branch Code' heading")
    code_col = cells.index("branch code")
    name_col = cells.index("branch") if "branch" in cells else None
    columns, years = {}, set()
    for c, text in enumerate(header):
        m = _MTD.match(str(text or ""))
        if m and m.group(1)[:3].lower() in _MONTHS:
            columns[c] = _MONTHS.index(m.group(1)[:3].lower()) + 1
            years.add(int(m.group(2)))
    if not columns:
        raise ValueError("Branch_PBT_Movement has no '<Month> <Year> MTD' columns")
    if len(years) != 1:
        raise ValueError(f"Branch_PBT_Movement spans more than one year: {sorted(years)}")
    figures, names = {}, {}
    for row in rows[h + 1:]:
        code = _code(row[code_col]) if code_col < len(row) else None
        if code is None:
            continue
        names[code] = str(row[name_col] or "").strip() if name_col is not None else ""
        figures[code] = {month: float(row[c]) * PBT_UNIT
                         for c, month in columns.items()
                         if c < len(row) and _number(row[c])}
    return years.pop(), figures, names


def _banca(ws, year):
    """The Bancassurance commission sheet → {code: {month: KES}} for ``year``."""
    import datetime

    rows = list(ws.iter_rows(max_row=80, max_col=40, values_only=True))
    if not rows:
        return {}
    columns = {c: v.month for c, v in enumerate(rows[0])
               if isinstance(v, (datetime.date, datetime.datetime)) and v.year == year}
    out = {}
    for row in rows[1:]:
        code = _code(row[0]) if row else None
        if code is None:
            continue
        out[code] = {month: float(row[c]) for c, month in columns.items()
                     if c < len(row) and _number(row[c])}
    return out


_LOSS = re.compile(r"^\s*([A-Za-z]+)\s+(\d{4})\s+Loan Loss\s*$", re.I)


def _provisions(workbook, year):
    """The Provisions sheet → {code: {month: loan loss}} for ``year``, or {}
    when the workbook has no such sheet."""
    try:
        ws = _sheet(workbook, "provisions")
    except ValueError:
        return {}
    rows = list(ws.iter_rows(max_row=80, max_col=120, values_only=True))
    for h, header in enumerate(rows):
        if any(str(c or "").strip().lower() == "ytd loan loss" for c in header):
            break
    else:
        return {}
    columns = {}
    for c, text in enumerate(header):
        m = _LOSS.match(str(text or ""))
        if m and int(m.group(2)) == year and m.group(1)[:3].lower() in _MONTHS:
            columns[c] = _MONTHS.index(m.group(1)[:3].lower()) + 1
    out = {}
    for row in rows[h + 1:]:
        code = _code(row[0]) if row else None
        if code is None:
            continue
        out[code] = {month: float(row[c]) for c, month in columns.items()
                     if c < len(row) and _number(row[c])}
    return out


def _running(months_by_code, latest):
    """{code: {month: value}} → {code: [Jan..Dec year to date, None past latest]}."""
    out = {}
    for code, months in months_by_code.items():
        running, series = 0.0, []
        for month in range(1, 13):
            if month > latest:
                series.append(None)
                continue
            running += months.get(month, 0.0)
            series.append(round(running, 2))
        out[code] = series
    return out


def read(stream):
    """The workbook → {"year", "latest_month", "ytd": {code: [Jan..Dec YTD or
    None]}, "names", "pbt", "banca"}. ``latest_month`` is the last month the
    PBT sheet has a figure for; no year to date is given past it."""
    import warnings

    import openpyxl

    with warnings.catch_warnings():
        # The workbook's print areas and conditional formatting: not data.
        warnings.simplefilter("ignore")
        workbook = openpyxl.load_workbook(stream, read_only=True, data_only=True)
        try:
            year, pbt, names = _pbt(_sheet(workbook, "branch_pbt_movement"))
            banca = _banca(_sheet(workbook, "bancassurance"), year)
            loss = _provisions(workbook, year)
        finally:
            workbook.close()
    latest = max((m for months in pbt.values() for m in months), default=0)
    # Each month: the PBT plus that month's bancassurance commission.
    monthly = {code: {m: months.get(m, 0.0) + (banca.get(code) or {}).get(m, 0.0)
                      for m in range(1, 13)}
               for code, months in pbt.items()}
    ytd = _running(monthly, latest)
    return {"year": year, "latest_month": latest, "ytd": ytd, "names": names,
            "loss_ytd": _running(loss, latest),
            "branches_without_banca": sorted(set(pbt) - set(banca))}


def save(found, file_name, loaded_by):
    """Keep the year's figures; a later file for the year replaces them."""
    from .models import BoWorkbookFile

    payload = {"year": found["year"], "latest_month": found["latest_month"],
               "ytd": {str(code): series for code, series in found["ytd"].items()},
               "loss_ytd": {str(code): series
                            for code, series in (found.get("loss_ytd") or {}).items()},
               "names": {str(code): name for code, name in found["names"].items()}}
    BoWorkbookFile.objects.update_or_create(
        kind=KIND.format(year=found["year"]),
        defaults={"payload": payload, "file_name": file_name, "loaded_by": loaded_by})


def stored(year):
    from .models import BoWorkbookFile

    row = BoWorkbookFile.objects.filter(kind=KIND.format(year=year)).first()
    return row.payload if row else None


def figures(year, month, exact=True, measure="ytd"):
    """→ (month read, {branch code: year to date}) or (None, {}).

    ``exact``: only that month (the proof compares a closed month). Otherwise
    the latest month Finance has closed at or before it - a card for November
    shows the year to October until November's accounts are loaded.
    ``measure``: "ytd" (PBT ex-HQ cost + bancassurance) or "loss_ytd" (loan
    loss, the Provisions sheet)."""
    data = stored(year)
    if not data or not data.get("latest_month"):
        return None, {}
    used = month if exact else min(month, int(data["latest_month"]))
    if used < 1 or used > int(data["latest_month"]):
        return None, {}
    return used, {int(code): series[used - 1]
                  for code, series in (data.get(measure) or {}).items()
                  if series[used - 1] is not None}
