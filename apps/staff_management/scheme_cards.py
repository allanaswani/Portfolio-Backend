"""The Scheme scorecards, computed exactly as the desk's workbook computes them.

Source: ``Scheme_Scorecards - Template 2026 V3.xlsm`` (the cards) and
``2026_Actuals_Scheme_Scorecards.xlsx`` (the figures). Read cell by cell; see
``docs/scheme-scorecards-findings.md`` for the mechanics and the faults.

**Faithful, faults included - on instruction.** These cards are scored the way
the signed cards were, so the number on the platform is the number on the
signed document. That means reproducing what the template does even where it
is wrong: the Head of Schemes' revenue line is scored and left out of his total
(``J28 = SUM(J7:J27)``), his deposit actual is the revenue figure, the synergy
lines read the blocks their formulas name, PROJECT_ADMIN's FID line divides by
the text "<3%" and so always scores nought. Every one of those is a line in
:data:`CARDS` below with the template's own formula beside it, so correcting
one later is a one-line change somebody can see.

How the workbook looks a figure up, and therefore how this does::

    =VLOOKUP($C$2, '<sheet>'!$C$a:$Q$b, month + 3, 0)

- by the person's NAME (column C), exact and case-insensitive, as VLOOKUP is;
- in a block of rows ``a..b`` - each actuals sheet stacks its measures in
  seven-row blocks;
- in the month's column, Jan = F.

A name the block does not hold is ``#N/A``. Under IFERROR (the ratio lines)
that scores nought; anywhere else it propagates and the card's total is an
error, exactly as in Excel - reported, not papered over.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The workbook's own error value, carried through the arithmetic so a total
#: that Excel would show as #N/A is not shown here as a number.
NA = "#N/A"


class SchemeCardError(Exception):
    """A figure the card needs could not be produced - with the reason."""


# ─────────────────────────────────────────────────────────────────────────────
# The cards
# ─────────────────────────────────────────────────────────────────────────────

#: How a line's YTD target is formed.
#:   "fixed"    G = F                       (G typed equal to F)
#:   "month"    G = F * (month / 12)
#:   "joiner"   F = M * (12 - L) / 12 ;  G = F / ((12 - L) / (month - L))
#:              where L = the List sheet's prorate_new for this person
YTD_RULES = ("fixed", "month", "joiner")

#: How a line is scored (column I).
#:   ("ratio", cap)    IFERROR(IF(H/G > cap, cap, H/G), 0)
#:   ("pass", ceiling) IF(AND(H <= ceiling, H >= 0), 1, 0)
#:   ("audit_band",)   IF(AND(H<=G, H>=0), 1, IF(AND(H>G, H<2.49), 0.8, 0))
#:   ("none",)         I left empty - the weighted score is I*E = 0


@dataclass(frozen=True)
class Line:
    row: int                 # the card sheet's row, for tracing
    perspective: str
    kpi: str                 # stable code for the platform
    description: str
    weight: float
    target: object           # F (or M on a joiner line); text where typed
    ytd: str                 # one of YTD_RULES
    actual: tuple            # ("lookup", sheet, first_row, last_row)
                             # ("revenue",)  the Revenue Growth sum, typed
                             # ("loaded",)   typed on the card - a desk figure
                             # ("zero",)     H typed 0
                             # ("empty",)    H left empty
    score: tuple
    counted: bool = True     # inside the card's SUM for the total
    note: str = ""


@dataclass(frozen=True)
class Card:
    sheet: str
    title: str
    role: str
    lines: tuple = field(default_factory=tuple)


_SCHED = "Scheme_schedule_reconcilliation"
_GS = "Group_Synergies"

PROJECT_ADMIN = Card("PROJECT_ADMIN", "2026 SCHEMES ADMIN SCORECARD",
                     "PROJECT ADMIN", (
    Line(6, "Revenue", "scheme_revenue",
         "Portfolio Revenue Growth by 15% from previous year number based on "
         "allocated Portfolio", 0.05, 489166833.945, "month", ("revenue",),
         ("ratio", 1.2)),
    Line(7, "Scheme Management", "scheme_fid",
         "Maintain FID below 3% of the total monthly disbursement", 0.075,
         "<3%", "fixed", ("lookup", "FID", 3, 9), ("ratio", 1.2),
         note="Scored H / \"<3%\" - text - so IFERROR makes it 0 whatever "
              "the FID is. SCHEMES_ADMIN scores the same line pass/fail."),
    Line(8, "Scheme Management", "scheme_reconciliation_accuracy",
         "100% accuracy in reconciliation of Scheme schedules for all the "
         "disbursements", 0.075, 1, "fixed", ("lookup", _SCHED, 3, 9),
         ("ratio", 1.2)),
    Line(9, "Scheme Management", "scheme_early_salary_reconciliation",
         "Early salary payment accounts reconciliation by 20th monthly",
         0.1, 1, "fixed", ("lookup", _SCHED, 13, 19), ("ratio", 1.2)),
    Line(10, "Group Synergies", "scheme_number_of_property",
         "Number of Property", 0.05, 4, "month", ("lookup", _GS, 3, 9),
         ("ratio", 1.2), note="Reads the VIC block, as the template does."),
    Line(11, "Group Synergies", "scheme_value_of_property",
         "Value of Property Sales", 0.05, 4 * 8200000, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2),
         note="Reads the VIC block, as the template does."),
    Line(12, "Group Synergies", "scheme_vic_life",
         "VIC Premiums - life policies", 0.05, 4, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2)),
    Line(13, "Group Synergies", "scheme_vic_non_life",
         "VIC Premiums - non-life", 0.05, 4, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2),
         note="Reads the VIC block, as the template does."),
    Line(14, "Scheme Reporting", "scheme_statement_reporting",
         "Update scheme statement, by product and report by 20th monthly",
         0.075, 1, "fixed", ("lookup", _SCHED, 23, 29), ("ratio", 1.2)),
    Line(15, "Call Back Support", "scheme_callback_scheme_loans",
         "Timely processing of call back on Scheme Loans - within 12 hours",
         0.05, 1, "fixed", ("lookup", _SCHED, 33, 39), ("ratio", 1.2)),
    Line(16, "Call Back Support", "scheme_callback_non_scheme_loans",
         "Timely processing of call back on Non-Scheme Loans - within 24 "
         "hours", 0.05, 1, "fixed", ("lookup", _SCHED, 43, 49),
         ("ratio", 1.2)),
    Line(17, "Sales (Scheme & Retail)", "scheme_deposit_growth",
         "Deposit Growth", 0.025, 500000000, "month",
         ("lookup", "Deposit_Growth", 3, 9), ("ratio", 1.2)),
    Line(18, "Sales (Scheme & Retail)", "scheme_rm_productivity",
         "Scheme RM Weighted Productivity - 70% and above", 0.05, 0.7,
         "fixed", ("lookup", "Scheme_RM_Productivity", 3, 9), ("ratio", 1.2)),
    Line(19, "NPL Management", "scheme_npl",
         "Overall NPL - below 5% (active schemes)", 0.1, "<5%", "fixed",
         ("lookup", "NPL_Management", 3, 9), ("pass", 0.05)),
    Line(20, "Audit", "scheme_audit", "Audit Score", 0.05, 1.65, "fixed",
         ("lookup", "Audit_Score", 3, 9), ("ratio", 1.2),
         note="A ratio here; the other three cards use the audit band."),
    Line(21, "Customer Experience", "scheme_department_score",
         "Department Score - 70% and above", 0.025, 0.7, "fixed",
         ("lookup", "NPS", 3, 9), ("ratio", 1.0)),
    Line(22, "Customer Experience", "scheme_global_nps",
         "Global NPS score - 60% and above", 0.025, 0.6, "fixed",
         ("lookup", "NPS", 14, 20), ("ratio", 1.0)),
    Line(23, "Staff Engagement", "scheme_training",
         "32 Training hours by December 31st", 0.025, 32, "month",
         ("lookup", "Staff_Engagement", 3, 9), ("ratio", 1.0)),
    Line(24, "Staff Engagement", "scheme_leave",
         "Clear leave days before EOY", 0.025, 1, "month",
         ("lookup", "Staff_Engagement", 13, 19), ("ratio", 1.0)),
))

SCHEMES_ADMIN = Card("SCHEMES_ADMIN", "2026 SCHEMES ADMIN SCORECARD",
                     "SCHEMES ADMIN", (
    Line(6, "Revenue", "scheme_revenue",
         "Portfolio Revenue Growth by 15% from previous year number based on "
         "allocated Portfolio", 0.05, 489166833.945, "month", ("revenue",),
         ("ratio", 1.2)),
    Line(7, "Scheme Management", "scheme_fid",
         "Maintain FID below 3% of the total monthly disbursement", 0.075,
         "<3%", "fixed", ("lookup", "FID", 3, 9), ("pass", 0.03)),
    Line(8, "Scheme Management", "scheme_reconciliation_accuracy",
         "100% accuracy in reconciliation of Scheme schedules for all the "
         "disbursements", 0.075, 1, "fixed", ("lookup", _SCHED, 3, 9),
         ("ratio", 1.2)),
    Line(9, "Scheme Management", "scheme_early_salary_reconciliation",
         "Early salary payment accounts reconciliation by 20th monthly",
         0.1, 1, "fixed", ("lookup", _SCHED, 13, 19), ("ratio", 1.2)),
    Line(10, "Group Synergies", "scheme_number_of_property",
         "Number of Property", 0.05, 4, "month", ("lookup", _GS, 3, 9),
         ("ratio", 1.2), note="Reads the VIC block, as the template does."),
    Line(11, "Group Synergies", "scheme_value_of_property",
         "Value of Property Sales", 0.05, 4 * 8200000, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2),
         note="Reads the VIC block, as the template does."),
    Line(12, "Group Synergies", "scheme_vic_life",
         "VIC Premiums - life policies", 0.05, 4, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2)),
    Line(13, "Group Synergies", "scheme_vic_non_life",
         "VIC Premiums - non-life", 0.05, 4, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2),
         note="Reads the VIC block, as the template does."),
    Line(14, "Scheme Reporting", "scheme_statement_reporting",
         "Update scheme statement, by product and report by 20th monthly",
         0.075, 1, "fixed", ("lookup", _SCHED, 23, 29), ("ratio", 1.2)),
    Line(15, "Scheme Monitoring", "scheme_collections_timeliness",
         "Timeliness of collections of loan repayment (by product)", 0.05, 1,
         "fixed", ("loaded",), ("ratio", 1.2),
         note="Typed on the card (0.9 in June); loaded under Figures to "
              "load."),
    Line(16, "Scheme Monitoring", "scheme_total_disbursement",
         "Total Disbursement", 0.025, 750000000, "month",
         ("lookup", "Disbursments", 3, 9), ("ratio", 1.2)),
    Line(17, "Sales (Scheme & Retail)", "scheme_deposit_growth",
         "Deposit Growth", 0.025, 500000000, "month",
         ("lookup", "Deposit_Growth", 3, 9), ("ratio", 1.2)),
    Line(18, "Sales (Scheme & Retail)", "scheme_empanelment",
         "Schemes Empanelment - 1", 0.025, 1, "fixed",
         ("lookup", "Signs_ups", 13, 19), ("ratio", 1.2)),
    Line(19, "Sales (Scheme & Retail)", "scheme_sign_ups",
         "Schemes sign-up - 1", 0.025, 35, "month",
         ("lookup", "Signs_ups", 3, 9), ("ratio", 1.2)),
    Line(20, "Sales (Scheme & Retail)", "scheme_rm_productivity",
         "Scheme RM Weighted Productivity - 70% and above", 0.025, 0.7,
         "fixed", ("lookup", "Scheme_RM_Productivity", 3, 9), ("ratio", 1.0)),
    Line(21, "NPL Management", "scheme_npl",
         "Overall NPL - below 5% (active schemes)", 0.1, "<5%", "fixed",
         ("lookup", "NPL_Management", 3, 9), ("pass", 0.05)),
    Line(22, "Audit", "scheme_audit", "Audit Score", 0.05, 1.65, "fixed",
         ("lookup", "Audit_Score", 3, 9), ("audit_band",)),
    Line(23, "Customer Experience", "scheme_department_score",
         "Department Score - 70% and above", 0.025, 0.7, "fixed",
         ("lookup", "NPS", 3, 9), ("ratio", 1.0)),
    Line(24, "Customer Experience", "scheme_global_nps",
         "Global NPS score - 60% and above", 0.025, 0.6, "fixed",
         ("lookup", "NPS", 14, 20), ("ratio", 1.0)),
    Line(25, "Staff Engagement", "scheme_training",
         "32 Training hours by December 31st", 0.025, 32, "month",
         ("lookup", "Staff_Engagement", 3, 9), ("ratio", 1.0)),
    Line(26, "Staff Engagement", "scheme_leave",
         "Clear leave days before EOY", 0.025, 1, "month",
         ("lookup", "Staff_Engagement", 13, 19), ("ratio", 1.0)),
))

SCHEMES_RM = Card("SCHEMES_RM", "2026 SCHEMES RM SCORECARD", "SCHEMES RM", (
    # M6 = 15*(12-S6)/12 and S6 is empty, so M6 = 15.
    Line(6, "Scheme Business", "scheme_sign_ups", "Scheme Sign ups", 0.2, 15,
         "joiner", ("lookup", "Signs_ups", 3, 9), ("ratio", 1.2)),
    Line(7, "Scheme Business", "scheme_deposit_growth", "Deposit Growth",
         0.05, 200000000, "joiner", ("lookup", "Deposit_Growth", 3, 9),
         ("ratio", 1.2)),
    Line(8, "Disbursements", "scheme_utilization",
         "Funded Scheme - Un-utilized funds (70%)", 0.025, 0.7, "fixed",
         ("lookup", "Utilization", 3, 9), ("ratio", 1.2)),
    Line(9, "Disbursements", "scheme_penetration",
         "Scheme penetration - top 20 schemes to deliver 50M FY", 0.075, 1,
         "fixed", ("lookup", "Scheme_penetration", 3, 9), ("ratio", 1.2)),
    Line(10, "Disbursements", "scheme_commercial_disbursement",
         "Total Disbursement - Commercial", 0.2, 750000000, "joiner",
         ("lookup", "Disbursments", 3, 9), ("ratio", 1.2)),
    Line(11, "Group Synergies", "scheme_number_of_property",
         "Number of Property", 0.05, 4, "joiner", ("lookup", _GS, 13, 19),
         ("ratio", 1.2)),
    Line(12, "Group Synergies", "scheme_value_of_property",
         "Value of Property Sales", 0.05, 4 * 8200000, "joiner",
         ("lookup", _GS, 3, 9), ("ratio", 1.2),
         note="Reads the VIC block, as the template does."),
    Line(13, "Group Synergies", "scheme_vic_life",
         "VIC Premiums - life policies", 0.05, 4, "joiner",
         ("lookup", _GS, 3, 9), ("ratio", 1.2)),
    Line(14, "Group Synergies", "scheme_vic_non_life",
         "VIC Premiums - non-life", 0.05, 4, "joiner",
         ("lookup", _GS, 23, 29), ("ratio", 1.2),
         note="Reads the Value-of-property block, as the template does."),
    Line(15, "NPL Management", "scheme_par", "Overall PAR - below 5%",
         0.05, "<5%", "fixed", ("lookup", "NPL_Management", 13, 19),
         ("pass", 0.05)),
    Line(16, "NPL Management", "scheme_npl", "Overall NPL - below 5%",
         0.05, "<5%", "fixed", ("lookup", "NPL_Management", 3, 9),
         ("pass", 0.05)),
    Line(17, "Audit", "scheme_audit", "Audit Score below 1.65", 0.05, 1.65,
         "fixed", ("lookup", "Audit_Score", 3, 9), ("audit_band",)),
    Line(18, "Customer Experience", "scheme_department_score",
         "Department Score - 70% and above", 0.025, 0.7, "fixed",
         ("lookup", "NPS", 3, 9), ("ratio", 1.0)),
    Line(19, "Customer Experience", "scheme_global_nps",
         "Global NPS score - 60% and above", 0.025, 0.6, "fixed",
         ("lookup", "NPS", 14, 20), ("ratio", 1.0)),
    Line(20, "Staff Engagement", "scheme_training",
         "40 Training hours by each team member", 0.025, 40, "joiner",
         ("lookup", "Staff_Engagement", 3, 9), ("ratio", 1.0)),
    # G21 = F21*(K5/12) - leave is NOT joiner-prorated on this card.
    Line(21, "Staff Engagement", "scheme_leave",
         "Clear leave days before EOY", 0.025, 1, "month",
         ("lookup", "Staff_Engagement", 13, 19), ("ratio", 1.0)),
))

HOD_SCHEMES = Card("HOD_SCHEMES", "2026 SCHEMES SCORECARD", "HEAD OF SCHEMES", (
    Line(6, "Scheme Business", "scheme_revenue",
         "Grow Scheme Revenue by 10% from Dec 2025", 0.05, 467898710.7300001,
         "month", ("revenue",), ("ratio", 1.2), counted=False,
         note="Outside the card's total: J28 = SUM(J7:J27), and the weights "
              "E7:E27 already make 100%."),
    Line(7, "Sales (Scheme & Retail)", "scheme_sign_ups",
         "Scheme Sign ups / Approval list empanelment", 0.1, 45, "month",
         ("lookup", "Signs_ups", 13, 19), ("ratio", 1.2)),
    Line(8, "Sales (Scheme & Retail)", "scheme_deposit_growth",
         "Deposit Growth", 0.05, 500000000, "month", ("revenue",),
         ("ratio", 1.2),
         note="H8 is the revenue figure typed in, not a deposit lookup."),
    Line(9, "Sales (Scheme & Retail)", "scheme_rm_productivity",
         "Scheme RM Weighted Productivity - 80% and above", 0.05, 0.8,
         "fixed", ("lookup", "Scheme_RM_Productivity", 3, 9), ("ratio", 1.2),
         note="Reads the head's own row, not the team's."),
    Line(10, "Sales (Scheme & Retail)", "scheme_pb_dsr_productivity",
         "PB DSR Weighted Productivity - 70% and above", 0.05, 0.7, "fixed",
         ("lookup", "PB_DSR_Productivity", 3, 9), ("ratio", 1.2)),
    Line(11, "Sales (Scheme & Retail)", "scheme_focus_accounts",
         "Focus Accounts (PB DSR sales)", 0.05, 7680, "month",
         ("lookup", "Focus_Accounts", 3, 9), ("ratio", 1.2)),
    Line(12, "Sales (Scheme & Retail)", "scheme_approve_list_empanelment",
         "Approve list empanelment", 0.0, 24, "month", ("empty",),
         ("ratio", 1.2)),
    Line(13, "Group Synergies", "scheme_number_of_property",
         "Number of Property", 0.05, 4, "month", ("lookup", _GS, 3, 9),
         ("ratio", 1.2), note="Reads the VIC block, as the template does."),
    Line(14, "Group Synergies", "scheme_value_of_property",
         "Value of Property Sales", 0.05, 32800000, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2),
         note="Reads the VIC block, as the template does."),
    Line(15, "Group Synergies", "scheme_vic_life",
         "VIC Premiums - life policies", 0.05, 6, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2)),
    Line(16, "Group Synergies", "scheme_vic_non_life",
         "VIC Premiums - non-life", 0.05, 6, "month",
         ("lookup", _GS, 3, 9), ("ratio", 1.2),
         note="Reads the VIC block, as the template does."),
    Line(17, "Disbursements", "scheme_utilization",
         "Funded Scheme - Un-utilized funds (70%)", 0.025, 0.7, "fixed",
         ("lookup", "Utilization", 3, 9), ("ratio", 1.2)),
    Line(18, "Disbursements", "scheme_penetration",
         "Scheme penetration - deliver 50M annually per scheme for top 35",
         0.05, 1, "fixed", ("lookup", "Scheme_penetration", 3, 9),
         ("ratio", 1.2)),
    Line(19, "Disbursements", "scheme_total_disbursement",
         "Total Disbursement Schemes & PB DSR", 0.075, 3000000000, "month",
         ("lookup", "Disbursments", 3, 9), ("ratio", 1.2)),
    Line(20, "Strategic Initiatives", "scheme_strategic_initiatives",
         "Completion of strategic initiatives as per agreed timelines", 0.1,
         0.1, "fixed", ("zero",), ("none",),
         note="I20 has no formula, so the line scores 0."),
    Line(21, "NPL Management", "scheme_par", "Overall PAR - below 5%", 0.05,
         0.05, "fixed", ("lookup", "NPL_Management", 13, 19),
         ("pass", 0.05)),
    Line(22, "NPL Management", "scheme_npl", "Overall NPL - below 5%", 0.05,
         0.05, "fixed", ("lookup", "NPL_Management", 3, 9), ("pass", 0.05)),
    Line(23, "Audit", "scheme_audit", "Audit Score of 1.65", 0.05, 1.65,
         "fixed", ("lookup", "Audit_Score", 3, 9), ("audit_band",)),
    Line(24, "Customer Experience", "scheme_department_score",
         "Department Score - 70% and above", 0.025, 0.7, "fixed",
         ("lookup", "NPS", 3, 9), ("ratio", 1.0)),
    # $c$13:$q$20 - eight rows where the others read 14:20.
    Line(25, "Customer Experience", "scheme_global_nps",
         "Global NPS score - 60% and above", 0.025, 0.6, "fixed",
         ("lookup", "NPS", 13, 20), ("ratio", 1.0)),
    Line(26, "Staff Engagement", "scheme_training",
         "40 Training hours by each team member", 0.025, 40, "month",
         ("lookup", "Staff_Engagement", 3, 9), ("ratio", 1.0)),
    # G27 = 1 typed - leave not prorated on this card.
    Line(27, "Staff Engagement", "scheme_leave",
         "Clear leave days before EOY", 0.025, 1, "fixed",
         ("lookup", "Staff_Engagement", 13, 19), ("ratio", 1.0)),
))

CARDS = {card.sheet: card for card in
         (PROJECT_ADMIN, SCHEMES_ADMIN, SCHEMES_RM, HOD_SCHEMES)}

#: The List sheet's staff_role -> the card it uses (Monthly_Summ_2026 col D).
ROLE_SHEETS = {
    "schemes rm": "SCHEMES_RM", "scheme rm": "SCHEMES_RM",
    "project admin": "PROJECT_ADMIN",
    "schemes admin": "SCHEMES_ADMIN", "scheme admin": "SCHEMES_ADMIN",
    "head of schemes": "HOD_SCHEMES",
}

#: The platform role code for each card.
ROLE_CODES = {"SCHEMES_RM": "scheme_rm", "PROJECT_ADMIN": "scheme_project_admin",
              "SCHEMES_ADMIN": "scheme_admin", "HOD_SCHEMES": "scheme_head"}


# ─────────────────────────────────────────────────────────────────────────────
# The actuals workbook
# ─────────────────────────────────────────────────────────────────────────────


class Actuals:
    """The actuals workbook, read the way the template's VLOOKUPs read it."""

    def __init__(self, sheets, revenue_by_month):
        #: {sheet name: {row number: [cell values A..Q]}}
        self.sheets = sheets
        #: {month 1..12: that month's scheme revenue (NII + NFI), 2026}
        self.revenue_by_month = revenue_by_month

    @classmethod
    def from_workbook(cls, workbook):
        """``workbook`` opened with ``data_only=True`` - the computed values,
        which is what VLOOKUP sees."""
        sheets = {}
        for ws in workbook.worksheets:
            rows = {}
            for index, row in enumerate(
                    ws.iter_rows(min_row=1, max_row=60, max_col=17,
                                 values_only=True), start=1):
                rows[index] = list(row) + [None] * (17 - len(row))
            sheets[ws.title] = rows
        return cls(sheets, _revenue_2026(workbook))

    def lookup(self, sheet, first, last, name, month):
        """=VLOOKUP(name, sheet!$C$first:$Q$last, month + 3, 0)"""
        value = self.cell(sheet, first, last, name, month)
        return 0.0 if value is None else value

    def cell(self, sheet, first, last, name, month):
        """The cell VLOOKUP lands on - None where it is EMPTY, which VLOOKUP
        itself reports as 0. Kept apart so a card can say a figure was never
        entered for that month instead of presenting a blank as a nought."""
        rows = self.sheets.get(sheet)
        if rows is None:
            raise SchemeCardError(f"the actuals workbook has no {sheet!r} sheet")
        wanted = _fold(name)
        for number in range(first, last + 1):
            row = rows.get(number)
            if row is None:
                continue
            if _fold(row[2]) == wanted:           # column C
                value = row[2 + month + 2]        # C + (month + 3) - 1
                if value is None or value == "":
                    return None
                if isinstance(value, bool):
                    return float(value)
                if isinstance(value, (int, float)):
                    return float(value)
                return value                      # text - Excel returns it
        return NA

    def revenue_ytd(self, month):
        """The figure typed into the revenue cells: the 2026 scheme revenue,
        January to the review month - ``Revenue Growth!F18 =
        SUM(B8:G8)`` for June."""
        if not self.revenue_by_month:
            raise SchemeCardError(
                "the actuals workbook's 'Revenue Growth' sheet has no 2026 row")
        # Left to right, one addition at a time, as Excel's SUM does. Not
        # ``sum()``: since Python 3.12 that compensates for rounding and lands
        # 0.0000002 away from the figure on the signed card.
        total = 0.0
        for m in range(1, month + 1):
            total += float(self.revenue_by_month.get(m, 0) or 0)
        return total


