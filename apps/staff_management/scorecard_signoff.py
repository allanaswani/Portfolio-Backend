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

#: The bank's own twelve columns, in the bank's own order and wording. Taken
#: from the desk's scorecard workbook, which is the document a reviewer knows.
HEADERS = ["COUNT", "KPI", "KPI Description", "Measure of Success", "Weight",
           "2025 FY", "GROWTH", "2026 FY", "YTD Target", "ACTUAL", "% SCORE",
           "Weighted Score"]


def _money(value):
    """Shillings with no decimals, counts as given. openpyxl writes the number
    and Excel formats it, so the file stays a spreadsheet people can work in
    rather than a page of strings."""
    if value is None:
        return None
    return round(float(value), 2)


def build_card_workbook(card, signoff=None):
    """Render a card as an .xlsx workbook → ``BytesIO``.

    Laid out as the BANK's own scorecard is laid out, cell for cell, because
    this file is the one that goes to a reviewer and it has to be the document
    they already know. The grid is taken from the desk's own workbook - the
    sheets in ``Portfolio Management - Q3 2026_scorecards.xlsb``:

        row 1   <year> <ROLE> OBJECTIVES
        row 2   Staff Name: | name | Title: | title | Performance Score: | ..
        row 3   BM Branch:  | brn  | Reports to: | manager | Performance Rating:
        row 4   Review Period | period | Report to Title: | .. | Comments:
        row 5   COUNT KPI "KPI Description" "Measure of Success" Weight
                "2025 FY" GROWTH "2026 FY" "YTD Target" ACTUAL "% SCORE"
                "Weighted Score"
        rows    one per line, grouped by perspective, the perspective named
                once in column B against the first of its lines
        then    the weight total in E and the score total in L
        then    the Reviewee and Reviewer signature rows

    Weights and scores are written as FRACTIONS, as they are on the bank's
    sheet - 0.05, not 5% - and the cells carry a percent number format so
    Excel shows them the way the original does. The figures stay numbers, so
    the reviewer can still check the arithmetic.

    ``card`` is the card dict - live, or the frozen copy off a sign-off.
    ``signoff`` fills the signature rows when the card has been signed.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.protection import WorkbookProtection

    teal = "FF0B5C6B"          # HF teal, the brand colour used on the screens
    wb = Workbook()
    ws = wb.active
    ws.title = "Scorecard"

    thin = Side(style="thin", color="FFBFD4DA")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    staff = card.get("staff") or {}
    bold = Font(bold=True)

    # ── the mark ──────────────────────────────────────────────────────────
    #
    # Every scorecard sheet in the desk's own workbook carries a cell reading
    # "HFCB Logo" in row 2, where the image sits. This file goes to a reviewer
    # and gets signed, and it was going out with no mark on it at all - no
    # images, no drawings, nothing.
    #
    # Anchored at H1, which is clear: the header block writes to columns 1, 3,
    # 4, 5, 7 and 11, so H to J are empty in the rows it spans. Scaled to a
    # tenth of the source (1300x575) so it reads as a letterhead rather than
    # covering the card.
    #
    # Guarded by exists(): a missing asset must never turn a download into a
    # 500. A card with no logo is a card somebody can still sign.
    import pathlib

    from openpyxl.drawing.image import Image as SheetImage

    mark = pathlib.Path(__file__).parent / "assets" / "hfcb-logo.png"
    if mark.exists():
        try:
            logo = SheetImage(str(mark))
            logo.width, logo.height = 132, 58
            ws.add_image(logo, "H1")
            ws.row_dimensions[1].height = 34
        except Exception:  # noqa: BLE001 - see above; the card still goes out
            pass

    def fraction(value):
        """A weight or a score, kept as the fraction the bank's sheet holds.

        NOT ``_money``: that rounds to two decimals, which is right for
        shillings and turns a weighted score of 0.000945 into nought.
        """
        return None if value is None else round(float(value), 6)

    def at(row, column, value, **font):
        cell = ws.cell(row=row, column=column, value=value)
        if font:
            cell.font = Font(**font)
        return cell

    # ── the header block ──────────────────────────────────────────────────
    # The bank is HFCB. "HFC" is the old name and must not go out on a
    # document somebody puts their signature to.
    title = (staff.get("title") or "").upper()
    # The card's OWN year, not today's. A September 2026 card downloaded in
    # January would otherwise head itself 2027 - the same fault as the period
    # label, which took whatever date happened to be to hand.
    period_text = str(((card.get("period") or {}).get("as_at") or ""))[:4]
    year = int(period_text) if period_text.isdigit() else \
        datetime.date.today().year
    at(1, 1, f"{year} {title} OBJECTIVES - HFCB",
       bold=True, size=13, color=teal)

    at(2, 1, "Staff Name:", bold=True)
    at(2, 3, staff.get("name") or "")
    at(2, 4, "Title:", bold=True)
    at(2, 5, staff.get("title") or "")
    at(2, 7, "Performance Score:", bold=True)
    score_cell = at(2, 11, fraction(card.get("performance_score") or 0),
                    bold=True)
    score_cell.number_format = "0.0%"

    at(3, 1, "BM Branch:", bold=True)
    at(3, 3, staff.get("branch") or "")
    at(3, 4, "Reports to:", bold=True)
    at(3, 5, staff.get("team_leader") or "")
    at(3, 7, "Performance Rating:", bold=True)

    at(4, 1, "Review Period", bold=True)
    at(4, 3, (card.get("period") or {}).get("label") or "")
    at(4, 4, "Report to Title:", bold=True)
    at(4, 7, "Comments:", bold=True)

    # ── the column headings ───────────────────────────────────────────────
    for column, header in enumerate(HEADERS, start=1):
        cell = at(5, column, header, bold=True, color="FFFFFFFF")
        cell.fill = PatternFill("solid", fgColor=teal)
        cell.border = box
        cell.alignment = Alignment(wrap_text=True, vertical="center",
                                   horizontal="center")

    row = 6
    group_number = 0
    for group in card.get("perspectives") or []:
        group_number += 1
        first = True
        for line in group.get("lines") or []:
            pending = line.get("pending")
            # A line settled by rule rather than measured has no figure, and
            # the ACTUAL column must say so rather than sit empty beside a
            # 100% score. CX mark some RMs "give full marks" because the
            # survey measure does not apply to them.
            by_rule = (not pending and line.get("full_marks_rule")
                       and line.get("ytd_actual") is None)

            if first:
                # The perspective is named once, against its first line, and
                # carries its own weight - "Financials (20.0%)" - which is
                # how ``mapping_category`` already reads.
                at(row, 1, group_number).alignment = Alignment(
                    horizontal="center")
                at(row, 2, group.get("perspective") or "", bold=True)
                first = False

            at(row, 3, line.get("kpi_name") or "")
            at(row, 4, line.get("measure_of_success") or "")

            weight = at(row, 5, fraction(line.get("weight")))
            weight.number_format = "0.0%"

            prior = _money(line.get("prior_year"))
            annual = _money(line.get("annual_target"))
            at(row, 6, prior)
            # GROWTH is what the year's target adds to the prior year, which
            # is how the bank's sheet reads it: F + G = H. With no prior year
            # the whole target is the growth, and the printed card shows it
            # that way too.
            at(row, 7, None if annual is None
               else round(annual - (prior or 0), 2))
            at(row, 8, annual)
            at(row, 9, _money(line.get("ytd_target")))

            # A pending line prints WHY, not a zero. A zero in this column
            # reads as "achieved nothing", which is a different statement
            # from "nobody has this figure".
            actual = at(row, 10, pending if pending else (
                "Full marks by rule - this measure does not apply"
                if by_rule else _money(line.get("ytd_actual"))))
            if pending or by_rule:
                actual.alignment = Alignment(wrap_text=True, vertical="top")

            if not pending:
                for column, value in ((11, line.get("score")),
                                      (12, line.get("weighted_score"))):
                    cell = at(row, column, fraction(value))
                    cell.number_format = "0.0%"

            for column in range(1, len(HEADERS) + 1):
                ws.cell(row=row, column=column).border = box
            row += 1

    # ── the totals ────────────────────────────────────────────────────────
    row += 1
    weights = at(row, 5, fraction(sum(
        float(line.get("weight") or 0)
        for group in card.get("perspectives") or []
        for line in group.get("lines") or [])), bold=True)
    weights.number_format = "0.0%"
    at(row, 2, "TOTAL PERFORMANCE SCORE", bold=True)
    total = at(row, 12, fraction(card.get("performance_score") or 0),
               bold=True)
    total.number_format = "0.0%"

    # What the total was out of. A line with no source scores nothing and is
    # summed as nothing, so a card carrying three of them totals against a
    # weight that was never fully on offer: Abed Lelgo's Commercial RM card
    # shows 102.5% of weight while 12.5% of it - banking covenant tracking,
    # tooling and account planning, leave management - has nowhere to read an
    # actual from. Printed as 65.66% with nothing beside it, that reads as
    # though he failed those three.
    #
    # The score itself is NOT rescaled. Rescaling would hand him the average
    # of the lines that did score, which is a figure nobody measured and
    # worse than the problem. This states the shortfall instead, on the row
    # below the total, and only when there is one.
    unscored = float(card.get("unscored_weight") or 0)
    if unscored:
        row += 1
        scored = float(card.get("scored_weight") or 0)
        note = at(row, 2,
                  f"Scored on {fraction(scored):.1%} of weight; "
                  f"{fraction(unscored):.1%} has no source and is not "
                  f"included. Administration enters those under "
                  f"Scorecards → Figures to load.")
        note.alignment = Alignment(wrap_text=True, vertical="top")

    # ── the signature rows ────────────────────────────────────────────────
    # Same two rows, same wording and same column positions as the printed
    # card, so a reviewer signs where they expect to sign.
    row += 2
    for who, name, when, comment in (
        ("Reviewee", getattr(signoff, "signed_by_name", "") or "",
         getattr(signoff, "signed_at", None),
         getattr(signoff, "owner_comment", "") or ""),
        ("Reviewer", getattr(signoff, "manager_signed_by_name", "") or "",
         getattr(signoff, "manager_signed_at", None),
         getattr(signoff, "manager_comment", "") or ""),
    ):
        at(row, 1, f"{who} Name:", bold=True)
        at(row, 3, name or "_" * 33)
        at(row, 4, f"{who} Sign and date", bold=True)
        at(row, 6, when.strftime("%d %b %Y %H:%M") if when else "_" * 21)
        at(row, 8, "Comments:", bold=True)
        at(row, 10, comment or "_" * 31)
        row += 2

    if not signoff or not getattr(signoff, "signed_at", None):
        at(row, 1,
           "This copy is unsigned and was taken from the live figures on "
           f"{datetime.date.today():%d %b %Y}. The figures move; sign the "
           "card in the portal to fix them.",
           italic=True, color="FF8A6A2A")

    #: A, B … L, to the bank's own proportions.
    widths = (7, 26, 34, 34, 8, 16, 16, 16, 16, 30, 10, 12)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A6"

    # ── read-only ─────────────────────────────────────────────────────────
    # A scorecard is a record, and a signed one is a record somebody has put
    # their name to. Left editable, the first thing that happens to a
    # downloaded card is that a figure gets changed in it and the file is
    # forwarded, and nothing then distinguishes that copy from the one that
    # was signed.
    #
    # This is Excel's own sheet protection. It is a deterrent, not encryption -
    # a determined person can strip it - and it carries no password, because a
    # password nobody wrote down is a support call. What it does is stop the
    # accident, which is the thing that actually happens, and make an
    # alteration deliberate instead of casual.
    ws.protection.sheet = True
    ws.protection.enable()
    for allowed in ("formatCells", "formatColumns", "formatRows",
                    "insertColumns", "insertRows", "insertHyperlinks",
                    "deleteColumns", "deleteRows", "sort", "autoFilter",
                    "pivotTables"):
        setattr(ws.protection, allowed, False)
    # Selecting and copying stay on: people need to read the thing, and
    # locking selection only makes it annoying without making it safer.
    ws.protection.selectLockedCells = False
    ws.protection.selectUnlockedCells = False
    # Stops the sheet being renamed, moved or deleted around the protection.
    wb.security = WorkbookProtection(lockStructure=True)

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
