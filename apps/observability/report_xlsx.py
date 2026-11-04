"""The bank's report workbook: an Excel attachment with one table per sheet.

The same look as the data team's reports (branch_summary_report.py and its
family): a teal tab, "Table Style Medium 9" with filter buttons, the header row
frozen. Reports here mail a short note and put the figures in this attachment,
because a table somebody can sort, filter and forward is what the reader wants.
"""

import datetime
import io

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TAB_COLOUR = "2AAFB8"
TABLE_STYLE = "TableStyleMedium9"
MAX_WIDTH = 48


def _cell_value(value):
    """Excel has no time zones; everything else goes in as it is."""
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        from django.utils import timezone

        return timezone.localtime(value).replace(tzinfo=None)
    return value


def _number_format(value, header):
    if isinstance(value, datetime.datetime):
        return "dd-mmm-yyyy hh:mm"
    if isinstance(value, datetime.date):
        return "dd-mmm-yyyy"
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and "%" in header:
        return "0.0%"
    if isinstance(value, (int, float)):
        return "#,##0" if float(value).is_integer() else "#,##0.00"
    return None


def build(sheets):
    """[{"title", "headers", "rows", "note"?, "empty"?}] → the workbook's bytes.

    An empty sheet still appears with its headers and says so: a sheet that
    vanishes on a quiet day reads as a broken report.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)
    for number, sheet in enumerate(sheets, 1):
        ws = workbook.create_sheet(sheet["title"][:31])
        ws.sheet_properties.tabColor = TAB_COLOUR
        ws.sheet_view.zoomScale = 90
        row = 1
        if sheet.get("note"):
            ws.cell(row=1, column=1, value=sheet["note"]).font = Font(italic=True)
            row = 3
        headers = list(sheet["headers"])
        header_row = row
        for col, header in enumerate(headers, 1):
            ws.cell(row=row, column=col, value=header)
        rows = list(sheet["rows"])
        widths = [len(str(h)) + 4 for h in headers]
        for values in rows:
            row += 1
            for col, value in enumerate(values, 1):
                value = _cell_value(value)
                cell = ws.cell(row=row, column=col, value=value)
                fmt = _number_format(value, headers[col - 1])
                if fmt:
                    cell.number_format = fmt
                shown = 18 if fmt and "yyyy" in fmt else len(str(value or ""))
                widths[col - 1] = max(widths[col - 1], shown + 2)
        if rows:
            ref = f"A{header_row}:{get_column_letter(len(headers))}{row}"
            table = Table(displayName=f"Sheet{number}Table", ref=ref)
            table.tableStyleInfo = TableStyleInfo(name=TABLE_STYLE,
                                                  showRowStripes=True)
            ws.add_table(table)
        else:
            ws.cell(row=header_row + 1, column=1,
                    value=sheet.get("empty", "Nothing to show."))
        for col, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = min(width,
                                                                     MAX_WIDTH)
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()