def _revenue_2026(workbook):
    """``Revenue Growth``: the pivot's 2026 row, January..December in B..M."""
    if "Revenue Growth" not in workbook.sheetnames:
        return {}
    for row in workbook["Revenue Growth"].iter_rows(min_row=1, max_row=40,
                                                     values_only=True):
        if row and row[0] in (2026, "2026", 2026.0):
            return {m: row[m] for m in range(1, 13) if m < len(row)}
    return {}


def _fold(value):
    return " ".join(str(value or "").split()).strip().lower()


# ─────────────────────────────────────────────────────────────────────────────
# Scoring - each rule is the template's formula, error values and all
# ─────────────────────────────────────────────────────────────────────────────


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _ytd_target(line, month, joined):
    """→ (FY target as shown, YTD target) - NA where Excel would error."""
    if line.ytd == "fixed":
        return line.target, line.target
    if line.ytd == "month":
        return line.target, line.target * (month / 12)
    # joiner: F = M*(12-L)/12 ; G = F/((12-L)/(month-L))
    full = line.target * (12 - joined) / 12
    try:
        ytd = full / ((12 - joined) / (month - joined))
    except ZeroDivisionError:
        ytd = NA
    return full, ytd


def _score(rule, actual, ytd):
    kind = rule[0]
    if kind == "none":
        return None
    if kind == "ratio":
        cap = rule[1]
        # IFERROR(IF((H/G)>cap, cap, H/G), 0)
        if not (_num(actual) and _num(ytd)) or ytd == 0:
            return 0.0
        ratio = actual / ytd
        return cap if ratio > cap else ratio
    if kind == "pass":
        # IF(AND(H<=ceiling, H>=0), 1, 0) - no IFERROR, so an error stays one.
        if actual == NA:
            return NA
        if not _num(actual):
            return 0.0      # text compares above every number in Excel
        return 1.0 if 0 <= actual <= rule[1] else 0.0
    if kind == "audit_band":
        # IF(AND(H<=G,H>=0),1,IF(AND(H>G,H<2.49),0.8,0))
        if actual == NA:
            return NA
        if not _num(actual):
            return 0.0
        if 0 <= actual <= ytd:
            return 1.0
        if ytd < actual < 2.49:
            return 0.8
        return 0.0
    raise ValueError(f"unknown scoring rule {rule!r}")


