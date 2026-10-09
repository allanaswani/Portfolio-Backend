"""Reading the RM actuals workbook into ``sc_employee_performance_actual_values``.

The workbook is ``2026_Actual_Template.xlsx`` — 65 sheets, one per KPI. Every
sheet is built from one repeating block::

    Staff PF-Number | Staff Sales Code | Staff - Name | Role | Branch | Zone | Jan | ... | Dec

Three things about it are not guessable from the headers, and each was
established by reproducing a figure a scorecard already states rather than by
reading the layout:

**A month column holds a YTD cumulative value, not that month's amount.**
One RM's VIC premium column runs Jun 2,076,983 / Jul 2,076,983 / Aug 2,076,987
and his Q3_Aug_26 card states 2,076,987. Summing Jan–Aug gives 9,601,603, which
is 4.6x too high. So the ACTUAL for a review month is that month's cell, as-is.

**A sheet can be several blocks wide, and a card picks one.**
``Banca_Assurance_Income`` is 118 columns: six repeats of the layout above at
1-18, 21-38, 41-58, 61-78, 81-98 and 101-118, unlabelled, and composites of each
other — at August, block 4 = block 2 + block 3 and block 6 = block 4 + block 5.
The Commercial card's VIC line is block 4. Block 1 would have read 2,410.

**Some lines negate what the sheet stores.** ``PL_Charge`` holds a loan loss
positive; every card that uses it shows it negative.

Which sheet, which block and whether to negate are therefore properties of the
KPI (``ScKpi.actuals_sheet`` / ``actuals_block`` / ``negate``), not of the
reader. A KPI whose block was never established carries
``not_configured_reason`` and is skipped — reading block 1 by default would put
Banca premiums 860x out, and a wrong figure on a scorecard is worse than an
absent one.

The month is matched on the header DATE, not on position, so a sheet that
starts at a different month still reads correctly.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

#: Columns 7..18 of a block are the twelve months.
MONTHS_PER_BLOCK = 12
#: A block is six identity columns then the months.
IDENTITY_COLUMNS = 6
BLOCK_WIDTH = IDENTITY_COLUMNS + MONTHS_PER_BLOCK

#: The cell that marks the start of a block.
BLOCK_MARKER = "staff pf-number"
#: The cell holding the key every scorecard is keyed on.
CODE_MARKER = "staff sales code"


@dataclass
class ActualRow:
    sales_code: str
    kpi_code: str
    value: float
    sheet: str
    block: int


@dataclass
class ReadResult:
    rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    #: KPIs that were configured but whose sheet/column was not found.
    unreadable: list = field(default_factory=list)
    #: KPIs deliberately skipped, with the reason recorded on the definition.
    skipped: list = field(default_factory=list)
    sheets_seen: int = 0
    people: int = 0

    @property
    def total(self):
        return len(self.rows)


def _text(value):
    return "" if value is None else " ".join(str(value).split())


def _blocks(header):
    """The 0-based start column of every block on this sheet.

    A sheet with no marker at all is treated as a single block starting at
    column 0, which is what the narrow sheets look like when the header has
    been re-typed.
    """
    starts = [i for i, c in enumerate(header)
              if _text(c).lower() == BLOCK_MARKER]
    return starts or [0]


def _month_column(header, start, month):
    """The column index holding ``month`` within the block at ``start``.

    Matched on the header's own date so a sheet that is short a month, or
    starts somewhere other than January, still reads correctly. Falls back to
    counting from the start of the block when the headers are not dates.
    """
    for i in range(start + IDENTITY_COLUMNS, min(start + BLOCK_WIDTH, len(header))):
        cell = header[i]
        if isinstance(cell, _dt.datetime) or isinstance(cell, _dt.date):
            if cell.year == month.year and cell.month == month.month:
                return i
    index = start + IDENTITY_COLUMNS + (month.month - 1)
    return index if index < len(header) else None


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def read_actuals(source, eom_date, definitions):
    """Read one review month out of the workbook.

    ``definitions`` are the ``ScKpi`` rows to look for — passed in rather than
    queried here so the parser stays testable without a database, and so the
    caller decides whether inactive KPIs are included.

    ``eom_date`` is any date in the review month; the day is ignored.
    """
    import openpyxl

    month = eom_date.replace(day=1)
    workbook = openpyxl.load_workbook(source, data_only=True, read_only=True)
    by_lower = {name.lower(): name for name in workbook.sheetnames}

    result = ReadResult()
    wanted = {}
    for kpi in definitions:
        if kpi.not_configured_reason:
            result.skipped.append(
                f"{kpi.kpi_code}: {kpi.not_configured_reason}")
            continue
        if not kpi.actuals_sheet:
            result.skipped.append(
                f"{kpi.kpi_code}: no actuals sheet on the KPI definition.")
            continue
        wanted.setdefault(kpi.actuals_sheet.lower(), []).append(kpi)

    seen_codes = set()

    for sheet_lower, kpis in sorted(wanted.items()):
        real = by_lower.get(sheet_lower)
        if real is None:
            for kpi in kpis:
                result.unreadable.append(
                    f"{kpi.kpi_code}: sheet {kpi.actuals_sheet!r} is not in "
                    f"this workbook.")
            continue

        rows = list(workbook[real].iter_rows(values_only=True))
        if not rows:
            for kpi in kpis:
                result.unreadable.append(f"{kpi.kpi_code}: {real} is empty.")
            continue

        result.sheets_seen += 1
        header = list(rows[0])
        starts = _blocks(header)

        for kpi in kpis:
            block = kpi.actuals_block or 1
            if block > len(starts):
                result.unreadable.append(
                    f"{kpi.kpi_code}: {real} has {len(starts)} block(s), "
                    f"the definition asks for block {block}.")
                continue
            start = starts[block - 1]
            column = _month_column(header, start, month)
            if column is None:
                result.unreadable.append(
                    f"{kpi.kpi_code}: {real} block {block} has no column for "
                    f"{month:%B %Y}.")
                continue

            code_column = start + 1
            found = 0
            for raw in rows[1:]:
                code = _text(raw[code_column]) if code_column < len(raw) else ""
                if not code:
                    continue
                value = _number(raw[column]) if column < len(raw) else None
                if value is None:
                    # A blank is not a zero. The engine records a missing
                    # actual, which is a question for the desk rather than a
                    # score of nought for the RM.
                    continue
                if kpi.negate:
                    value = -value
                result.rows.append(ActualRow(
                    sales_code=code, kpi_code=kpi.kpi_code, value=value,
                    sheet=real, block=block))
                seen_codes.add(code.upper())
                found += 1
            if not found:
                result.warnings.append(
                    f"{kpi.kpi_code}: {real} block {block} has no figures for "
                    f"{month:%B %Y}.")

    result.people = len(seen_codes)
    return result


def apply_actuals(result, eom_date, changed_by=""):
    """Write what was read, and report what changed.

    ``ScEmployeePerformanceActual.save`` refuses an update without a change
    reason, so updates carry one — the figures on a scorecard are something
    somebody will eventually have to account for.
    """
    from .scorecard_automation.models import ScEmployeePerformanceActual

    month = eom_date.replace(day=1)
    created = updated = unchanged = 0
    reason = f"actuals upload for {month:%B %Y}" + (f" by {changed_by}" if changed_by else "")

    for row in result.rows:
        existing = ScEmployeePerformanceActual.objects.filter(
            sales_code=row.sales_code, kpi_code=row.kpi_code, eom_date=month,
        ).first()
        if existing is None:
            ScEmployeePerformanceActual.objects.create(
                sales_code=row.sales_code, kpi_code=row.kpi_code,
                eom_date=month, kpi_value=row.value)
            created += 1
        elif float(existing.kpi_value) != row.value:
            existing.kpi_value = row.value
            existing._change_reason = reason
            existing.save()
            updated += 1
        else:
            unchanged += 1

    return {"created": created, "updated": updated, "unchanged": unchanged}


# ─────────────────────────────────────────────────────────────────────────────
# The per-person targets
# ─────────────────────────────────────────────────────────────────────────────
#
# ``Summary Allocation`` in the scorecard workbook is where each RM's own
# numbers live: 99 sales codes against 78 columns, grouped DEPOSITS / LOANS /
# AUM / TOTAL INCOME CONTRIBUTION / NPL / EXPENSE MANAGEMENT / FTP / CREDIT
# SERVICE FEES / LOAN LOSS / NFI and then a run of singly-named columns.
#
# These are genuinely per person, not per role: on the Commercial card one RM's
# deposit growth target is 4.35x his own base. So they load into
# ``ScEmployeeKpiTarget``, which the engine prefers over the role's target.
#
# The mapping below is by COLUMN NAME rather than position, because the sheet
# grows a column most years. ``base`` is the scorecard's "2025 FY" and
# ``growth`` its "GROWTH"; the engine adds them to get "2026 FY".

#: kpi_code -> (group label or None, column header, base column header or None)
#: Matched case-insensitively on the group/header pair as the sheet spells it.
ALLOCATION_COLUMNS = {
    "deposit_growth_retail": ("DEPOSITS", "Deposit Growth", "deposit_base"),
    "asset_growth": ("LOANS", "asset_growth", "Assets"),
    "portfolio_aum": ("AUM", "AUMGrowth", "Starting AUM"),
    "revenue_contribution": ("TOTAL INCOME CONTRIBUTION", "Growth",
                             "2024 (Income+(FTP-LoanLoss))"),
    "asset_drawdown": ("Disbursment", "Total", None),
    "trade_finance_income": ("Trade income", "Total", None),
    "new_customers": ("New_Cust", "", None),
    "plot_sales_volume": ("Plot_Sales", "", None),
    "plot_sales_value": ("PLOT_SALES_VALUE", "", None),
    "banca_life": ("banca_life", "", None),
    "banca_non_life": ("banca_non_life", "", None),
    "banca_total": ("banca_total", "", None),
    "casa": ("CASA", "", None),
    "loan_approvals": ("loan_approvals", "", None),
    "trade_loan_loss": ("trade_loan_loss", "", None),
    "digital_adoption": ("DIGITAL_ADOPTION", "", None),
    "collections_deposits": ("Collection_Deposits", "", None),
    "ecosystem": ("Ecosystem_Partner", "", None),
    "ppc": ("PPC", "2024.0", None),
    "active_customers": ("ACTIVE", "2024.0", None),
}

#: Row holding the group labels, and the row holding the column headers.
_ALLOC_GROUP_ROW = 2
_ALLOC_HEADER_ROW = 3
_ALLOC_CODE_COLUMN = 1          # column B, "SALES CODE"


def _alloc_labels(group_row, header_row):
    """[(group, header)] per column, with the group carried down."""
    width = max(len(group_row), len(header_row))
    labels, group = [], ""
    for i in range(width):
        cell = _text(group_row[i]) if i < len(group_row) else ""
        if cell:
            group = cell
        labels.append((group, _text(header_row[i]) if i < len(header_row) else ""))
    return labels


def _find_column(labels, group, header):
    """The index of the column whose (group, header) matches, or None."""
    want = (group.strip().lower(), (header or "").strip().lower())
    for i, (g, h) in enumerate(labels):
        if (g.strip().lower(), h.strip().lower()) == want:
            return i
    if not want[1]:
        # A singly-named column: the name may sit in either row.
        for i, (g, h) in enumerate(labels):
            if want[0] in (g.strip().lower(), h.strip().lower()):
                return i
    return None


def _grid(source, sheet_name):
    """[[cell, ...], ...] for one sheet of an .xlsx or .xlsb workbook."""
    name = str(getattr(source, "name", source) or "").lower()
    if name.endswith(".xlsb"):
        from pyxlsb import open_workbook

        with open_workbook(source) as wb:
            if sheet_name not in wb.sheets:
                return None
            with wb.get_sheet(sheet_name) as sheet:
                return [[c.v for c in row] for row in sheet.rows()]

    import openpyxl

    wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    match = next((s for s in wb.sheetnames if s.lower() == sheet_name.lower()), None)
    if match is None:
        return None
    return [list(r) for r in wb[match].iter_rows(values_only=True)]


def read_allocation(source, sheet_name="Summary Allocation"):
    """Per-person targets out of the allocation sheet.

    Returns ``(rows, warnings)`` where a row is
    ``{sales_code, kpi_code, kpi_target, base_value}``. A column the sheet does
    not carry is reported rather than assumed to be zero — a target of zero
    scores every RM at either 0 or a division by nothing.
    """
    grid = _grid(source, sheet_name)
    warnings = []
    if not grid or len(grid) <= _ALLOC_HEADER_ROW:
        return [], [f"{sheet_name}: not in this workbook, or empty."]

    labels = _alloc_labels(grid[_ALLOC_GROUP_ROW - 1], grid[_ALLOC_HEADER_ROW - 1])

    resolved = {}
    for kpi_code, (group, header, base_header) in ALLOCATION_COLUMNS.items():
        column = _find_column(labels, group, header)
        if column is None:
            warnings.append(
                f"{kpi_code}: no column {group!r}/{header!r} on {sheet_name}.")
            continue
        base = _find_column(labels, group, base_header) if base_header else None
        resolved[kpi_code] = (column, base)

    rows = []
    for raw in grid[_ALLOC_HEADER_ROW:]:
        code = _text(raw[_ALLOC_CODE_COLUMN]) if len(raw) > _ALLOC_CODE_COLUMN else ""
        if not code:
            continue
        for kpi_code, (column, base) in resolved.items():
            target = _number(raw[column]) if column < len(raw) else None
            if target is None:
                continue
            base_value = None
            if base is not None and base < len(raw):
                base_value = _number(raw[base])
            rows.append({
                "sales_code": code, "kpi_code": kpi_code,
                "kpi_target": target, "base_value": base_value,
            })
    return rows, warnings


def apply_allocation(rows, year, source_label="", changed_by=""):
    """Write per-person targets, replacing that person's figure for the year."""
    from .scorecard_automation.models import ScEmployeeKpiTarget

    created = updated = unchanged = 0
    for row in rows:
        existing = ScEmployeeKpiTarget.objects.filter(
            sales_code=row["sales_code"], kpi_code=row["kpi_code"], year=year,
        ).first()
        if existing is None:
            ScEmployeeKpiTarget.objects.create(
                sales_code=row["sales_code"], kpi_code=row["kpi_code"],
                year=year, kpi_target=row["kpi_target"],
                base_value=row["base_value"], source=source_label,
                updated_by=changed_by)
            created += 1
        elif (existing.kpi_target != row["kpi_target"]
                or existing.base_value != row["base_value"]):
            existing.kpi_target = row["kpi_target"]
            existing.base_value = row["base_value"]
            existing.source = source_label
            existing.updated_by = changed_by
            existing._change_reason = f"allocation upload for {year}"
            existing.save()
            updated += 1
        else:
            unchanged += 1
    return {"created": created, "updated": updated, "unchanged": unchanged}
