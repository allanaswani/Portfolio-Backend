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
import math
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


def _sheet_password():
    """The password the download is locked with.

    ``SCORECARD_SHEET_PASSWORD`` when it is set, so whoever administers the
    cards can open one up. Otherwise one derived from the server's secret,
    which nobody has - a card nobody can unlock is the point.
    """
    import hashlib

    from django.conf import settings

    chosen = getattr(settings, "SCORECARD_SHEET_PASSWORD", "") or ""
    if chosen:
        return chosen
    return hashlib.sha256(
        f"scorecard-sheet:{settings.SECRET_KEY}".encode()).hexdigest()[:24]


def _line_format(line):
    """The number format the desk's card gives a line, read off its figures.

    Shillings in millions to one decimal ("88.7m", ".7m" - the desk's own
    ``#,###.0,,"m"``), rates as percentages ("100%", "60%"), and counts as
    whole numbers ("1,397", "36").
    """
    values = [abs(float(v)) for v in (
        line.get("prior_year"), line.get("annual_target"),
        line.get("ytd_target"), line.get("ytd_actual"))
        if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not values:
        return "#,##0"
    if max(values) >= 100_000:
        return '#,###.0,,"m"'
    if max(values) <= 1.5:
        small = [v for v in values if v and v < 0.1]
        return "0.0%" if small else "0%"
    if max(values) <= 10 and any(v != int(v) for v in values):
        return "0.00"          # a rating - the audit's 1.72 against < 1.65
    return "#,##0"


def build_card_workbook(card, signoff=None):
    """Render a card as an .xlsx workbook → ``BytesIO``.

    Laid out as the BANK's own scorecard is laid out, cell for cell, because
    this file is the one that goes to a reviewer and it has to be the document
    they already know. The grid is taken from the desk's own workbooks - the
    sheets in ``Portfolio Management - Q3 2026_scorecards.xlsb`` and the
    ``BM_Scorecard`` sheet of ``BB_Scorecards - Q3 2026_Scorecards.xlsb``:

        row 1   <year> <ROLE> OBJECTIVES, on the teal band
        row 2   Staff Name: | name | Title: | title | Performance Score: | ..
        row 3   BM Branch:  | brn  | Reports to: | manager | Performance Rating:
        row 4   Review Period | period | Report to Title: | .. | Comments:
        row 5   COUNT KPI "KPI Description" "Measure of Success" Weight
                "2025 FY" GROWTH "2026 FY" "YTD Target" ACTUAL "% SCORE"
                "Weighted Score"
        rows    one per line, grouped by perspective, the perspective named
                once in column B against the first of its lines
        then    the weight total in E and the score total in L, on the band
        then    the Reviewee and Reviewer signature rows

    And dressed as the desk dresses it: teal label cells with white bold
    text, dotted rules between the lines, figures in millions ("88.7m"),
    a KPI that spans two lines merged over both (VIC Premium), no
    gridlines. The branch manager's card hides COUNT and KPI, as
    ``BM_Scorecard`` does.

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

    #: The desk's own palette: the teal of its label cells and heading row,
    #: and the darker teal of its total band.
    teal, band, white = "FF2293A6", "FF0E5A6B", "FFFFFFFF"
    face = "Cambria"           # the desk's card is set in a serif face
    wb = Workbook()
    ws = wb.active
    ws.title = "Scorecard"
    ws.sheet_view.showGridLines = False

    rule = Side(style="dotted", color="FF404040")
    edge = Side(style="thin", color="FF404040")
    box = Border(left=edge, right=edge, top=rule, bottom=rule)
    under = Border(bottom=edge)
    fill = PatternFill("solid", fgColor=teal)
    dark = PatternFill("solid", fgColor=band)
    middle = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    staff = card.get("staff") or {}
    branch_card = card.get("workbook_card") == "branch_business"
    last = len(HEADERS)

    def fraction(value):
        """A weight or a score, kept as the fraction the bank's sheet holds.

        NOT ``_money``: that rounds to two decimals, which is right for
        shillings and turns a weighted score of 0.000945 into nought.
        """
        return None if value is None else round(float(value), 6)

    def at(row, column, value, align=None, **font):
        cell = ws.cell(row=row, column=column, value=value)
        cell.font = Font(name=face, size=font.pop("size", 10), **font)
        if align is not None:
            cell.alignment = align
        return cell

    def span(row, first, final, rows=1, border=None, paint=None):
        """Merge a block, and border/paint every cell of it - Excel draws a
        merged cell's border from the cells it covers, not the first one."""
        for r in range(row, row + rows):
            for c in range(first, final + 1):
                cell = ws.cell(row=r, column=c)
                if border is not None:
                    cell.border = border
                if paint is not None:
                    cell.fill = paint
        if rows > 1 or final > first:
            ws.merge_cells(start_row=row, start_column=first,
                           end_row=row + rows - 1, end_column=final)

    def label(row, column, text, final=None):
        at(row, column, text, left, bold=True, color=white)
        span(row, column, final or column, border=box, paint=fill)

    # ── the band and the mark ─────────────────────────────────────────────
    # The bank is HFCB. "HFC" is the old name and must not go out on a
    # document somebody puts their signature to.
    title = (staff.get("title") or "").upper()
    # The card's OWN year, not today's. A September 2026 card downloaded in
    # January would otherwise head itself 2027.
    period_text = str(((card.get("period") or {}).get("as_at") or ""))[:4]
    year = int(period_text) if period_text.isdigit() else \
        datetime.date.today().year
    heading = f"{year} {title} OBJECTIVES - HFCB"
    at(1, 1, heading, left, bold=True, size=12, color=white)
    if branch_card:
        # Columns A and B are hidden on the branch card, so the band's text
        # sits in C, the first column a branch manager sees.
        span(1, 1, 2, paint=dark)
        at(1, 3, heading, left, bold=True, size=12, color=white)
        span(1, 3, 10, paint=dark)
    else:
        span(1, 1, 10, paint=dark)
    ws.row_dimensions[1].height = 40

    # Every scorecard sheet in the desk's workbook carries the mark top right,
    # over the score. Guarded by exists(): a missing asset must never turn a
    # download into a 500.
    import pathlib

    from openpyxl.drawing.image import Image as SheetImage

    mark = pathlib.Path(__file__).parent / "assets" / "hfcb-logo.png"
    if mark.exists():
        try:
            logo = SheetImage(str(mark))
            logo.width, logo.height = 110, 48
            ws.add_image(logo, "K1")
        except Exception:  # noqa: BLE001 - see above; the card still goes out
            pass

    # ── the header block ──────────────────────────────────────────────────
    period = (card.get("period") or {}).get("label") or ""
    as_at = str((card.get("period") or {}).get("as_at") or "")
    if branch_card and len(as_at) >= 7 and as_at[5:7].isdigit():
        # BM_Scorecard heads its period the way Constants names it: Q3_Sep_26.
        month = datetime.date(int(as_at[:4]), int(as_at[5:7]), 1)
        period = f"Q{(month.month - 1) // 3 + 1}_{month:%b}_{month:%y}"

    for row, (name_label, value, side_label, side_value, score_label) in \
            enumerate((
                ("Staff Name:", staff.get("name") or "", "Title:",
                 staff.get("title") or "", "Performance Score:"),
                ("BM Branch:", staff.get("branch") or "", "Reports to:",
                 staff.get("team_leader") or "", "Performance Rating:"),
                ("Review Period", period, "Report to Title:",
                 staff.get("report_to_title") or "", "Comments:"),
            ), start=2):
        label(row, 1, name_label, 2)
        at(row, 3, value, left, bold=True)
        span(row, 3, 3, border=box)
        label(row, 4, side_label)
        at(row, 5, side_value, left, bold=True)
        span(row, 5, 6, border=box)
        label(row, 7, score_label, 10)
        ws.row_dimensions[row].height = 17

    score_cell = at(2, 11, fraction(card.get("performance_score") or 0),
                    middle, bold=True, size=16)
    score_cell.number_format = "0.0%"
    span(2, 11, 12, rows=3, border=Border(left=edge, right=edge, top=edge,
                                          bottom=edge))

    # ── the column headings ───────────────────────────────────────────────
    for column, header in enumerate(HEADERS, start=1):
        cell = at(5, column, header, middle, bold=True, color=white)
        cell.fill = fill
        cell.border = Border(left=edge, right=edge, top=edge, bottom=edge)
    ws.row_dimensions[5].height = 30

    def close_kpi(first, final):
        """Merge a KPI's run of lines into one cell, once the run is over -
        merging line by line would lay overlapping ranges, which Excel
        reports as a damaged file."""
        if final > first:
            ws.merge_cells(start_row=first, start_column=3, end_row=final,
                           end_column=3)

    row = 6
    group_number = 0
    for group in card.get("perspectives") or []:
        group_number += 1
        group_start = row
        kpi_start = row
        for line in group.get("lines") or []:
            pending = line.get("pending")
            # A line settled by rule rather than measured has no figure, and
            # the ACTUAL column must say so rather than sit empty beside a
            # 100% score. CX mark some RMs "give full marks" because the
            # survey measure does not apply to them.
            by_rule = (not pending and line.get("full_marks_rule")
                       and line.get("ytd_actual") is None)
            shape = _line_format(line)

            if row == group_start:
                # The perspective is named once, against its first line, and
                # carries its own weight - "Financials (20.0%)" - which is
                # how ``mapping_category`` already reads.
                at(row, 1, group_number, middle)
                at(row, 2, group.get("perspective") or "", left, bold=True)

            # A KPI over two lines - VIC Premium, life and non-life - is one
            # merged cell on the desk's card.
            if not (line.get("continues_kpi") and row > group_start):
                close_kpi(kpi_start, row - 1)
                kpi_start = row
                at(row, 3, line.get("kpi_name") or "", left)
            at(row, 4, line.get("measure_of_success") or "", left)

            weight = at(row, 5, fraction(line.get("weight")), middle)
            weight.number_format = "0.0%"

            prior = _money(line.get("prior_year"))
            annual = _money(line.get("annual_target"))
            at(row, 6, prior, middle).number_format = shape
            # GROWTH is what the year's target adds to the prior year, which
            # is how the bank's sheet reads it: F + G = H. With no prior year
            # the whole target is the growth, and the printed card shows it
            # that way too.
            at(row, 7, None if annual is None
               else round(annual - (prior or 0), 2), middle
               ).number_format = shape
            ytd = _money(line.get("ytd_target"))
            text_target = line.get("target_text") or ""
            # A target the desk writes as words - "< 1.65" for the audit
            # rating - prints as written.
            at(row, 8, annual if annual is not None else
               (text_target or None), middle).number_format = shape
            at(row, 9, ytd if ytd is not None else
               (text_target or None), middle).number_format = shape

            # A pending line prints WHY, not a zero. A zero in this column
            # reads as "achieved nothing", which is a different statement
            # from "nobody has this figure".
            actual = at(row, 10, pending if pending else (
                "Full marks by rule - this measure does not apply"
                if by_rule else _money(line.get("ytd_actual"))),
                Alignment(wrap_text=True, vertical="center",
                          horizontal="left" if pending or by_rule
                          else "center"),
                size=8 if pending or by_rule else 10)
            actual.number_format = shape

            if not pending:
                for column, value in ((11, line.get("score")),
                                      (12, line.get("weighted_score"))):
                    cell = at(row, column, fraction(value), middle)
                    cell.number_format = "0.0%"

            for column in range(1, last + 1):
                ws.cell(row=row, column=column).border = box
            # Tall enough for the wrapped text: the desk's long measures
            # ("Grow by 40% of Disbusement Target of the Dec book Balance")
            # run to two lines.
            wraps = max(
                math.ceil(len(str(line.get("measure_of_success") or "")) / 44),
                math.ceil(len(str(line.get("kpi_name") or "")) / 32),
                3 if pending else 1)
            ws.row_dimensions[row].height = max(18, 14 * wraps + 4)
            row += 1

        close_kpi(kpi_start, row - 1)
        if row - group_start > 1:
            for column in (1, 2):
                ws.merge_cells(start_row=group_start, start_column=column,
                               end_row=row - 1, end_column=column)

    # ── the totals ────────────────────────────────────────────────────────
    total_row = row
    for column in range(1, last + 1):
        cell = ws.cell(row=total_row, column=column)
        cell.fill = dark
        cell.border = Border(top=edge, bottom=edge)
    at(total_row, 2, "TOTAL PERFORMANCE SCORE", left, bold=True, color=white)
    ws.merge_cells(start_row=total_row, start_column=2, end_row=total_row,
                   end_column=4)
    weights = at(total_row, 5, fraction(sum(
        float(line.get("weight") or 0)
        for group in card.get("perspectives") or []
        for line in group.get("lines") or [])), middle, bold=True,
        color=white)
    weights.number_format = "0.0%"
    total = at(total_row, 12, fraction(card.get("performance_score") or 0),
               middle, bold=True, color=white)
    total.number_format = "0.0%"
    ws.row_dimensions[total_row].height = 20
    row = total_row

    # What the total was out of. A line with no source scores nothing and is
    # summed as nothing, so a card carrying three of them totals against a
    # weight that was never fully on offer. The score itself is NOT
    # rescaled; this states the shortfall instead, below the total, and only
    # when there is one.
    unscored = float(card.get("unscored_weight") or 0)
    if unscored:
        row += 1
        scored = float(card.get("scored_weight") or 0)
        at(row, 3,
           f"Scored on {fraction(scored):.1%} of weight; "
           f"{fraction(unscored):.1%} has no source and is not "
           f"included. Administration enters those under "
           f"Scorecards → Figures to load.", left, italic=True, size=9)
        ws.merge_cells(start_row=row, start_column=3, end_row=row,
                       end_column=last)

    # ── the signature rows ────────────────────────────────────────────────
    # Same two rows, same wording and same column positions as the printed
    # card, so a reviewer signs where they expect to sign: the name on a
    # rule, a teal "Sign and date" box, the date on a rule, a teal
    # "Comments:" box, the comment on a rule.
    row += 2
    for who, name, when, comment in (
        ("Reviewee", getattr(signoff, "signed_by_name", "") or "",
         getattr(signoff, "signed_at", None),
         getattr(signoff, "owner_comment", "") or ""),
        ("Reviewer", getattr(signoff, "manager_signed_by_name", "") or "",
         getattr(signoff, "manager_signed_at", None),
         getattr(signoff, "manager_comment", "") or ""),
    ):
        at(row, 1, f"{who} Name:", left, bold=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row,
                       end_column=2)
        at(row, 3, name, left).border = under
        label(row, 4, f"{who} Sign and date", 5)
        at(row, 6, when.strftime("%d %b %Y %H:%M") if when else None,
           middle)
        span(row, 6, 7, border=under)
        label(row, 8, "Comments:", 9)
        at(row, 10, comment or None, left)
        span(row, 10, last, border=under)
        ws.row_dimensions[row].height = 22
        row += 2

    if not signoff or not getattr(signoff, "signed_at", None):
        at(row, 3 if branch_card else 1,
           "This copy is unsigned and was taken from the live figures on "
           f"{datetime.date.today():%d %b %Y}. The figures move; sign the "
           "card in the portal to fix them.",
           italic=True, color="FF8A6A2A", size=9)

    #: A, B … L, to the bank's own proportions.
    widths = (7, 22, 30, 38, 8, 12, 12, 14, 13, 16, 11, 14)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    if branch_card:
        # BM_Scorecard keeps COUNT and KPI out of sight; its KPI Description
        # column is the first a branch manager reads.
        for column in ("A", "B"):
            ws.column_dimensions[column].hidden = True
    ws.freeze_panes = "A6"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    # ── read-only ─────────────────────────────────────────────────────────
    # A scorecard is a record, and a signed one is a record somebody has put
    # their name to. Left editable, the first thing that happens to a
    # downloaded card is that a figure gets changed in it and the file is
    # forwarded, and nothing then distinguishes that copy from the one that
    # was signed.
    #
    # Excel's own sheet protection, WITH a password. Without one, Review →
    # Unprotect Sheet is a single click and the protection stopped nobody;
    # the business asked that the download not be editable. The password is
    # the server's (see ``_sheet_password``), so the person holding the file
    # cannot lift it. Selecting and copying stay on: people need to read the
    # thing.
    secret = _sheet_password()
    ws.protection.sheet = True
    ws.protection.password = secret
    for allowed in ("formatCells", "formatColumns", "formatRows",
                    "insertColumns", "insertRows", "insertHyperlinks",
                    "deleteColumns", "deleteRows", "sort", "autoFilter",
                    "pivotTables", "objects", "scenarios"):
        setattr(ws.protection, allowed, True)
    ws.protection.selectLockedCells = False
    ws.protection.selectUnlockedCells = False
    # Stops the sheet being renamed, moved, deleted or copied out around the
    # protection.
    wb.security = WorkbookProtection(lockStructure=True)
    wb.security.workbookPassword = secret

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