def compute_card(card, name, month, joined, actuals, loaded=None):
    """One person's card, exactly as the template computes it.

    ``joined`` is the List sheet's ``prorate_new`` (months before joining).
    ``loaded`` is ``{kpi code: value}`` for the figures the card has typed on
    it and the actuals workbook does not carry.

    → ``{"lines": [...], "total": float | NA, "weight": float}``
    """
    loaded = loaded or {}
    out, total, weight = [], 0.0, 0.0
    for line in card.lines:
        source = line.actual[0]
        empty = False
        if source == "lookup":
            _kind, sheet, first, last = line.actual
            raw = actuals.cell(sheet, first, last, name, month)
            empty = raw is None
            actual = 0.0 if empty else raw
        elif source == "revenue":
            actual = actuals.revenue_ytd(month)
        elif source == "loaded":
            actual = loaded.get(line.kpi)
        elif source == "zero":
            actual = 0.0
        else:   # "empty" - shown blank; IFERROR scores it 0 regardless
            actual = None
        full, ytd = _ytd_target(line, month, joined)
        # A desk figure nobody has loaded is left unscored and out of the
        # total - which is what the June run did: Benedicto Juma's signed
        # 0.6091 is his card without the collections line, typed in later.
        score = (None if actual is None and source == "loaded"
                 else _score(line.score, actual, ytd))
        if score is None:
            weighted = 0.0 if line.score[0] == "none" else None
        elif score == NA:
            weighted = NA
        else:
            weighted = score * line.weight
        if line.counted:
            weight += line.weight
            if weighted == NA or total == NA:
                total = NA
            elif weighted is not None:
                total += weighted
        out.append({
            "row": line.row, "kpi": line.kpi, "perspective": line.perspective,
            "description": line.description, "weight": line.weight,
            "fy_target": full, "ytd_target": ytd, "actual": actual,
            "score": score, "weighted": weighted, "counted": line.counted,
            "note": line.note, "empty": empty,
        })
    return {"lines": out, "total": total, "weight": weight}


