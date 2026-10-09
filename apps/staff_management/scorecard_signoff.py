"""Signing a scorecard, and downloading the copy that was signed.

Why a copy
──────────
The live card is computed from feeds that move every night. A signature on it
would attest to a document that reads differently an hour later, and the point
of the signature is that both sides agree on what the figures WERE. So signing
freezes the card into ``sc_scorecard_signoffs``, and both the download and
every later view of that month render from the frozen copy.

The workbook
────────────
The desk sends these as a spreadsheet, so the download is a spreadsheet, laid
out the way the card is laid out: the header block, then each perspective with
its lines and the same six columns, then the total, then the signature block.
A pending line prints its reason in the ACTUAL column rather than a zero, for
the same reason the screen does.
"""

from __future__ import annotations

import datetime
from io import BytesIO

HEADERS = ["#", "KPI", "Measure of success", "Weight", "YTD target",
           "YTD actual", "As at", "Score", "Weighted"]


def _money(value):
    """Shillings with no decimals, counts as given. openpyxl writes the number
    and Excel formats it, so the file stays a spreadsheet people can work in
    rather than a page of strings."""
    if value is None:
        return None
    return round(float(value), 2)


def build_card_workbook(card, signoff=None):
    """Render a card as an .xlsx workbook → ``BytesIO``.

    ``card`` is the card dict — live, or the frozen copy off a sign-off.
    ``signoff`` fills the signature block when the card has been signed.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    teal = "FF0B5C6B"          # HF teal, the brand colour used on the screens
    wb = Workbook()
    ws = wb.active
    ws.title = "Scorecard"

    thin = Side(style="thin", color="FFD6E4E8")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    staff = card.get("staff") or {}

    row = 1

    def put(label, value, bold_label=True):
        nonlocal row
        ws.cell(row=row, column=1, value=label).font = Font(bold=bold_label)
        ws.cell(row=row, column=2, value=value)
        row += 1

    ws.cell(row=row, column=1, value="HFC PERFORMANCE SCORECARD").font = Font(
        bold=True, size=14, color=teal)
    row += 2

    put("Name", staff.get("name") or "")
    put("Sales code", staff.get("sales_code") or "")
    put("Role", staff.get("title") or "")
    put("Branch", staff.get("branch") or "")
    put("Line manager", staff.get("team_leader") or "")
    put("Period", (card.get("period") or {}).get("label") or "")
    put("Performance score", _money((card.get("performance_score") or 0) * 100))
    ws.cell(row=row - 1, column=3, value="%")
    put("Lines scored",
        f"{card.get('scored_lines', 0)} of "
        f"{card.get('scored_lines', 0) + card.get('pending_lines', 0)}")
    put("Targets from", card.get("target_source") or "")
    row += 1

    for group in card.get("perspectives") or []:
        cell = ws.cell(row=row, column=1,
                       value=f"{group.get('perspective', '')}  "
                             f"({_money((group.get('weight') or 0) * 100)}%)")
        cell.font = Font(bold=True, color="FFFFFFFF")
        for column in range(1, len(HEADERS) + 1):
            ws.cell(row=row, column=column).fill = PatternFill(
                "solid", fgColor=teal)
        row += 1

        for index, header in enumerate(HEADERS, start=1):
            head = ws.cell(row=row, column=index, value=header)
            head.font = Font(bold=True)
            head.border = box
            head.fill = PatternFill("solid", fgColor="FFF3F8F9")
        row += 1

        for line in group.get("lines") or []:
            pending = line.get("pending")
            values = [
                line.get("kpi_order"),
                line.get("kpi_name") or "",
                line.get("measure_of_success") or "",
                _money((line.get("weight") or 0) * 100),
                _money(line.get("ytd_target")),
                # A pending line prints WHY, not a zero. A zero in this column
                # reads as "achieved nothing", which is a different statement
                # from "nobody has this figure".
                pending if pending else _money(line.get("ytd_actual")),
                line.get("as_at") or "",
                None if pending else _money((line.get("score") or 0) * 100),
                None if pending else _money(
                    (line.get("weighted_score") or 0) * 100),
            ]
            for index, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=index, value=value)
                cell.border = box
                if index in (2, 3, 6) and pending:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
            row += 1
        row += 1

    total = ws.cell(row=row, column=2, value="TOTAL PERFORMANCE SCORE")
    total.font = Font(bold=True)
    score = ws.cell(row=row, column=9,
                    value=_money((card.get("performance_score") or 0) * 100))
    score.font = Font(bold=True)
    row += 3

    # ── Signatures ────────────────────────────────────────────────────────
    ws.cell(row=row, column=1, value="SIGN-OFF").font = Font(bold=True,
                                                             color=teal)
    row += 1
    for who, name, when, comment in (
        ("Staff member", getattr(signoff, "signed_by_name", "") or "",
         getattr(signoff, "signed_at", None),
         getattr(signoff, "owner_comment", "") or ""),
        ("Line manager", getattr(signoff, "manager_signed_by_name", "") or "",
         getattr(signoff, "manager_signed_at", None),
         getattr(signoff, "manager_comment", "") or ""),
    ):
        ws.cell(row=row, column=1, value=who).font = Font(bold=True)
        ws.cell(row=row, column=2, value=name or "………………………………")
        ws.cell(row=row, column=3, value=(
            when.strftime("%d %b %Y %H:%M") if when else "Date: ……………………"))
        ws.cell(row=row, column=4, value=comment)
        row += 2

    if not signoff or not getattr(signoff, "signed_at", None):
        note = ws.cell(row=row, column=1, value=(
            "This copy is unsigned and was taken from the live figures on "
            f"{datetime.date.today():%d %b %Y}. The figures move; sign the "
            "card in the portal to fix them."))
        note.font = Font(italic=True, color="FF8A6A2A")

    widths = (5, 44, 40, 9, 16, 30, 20, 9, 10)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def period_for(card=None, today=None):
    """``YYYY-MM`` for the month a card is signed for.

    The month that has CLOSED, not the one in progress: a card signed on the
    9th of October is the September card, which is the month the figures on it
    are year-to-date to.
    """
    today = today or datetime.date.today()
    first = today.replace(day=1)
    closed = first - datetime.timedelta(days=1)
    return f"{closed.year:04d}-{closed.month:02d}"