# ─────────────────────────────────────────────────────────────────────────────
# Loading the workbooks, storing the cards, and showing one
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RosterRow:
    sales_code: str
    name: str
    role: str
    sheet: str
    joined: int


def read_roster(template):
    """The template's ``List`` sheet → ``([RosterRow], unplaced)``, where
    ``unplaced`` is ``[(row number, name, role)]`` for rows with no card or no
    sales code.

    The List is the authority for who holds a Scheme card: it is what the
    desk's macro walks to produce them (``Summary_Run_Log``).
    """
    if "List" not in template.sheetnames:
        raise SchemeCardError("the template has no 'List' sheet")
    rows, unplaced = [], []
    for number, row in enumerate(template["List"].iter_rows(
            min_row=2, values_only=True), start=2):
        row = list(row) + [None] * 14
        code, name, role, joined = row[1], row[2], row[3], row[10]
        if not name:
            continue
        sheet = ROLE_SHEETS.get(_fold(role))
        if sheet is None or not str(code or "").strip():
            unplaced.append((number, name, role))
            continue
        rows.append(RosterRow(str(code).strip().upper(), str(name).strip(),
                              str(role).strip(), sheet,
                              int(joined) if _num(joined) else 0))
    return rows, unplaced


_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def template_month(template):
    """The review month the template is set to → 1..12, or None.

    ``Constants!B2`` ("Month_count") - the number every card's ``K5`` and
    ``Constants!C7`` ("Jun-26") are driven from.
    """
    if "Constants" in template.sheetnames:
        for row in template["Constants"].iter_rows(min_row=1, max_row=10,
                                                   max_col=2, values_only=True):
            if row and str(row[0] or "").strip().lower() == "month_count":
                if _num(row[1]) and 1 <= int(row[1]) <= 12:
                    return int(row[1])
    return None


def template_period(template):
    """The template's review month as a date (the 1st), or None -
    ``Constants!B4`` ("Review", 30 Jun 2026), else Month_count in this year."""
    import datetime

    if "Constants" in template.sheetnames:
        for row in template["Constants"].iter_rows(min_row=1, max_row=10,
                                                   max_col=2, values_only=True):
            if row and str(row[0] or "").strip().lower() == "review":
                value = row[1]
                if isinstance(value, datetime.datetime):
                    value = value.date()
                if isinstance(value, datetime.date):
                    return value.replace(day=1)
    month = template_month(template)
    if month is None:
        return None
    return datetime.date(datetime.date.today().year, month, 1)


def months_with_figures(actuals, names):
    """The months the actuals workbook actually holds figures for → set.

    A month is there when a row naming somebody on the List (``names``), in a
    sheet the cards look up, carries a real non-zero number in that month's
    column. Used to refuse a month the workbook has nothing for: every lookup
    would read an empty cell as 0, and the card would score only the lines
    that pass on a blank - exactly how a September card read 15%.

    Only the List's names, because every block's HEADER row carries the
    month dates themselves across all twelve columns; only non-zero numbers,
    because a stray formula left on a row (Utilization!L3 on Phiedis Kyengo's
    row) evaluates to 0 in July and would otherwise make July look loaded.
    """
    wanted = {_fold(name) for name in names}
    sheets = {line.actual[1] for card in CARDS.values() for line in card.lines
              if line.actual[0] == "lookup"}
    found = set()
    for sheet in sheets:
        for row in actuals.sheets.get(sheet, {}).values():
            if _fold(row[2]) not in wanted:
                continue
            for month in range(1, 13):
                value = row[2 + month + 2]
                if _num(value) and value != 0:
                    found.add(month)
    return found


def compute_months(template, actuals_book, loaded_for=None, only=None):
    """Every month the actuals workbook holds, for everybody on the List →
    ``({month: [(RosterRow, result)]}, unplaced)``.

    One load, every month - so any month can be opened afterwards, not just
    the one the template happens to be set to. ``only`` restricts it to one
    month (1..12), refused if the workbook holds nothing for it.
    ``loaded_for(month)`` gives that month's figures typed under Figures to
    load.
    """
    roster, unplaced = read_roster(template)
    actuals = Actuals.from_workbook(actuals_book)
    held = sorted(months_with_figures(actuals,
                                      [person.name for person in roster]))
    if not held:
        raise SchemeCardError("The actuals workbook holds no monthly figures "
                              "for anybody on the List.")
    if only is not None:
        if only not in held:
            raise SchemeCardError(
                f"The actuals workbook has no figures for "
                f"{_MONTHS[only - 1]}. It holds "
                f"{', '.join(_MONTHS[m - 1] for m in held)}.")
        held = [only]
    out = {}
    for month in held:
        loaded = loaded_for(month) if loaded_for else {}
        out[month] = [
            (person, compute_card(CARDS[person.sheet], person.name, month,
                                  person.joined, actuals,
                                  loaded.get(person.sales_code, {})))
            for person in roster]
    return out, unplaced


def loaded_figures(month_start):
    """``{sales code: {kpi: value}}`` - figures typed on a Scheme card that the
    actuals workbook does not carry, entered under Figures to load."""
    from .scorecard_automation.models import ScEmployeePerformanceActual

    codes = {line.kpi for card in CARDS.values() for line in card.lines
             if line.actual[0] == "loaded"}
    out = {}
    for row in ScEmployeePerformanceActual.objects.filter(
            kpi_code__in=codes, eom_date=month_start):
        out.setdefault(row.sales_code.strip().upper(), {})[row.kpi_code] = (
            float(row.kpi_value))
    return out


def store(cards, month_start, loaded_by=""):
    """One row per person per month, replaced on reload → how many."""
    from .models import SchemeScorecard

    for person, result in cards:
        total = result["total"]
        SchemeScorecard.objects.update_or_create(
            sales_code=person.sales_code, month=month_start,
            defaults={
                "staff_name": person.name, "sheet": person.sheet,
                "joined": person.joined, "card": result,
                "total": total if _num(total) else None,
                "loaded_by": loaded_by,
            })
    return len(cards)


def stored_for(sales_code, as_at=None):
    """The newest stored card on or before ``as_at`` → SchemeScorecard or
    None."""
    from .models import SchemeScorecard

    rows = SchemeScorecard.objects.filter(
        sales_code__iexact=(sales_code or "").strip())
    if as_at is not None:
        rows = rows.filter(month__lte=as_at)
    return rows.order_by("-month").first()


def months_loaded(sales_code):
    """The months a person's Scheme card is stored for → ["2026-01", ...]."""
    from .models import SchemeScorecard

    return [m.strftime("%Y-%m") for m in SchemeScorecard.objects.filter(
        sales_code__iexact=(sales_code or "").strip())
        .order_by("month").values_list("month", flat=True)]


def card_payload(record, asked=None):
    """A stored Scheme card in the shape every other card has, so the same
    page, download and signature show it. ``asked`` is the month end the
    viewer asked for; where it is not the stored month, the card says so."""
    card = CARDS.get(record.sheet)
    data = record.card or {}
    perspectives, seen = [], {}
    scored = unscored = 0.0
    month_end = _month_end(record.month)
    for line in data.get("lines", []):
        name = line["perspective"]
        if name not in seen:
            seen[name] = {"perspective": name, "weight": 0.0, "lines": []}
            perspectives.append(seen[name])
        seen[name]["weight"] += line["weight"]
        score, weighted = line.get("score"), line.get("weighted")
        if _num(score):
            scored += line["weight"]
        else:
            unscored += line["weight"]
        pending = ""
        if score is None and line["kpi"] == "scheme_collections_timeliness":
            pending = ("This is a figure the desk types on the card. "
                       "Administration enters it under Scorecards → Figures "
                       "to load, and the cards are loaded again.")
        elif score == NA:
            pending = ("The actuals workbook has no row for this name in the "
                       "block this line reads, so the workbook's own total is "
                       "an error too.")
        as_at = f"as at {month_end.day} {month_end:%b %Y}"
        if line.get("empty"):
            # Scored as the workbook scores it - an empty cell is 0 - but
            # said, so a blank is never read as a real nought.
            as_at = (f"no figure entered for {month_end:%B} in the actuals "
                     f"workbook - read as 0, as the workbook reads it")
        fy, ytd, actual = (line["fy_target"], line["ytd_target"],
                           line["actual"])
        seen[name]["lines"].append({
            "kpi_code": line["kpi"],
            "kpi_name": line["description"],
            "measure_of_success": line["description"],
            "weight": line["weight"],
            "ytd_target": ytd if _num(ytd) else None,
            "annual_target": fy if _num(fy) else None,
            # "<3%", "<5%" - the card writes these targets as text.
            "target_text": fy if isinstance(fy, str) else "",
            "prior_year": None,
            "growth_target": None,
            "target_field": "",
            "target_source": "the Scheme scorecard template",
            "full_year_target": fy == ytd,
            "ytd_actual": actual if _num(actual) else None,
            "warehouse_said": None,
            "score": score if _num(score) else None,
            "weighted_score": weighted if _num(weighted) else None,
            # The Head of Schemes' revenue line is scored and left out of his
            # total, as on his card.
            "counted_in_total": line.get("counted", True),
            "as_at": as_at,
            "as_at_date": month_end.isoformat(),
            "higher_is_better": True,
            "full_marks_rule": "",
            "score_cap": None,
            "pending": pending,
            "pending_label": "Not loaded" if pending else "",
            "diagnostic": line.get("note", ""),
        })
    total = record.total
    return {
        "has_card": True,
        "live": False,
        "scheme": True,
        "staff": {
            "sales_code": record.sales_code,
            "name": record.staff_name,
            "title": card.role if card else record.sheet,
            "role_code": ROLE_CODES.get(record.sheet, record.sheet),
            "branch": "Head Office",
            "team_leader": "",
            "roster": "the Scheme scorecard workbook",
            "started": None,
        },
        "book": {"customers": None, "note": ""},
        "period": {"label": record.month.strftime("%B %Y"),
                   "as_at": month_end.isoformat()},
        "target_source": "the Scheme scorecard template",
        "performance_score": round(total, 4) if _num(total) else None,
        "scored_lines": sum(1 for p in perspectives for ln in p["lines"]
                            if ln["score"] is not None),
        "pending_lines": sum(1 for p in perspectives for ln in p["lines"]
                             if ln["pending"]),
        "scored_weight": round(scored, 4),
        "unscored_weight": round(unscored, 4),
        "perspectives": perspectives,
        "months_loaded": months_loaded(record.sales_code),
        # A month the desk only partly filled in. Scored exactly as the
        # workbook would score it - but said at the top, because a January
        # card with 14 of 16 lines empty reads 4.6% and looks like a
        # collapse rather than like a workbook nobody has filled in yet.
        "coverage_note": _coverage_note(data.get("lines", []), record.month),
        "showing_other_month": (
            "" if asked is None or asked.replace(day=1) == record.month else
            f"Nothing is loaded for {asked:%B %Y}; this is "
            f"{record.month:%B %Y}, the latest month on or before it."),
        "how_scored": ("Computed exactly as the desk's Scheme scorecard "
                       "workbook computes it, line by line - including where "
                       "the workbook's own formulas are known to be wrong. "
                       "Any line that differs from what it says carries a "
                       "note."),
    }


def _coverage_note(lines, month):
    looked_up = [ln for ln in lines if "empty" in ln]
    empty = sum(1 for ln in looked_up if ln["empty"])
    if not empty:
        return ""
    return (f"{empty} of {len(lines)} lines had no figure for "
            f"{month:%B %Y} in the actuals workbook, so they read as 0 - as "
            f"the workbook itself reads them. Those lines are marked; the "
            f"score is low because the month is not filled in, not because "
            f"of the results.")


def _month_end(first):
    import datetime

    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt - datetime.timedelta(days=1)
