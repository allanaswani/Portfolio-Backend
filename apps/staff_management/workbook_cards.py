"""Scorecards computed exactly as the desk's workbooks compute them.

Two workbooks are built the same way - the back-office one and the sales
one (``Portfolio Management - Q3 2026_scorecards.xlsb`` over
``2026_Actual_Template.xlsx``) - and :data:`SPECS` holds the few places they
differ: which cells the macro types (the sales macro fills C2 name, C3
branch, E2 role and E3 the BBM, then reads K2), the List's columns, and where
Monthly_Summ keeps what the macro recorded. Everything else is the
workbook's own formulas, so what follows for the back office holds for both.

Against the real files: back office September 108 of 108 exact; sales July
72 of 79 and August 76 of 83 before a fix (Excel matches sheet names without
case - the Commercial cards ask for "Trade_Finance_Income" and the template
says "Trade_Finance_income"), 160 of 162 after it. Months before Q3 were run
on the Q1/Q2 workbooks, so they differ - and a stored card shows what the
macro recorded for them.

Two files make a back-office card, and the desk keeps both:

* ``2026_BO_Non_Sales_Scorecards ….xlsb`` - one card sheet per role
  (TELLER_SCORECARD, BOM_SCORECARD, …), the List of who holds which, and the
  Constants the targets cascade from;
* ``2026_BO_Actual_Template.xlsx`` - a sheet per feed (KYC, CASA, NPS, …),
  a row per person and a column per month.

The desk's macro (``explode_scores`` / ``Do_Monthly_Summary``) walks the List
and, for each person, types their NAME into the card sheet's C2 and their
BRANCH into C4, sets the month in Constants, and reads the score in J6. Every
figure on the card is a formula over those two cells:

    PM          typed on the card (or looked up by branch in Constants)
    YTD Target  =F10*('Constants'!$B$2-$M10)          monthly × months
                =F16*(('Constants'!$B$2-$M16)/12)     annual × months/12
                =F11                                   a level
    Actual      =VLOOKUP($C$2, INDIRECT("[template]"&$L10&"!$c:$R"), $O$1, 0)
    % Score     =IF(H10/G10>1.2, 1.2, H10/G10)  - and 20 other shapes
    Weighted    =I10*E10

This module does not re-type those rules. It reads the formulas themselves
out of the .xlsb - shared formulas included, which the usual readers leave as
``#PTG1!`` - and evaluates them with a small Excel evaluator, person by person
and month by month, exactly as the macro does. So next year's workbook, with
its own lines, weights and caps, is next year's cards with no code change, and
the September card for Bob Waigwa is 92.58% because that is what the
workbook's own J6 says when his name is in C2.

Only the cards are evaluated. The List, BMs, Constants and mapping sheets are
read as the values the workbook last saved; the macro does not recompute them
either.

Everything here is pure: :func:`read_scorecards` and :func:`read_actuals`
turn the two files into plain data, :func:`compute` turns that data into
cards. Storing them is :func:`store`.
"""

from __future__ import annotations

import datetime
import math
import os
import re
import struct
import tempfile

#: The macro's own mapping of List role → card sheet (explode_scores,
#: explode_RBO_scores). BOMCSO and CASHTELLER_SCORECARD are still in the
#: workbook but read the 2023/2024 templates and no List role reaches them.
ROLE_SHEETS = {
    "BOM": "BOM_SCORECARD",
    "CSO": "CSO_SCORECARD",
    "CSO_UB": "CSO_UB_SCORECARD",
    "CSM_DB": "CSM_DB_SCORECARD",
    "Cash_Center": "CASH_TELLER_SCORECARD",
    "Teller": "TELLER_SCORECARD",
    "BSA": "BSA_SCORECARD",
    "RBO": "RBO_SCORECARD",
    "TL_RBO": "TL_RBO_SCORECARD",
}

#: The platform role each card sheet is shown under.
ROLE_CODES = {
    "BOM_SCORECARD": "bo_bom",
    "CSO_SCORECARD": "bo_cso",
    "CSO_UB_SCORECARD": "bo_cso_ub",
    "CSM_DB_SCORECARD": "bo_csm_diaspora",
    "CASH_TELLER_SCORECARD": "bo_cash_teller",
    "TELLER_SCORECARD": "bo_teller",
    "BSA_SCORECARD": "bo_bsa",
    "RBO_SCORECARD": "bo_rbo",
    "TL_RBO_SCORECARD": "bo_tl_rbo",
}

TITLES = {
    "BOM_SCORECARD": "Branch Operations Manager",
    "CSO_SCORECARD": "Customer Service",
    "CSO_UB_SCORECARD": "Customer Service - Ultimate Banking",
    "CSM_DB_SCORECARD": "Client Service Manager - Diaspora Banking",
    "CASH_TELLER_SCORECARD": "Cash Centre Teller",
    "TELLER_SCORECARD": "Teller",
    "BSA_SCORECARD": "Branch Service Ambassador",
    "RBO_SCORECARD": "Retail Back Office (Account Opening)",
    "TL_RBO_SCORECARD": "Retail Back Office Team Leader",
}

#: The sales workbook's macro (explode_scores / Do_Monthly_Summary): List
#: role → card sheet, and the platform role each is shown under.
SALES_ROLE_SHEETS = {
    "SME BBC": "Business_Banking", "SME RM": "Business_Banking",
    "SME ARM": "Business_Banking",
    "PB BBC": "Personal_Banking", "PB RM": "Personal_Banking",
    "PB ARM": "Personal_Banking",
    "Ultimate RM": "Ultimate_RM",
    "SNR MGR ULTIMATE": "SNR_MGR_ULTIMATE",
    "DIASPORA ARM": "Diaspora", "DIASPORA RM": "Diaspora",
    "Mortgage Business ARM": "Mortgage_Business",
    "Mortgage Business RM": "Mortgage_Business",
    "COMMERCIAL RM": "Commercial",
    "COMMERCIAL RM- TRADE": "Commercial_trade",
    "HEAD OF COMMERCIAL": "HEAD_COMMERCIAL",
}
SALES_ROLE_CODES = {
    "SME BBC": "sme_bbc", "SME RM": "sme_rm", "SME ARM": "sme_arm",
    "PB BBC": "pb_bbc", "PB RM": "pb_rm", "PB ARM": "pb_arm",
    "Ultimate RM": "ultimate_rm", "SNR MGR ULTIMATE": "snr_mgr_ultimate",
    "DIASPORA ARM": "diaspora_arm", "DIASPORA RM": "diaspora_rm",
    "Mortgage Business ARM": "mortgage_business_arm",
    "Mortgage Business RM": "mortgage_business_rm",
    "COMMERCIAL RM": "commercial_rm",
    "COMMERCIAL RM- TRADE": "commercial_rm_trade",
    "HEAD OF COMMERCIAL": "head_commercial",
}

BACK_OFFICE, SALES, BRANCH_BUSINESS = "back_office", "sales", "branch_business"
RETAIL_BO = "retail_back_office"

#: The Retail Back Office workbook's macro (retail_back_office_scorecards):
#: List role (column D) → card sheet. Its INITIATIVES_* sheets are not cards
#: anybody holds; one line of the APM, SPM, sector RM, SRM and trade cards
#: reads their total.
RBO_ROLE_SHEETS = {
    "RELATIONSHIP OFFICER - COMMERCIAL": "RO_COMMERCIAL",
    "CREDIT ANALYST - COMMERCIAL": "COMMERCIAL_ANALYST",
    "MANAGER CREDIT ANALYST - COMMERCIAL": "MANAGER_COMMERCIAL_ANALYST",
    "CREDIT ANALYST - RETAIL": "RETAIL_ANALYST",
    "CREDIT ORIGINATION MANAGER": "CREDIT_ORG_MANAGER",
    "PRODUCTS OFFICER - LENDING": "PO_LENDING",
    "ASSETS PRODUCTS MANAGER": "ASSETS_PRODUCTS_MANAGER",
    "PRODUCTS OFFICER - LIABILITIES": "PO_LIABILITIES",
    "SENIOR PRODUCT MANAGER": "SENIOR_PRODUCT_MANAGER",
    "SECTOR RM - HEALTH": "SECTOR_RM_HEALTH",
    "SECTOR RM - WATER AND ENERGY": "SECTOR_RM_WATER_AND_ENERGY",
    "SENIOR RELATIONSHIP MANAGER": "SENIOR_RELATIONSHIP_MANAGER",
    "TRADE MIDDLE OFFICE": "TRADE_MIDDLE_OFFICE",
    "RM - TRADE FINANCE SALES": "RM_TRADE_FINANCE_SALES",
}
RBO_INITIATIVE_SHEETS = ("INITIATIVES_APM", "INITIATIVES_SPM", "INITIATIVES_HEALTH",
                         "INITIATIVES_WATER_AND_ENERGY", "INITIATIVES_SRM",
                         "INITIATIVES_TRADE_FINANCE")
RBO_ROLE_CODES = {sheet: "rbo_" + sheet.lower() for sheet in RBO_ROLE_SHEETS.values()}
RBO_ROSTER = "the retail back office scorecards workbook"

#: IB_Scorecards_Template (.xlsm), Institutional Banking. Its macro
#: (generate_ib_scorecards) puts "IB RM" on IB_RM and "HEAD OF INSTITUTIONAL
#: BANKING" on HOD_IB, typing C2 name, E2 role, C3 branch, E3 reports to; the
#: score is K2 (=L23). Every actual is VLOOKUP($C$2, INDIRECT("[2026_IB_
#: Actual_Template_v2.xlsx]"&M&"!$c:$R"), Constants!B2+4, 0) on the template.
IB = "ib"
IB_ROLE_SHEETS = {"IB RM": "IB_RM", "HEAD OF INSTITUTIONAL BANKING": "HOD_IB"}
IB_ROLE_CODES = {"IB_RM": "ib_rm", "HOD_IB": "ib_head"}
IB_ROSTER = "the institutional banking scorecards workbook"
#: The workbook's own tables - read as values, never evaluated.
IB_TABLE_SHEETS = ("List", "Constants", "Monthly_Summary", "mapping")
#: What the cards' formulas name: the IB actuals template.
IB_TEMPLATE_MARK = "ib_actual_template"
#: The IB actuals template's per-person sheets (any one of them is not enough).
IB_TEMPLATE_SHEETS = {"Revenue", "Deposit_Growth", "Deposit_Mix",
                      "Interest_Expense_Rate", "Client_Retention"}
#: Its account-level working sheets: the per-person sheets are computed from
#: them, the cards never read them, and their columns are not months.
IB_RAW_SHEETS = ("Portfolio", "PVTS")

#: Master Scorecard - 2026.xlsm, HFDI (property). Its macro (explode_
#: objectives) walks staff_list (active = 1 in column N) and puts each role on
#: the sheet below, typing C2 name and C3 project; Do_Monthly_Summary writes
#: J2 to Monthly_Summ by staff_id. People are keyed by staff_id (the PF):
#: staff_list has no sales codes.
HFDI = "hfdi"
HFDI_ROLE_SHEETS = {
    "Relationship Manager": "Relationship_Manager",
    "Relationship Officer": "Relationship_Officer",
    "Operations Officer": "Ops_Officer",
    "Site Administrator": "Site_Admin",
    "Sales Manager": "Sales_Manager",
    "Team Leader": "Team_Leader",
    "Property Advisor": "Property_Advisor",
    "Property Activations Officer": "Property_Activations_Officer",
    "Head of Agency": "Agency",
    "Collections Officer - Tenant Purchase Scheme": "Collections_Officer",
}
HFDI_ROLE_CODES = {s: "hfdi_" + s.lower() for s in HFDI_ROLE_SHEETS.values()}
HFDI_ROSTER = "the HFDI master scorecard workbook"
#: Its tables: read as values. The List is staff_list; Constants is mapping.
HFDI_TABLE_SHEETS = ("staff_list", "targets", "mapping", "Monthly_Summ")
#: Scorecard_Actual_Template_2026.xlsx: A staff_id, B name, C role, D
#: project, E..P January..December.
HFDI_TEMPLATE_SHEETS = {"own_project_sales", "bank_accounts", "own_leads",
                        "leads_followups"}


class Spec:
    """Where one workbook keeps things. Everything else is its formulas."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


SPECS = {
    BACK_OFFICE: Spec(
        book=BACK_OFFICE,
        label="back-office",
        marker="TELLER_SCORECARD",
        role_sheets=ROLE_SHEETS,
        # List: PF, sales code, name, role, branch
        list_cols={"pf": 0, "code": 1, "name": 2, "role": 3, "branch": 4},
        # The cells the macro types before it reads the score: C2, C4.
        inputs={(1, 2): "name", (3, 2): "branch"},
        score=(5, 9),                                 # J6
        # Constants!B1 is the VLOOKUP column into the template's C:R
        # (January = 5), B2 the months elapsed.
        month_column=(0, 1), month_count=(1, 1), year=(4, 1),
        header="Perspective", ends=("TOTAL SCORE",),
        cols={"perspective": 1, "measure": 2, "initiative": 3, "weight": 4,
              "prior": None, "growth": None, "fy": 5, "ytd": 6, "actual": 7,
              "score": 8, "weighted": 9, "feed": 11},
        # (sheet, header row, sales code column, January's column)
        summaries=(("Monthly_Summ", 0, 1, 6), ("RBO_Monthly_Summ", 0, 1, 6)),
        files=("scorecards", "actuals"),
        source="the back-office scorecards workbook",
    ),
    SALES: Spec(
        book=SALES,
        label="sales",
        marker="Business_Banking",
        role_sheets=SALES_ROLE_SHEETS,
        list_cols={"pf": None, "code": 0, "name": 1, "role": 2, "branch": 3,
                   "bbm": 4},
        # C2 name, C3 branch, E3 the BBM, E2 the role.
        inputs={(1, 2): "name", (2, 2): "branch", (2, 4): "bbm",
                (1, 4): "role"},
        score=(1, 10),                                # K2
        month_column=(4, 1), month_count=(5, 1), year=(0, 1),
        header="KPI", ends=("Reviewee",),
        cols={"perspective": 1, "measure": 2, "initiative": 3, "weight": 4,
              "prior": 5, "growth": 6, "fy": 7, "ytd": 8, "actual": 9,
              "score": 10, "weighted": 11, "feed": 12},
        summaries=(("Monthly_Summ", 4, 0, 4),),
        files=("sales_scorecards", "sales_actuals"),
        source="the sales scorecards workbook",
    ),
    # BB_Scorecards - the branch managers. Its macro (Do_Monthly_Summary)
    # puts everybody on the List through BM_Scorecard: C2 the name, C3 the
    # branch; K2 the score, written to Branch_Monthly_Summary. It reads the
    # SAME actuals template as the sales workbook, at the BM's own rows.
    BRANCH_BUSINESS: Spec(
        book=BRANCH_BUSINESS,
        label="branch business",
        marker="BM_Scorecard",
        role_sheets={}, default_sheet="BM_Scorecard",
        list_cols={"pf": 0, "code": 1, "name": 2, "role": None, "branch": 3,
                   "bbm": 8},
        inputs={(1, 2): "name", (2, 2): "branch", (2, 4): "bbm"},
        score=(1, 10),                                # K2
        month_column=(0, 1), month_count=(1, 1), year=(5, 1),
        header="KPI", ends=("Reviewee",),
        cols={"perspective": 1, "measure": 2, "initiative": 3, "weight": 4,
              "prior": 5, "growth": 6, "fy": 7, "ytd": 8, "actual": 9,
              "score": 10, "weighted": 11, "feed": 13},
        summaries=(("Branch_Monthly_Summary", 2, 1, 5),),
        files=("bb_scorecards", "sales_actuals"),
        source="the branch business scorecards workbook",
        title="Branch Manager", role_code="bbm",
    ),
    # 2026_Retail_Back_Office_Scorecards (.xlsm): credit analysts, product
    # managers, sector RMs, trade. Every sheet: E weight, F FY, G YTD
    # (=F*((Constants!B2 - L)/12), L = the List's prorate_new), H actual -
    # typed by the desk ("group numbers") or read off its actuals template
    # through INDIRECT on K - I score, J weighted, the score in I2. The macro
    # types C2 name, E2 role, C3 branch, E3 reports to.
    RETAIL_BO: Spec(
        book=RETAIL_BO,
        label="retail back office",
        marker="RO_COMMERCIAL",
        role_sheets=RBO_ROLE_SHEETS,
        role_codes=RBO_ROLE_CODES,
        list_cols={"pf": 0, "code": 1, "name": 2, "role": 3, "branch": 4,
                   "bbm": 6},
        inputs={(1, 2): "name", (1, 4): "role", (2, 2): "branch", (2, 4): "bbm"},
        score=(1, 8),                                 # I2
        month_column=(0, 1), month_count=(1, 1), year=(4, 1),
        header="KPI", ends=("Reviewee",),
        cols={"perspective": 1, "measure": 2, "initiative": 3, "weight": 4,
              "prior": None, "growth": None, "fy": 5, "ytd": 6, "actual": 7,
              "score": 8, "weighted": 9, "feed": 10},
        summaries=(("Monthly_Summary", 0, 1, 6),),
        # Its Monthly_Summary carries March, April and June, and an October
        # column that is a copy of June (Q checks P = L): only months up to
        # the desk's own run (Constants B2) are its scores.
        summary_upto_run_month=True,
        # The INITIATIVES_* sheets are evaluated with the card, so their
        # month-prorated targets follow the month asked for.
        evaluate_sheets=RBO_INITIATIVE_SHEETS,
        files=("rbo_scorecards", "rbo_actuals"),
        source="the retail back office scorecards workbook",
    ),
    # IB_Scorecards_Template (.xlsm): IB RMs and the Head of IB. Columns: E
    # weight as typed, F the weight the score uses (=E, except where the desk
    # typed another), G/H FY target, I YTD (=H*(Constants!B2/12)), J actual,
    # K score, L weighted, M the template sheet; the score in K2.
    IB: Spec(
        book=IB,
        label="institutional banking",
        marker="HOD_IB",
        role_sheets=IB_ROLE_SHEETS,
        role_codes=IB_ROLE_CODES,
        list_cols={"pf": 0, "code": 1, "name": 2, "role": 3, "branch": 4,
                   "bbm": 6},
        inputs={(1, 2): "name", (1, 4): "role", (2, 2): "branch", (2, 4): "bbm"},
        score=(1, 10),                                # K2
        month_column=(0, 1), month_count=(1, 1), year=(4, 1),
        header="KPI", ends=("Reviewee",),
        cols={"perspective": 1, "measure": 2, "initiative": 3, "weight": 5,
              "prior": None, "growth": None, "fy": 7, "ytd": 8, "actual": 9,
              "score": 10, "weighted": 11, "feed": 12},
        summaries=(("Monthly_Summary", 0, 1, 6),),
        files=("ib_scorecards", "ib_actuals"),
        source="the institutional banking scorecards workbook",
        cap_to_run_month=True,
    ),
    # Master Scorecard - 2026.xlsm (HFDI). Columns: B perspective, C KPI, D
    # measure, E weight, F FY target, G YTD, H actual, I % achievement, J
    # weighted, M the template sheet; the score in J2 (=J23, the Total row).
    # mapping!B4 is the month count, B3 the template column (B4+3), B1 the
    # year. Template rows: A staff_id, B name, E..P January..December.
    HFDI: Spec(
        book=HFDI,
        label="HFDI master",
        marker="Property_Advisor",
        role_sheets=HFDI_ROLE_SHEETS,
        role_codes=HFDI_ROLE_CODES,
        list_cols={"pf": 0, "code": 0, "name": 1, "role": 2, "branch": 3,
                   "bbm": 9},
        active_col=13,
        inputs={(1, 2): "name", (2, 2): "branch"},
        score=(1, 9),                                 # J2
        constants_sheet="mapping",
        month_column=(2, 1), month_count=(3, 1), year=(0, 1),
        header="KPI", ends=("Total", "Staff Signature"),
        cols={"perspective": 1, "measure": 2, "initiative": 3, "weight": 4,
              "prior": None, "growth": None, "fy": 5, "ytd": 6, "actual": 7,
              "score": 8, "weighted": 9, "feed": 12},
        summaries=(("Monthly_Summ", 5, 0, 4),),
        files=("hfdi_scorecards", "hfdi_actuals"),
        source="the HFDI master scorecard workbook",
        template_first_month=4,
        cap_to_run_month=True,
    ),
}

FIRST_MONTH_INDEX = 5


class WorkbookError(Exception):
    """The file is not what it was said to be; the message says why."""


# ─────────────────────────────────────────────────────────────────────────
# Values
# ─────────────────────────────────────────────────────────────────────────

class Err:
    """An Excel error value. Carried, not raised - Excel's IF can step round
    one, and a card with an error on it shows the error."""

    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return self.code

    def __eq__(self, other):
        return isinstance(other, Err) and other.code == self.code

    def __hash__(self):
        return hash(self.code)


NA, DIV0, VALUE, REF, NAME = (Err("#N/A"), Err("#DIV/0!"), Err("#VALUE!"),
                              Err("#REF!"), Err("#NAME?"))
_ERROR_CODES = {0x00: "#NULL!", 0x07: "#DIV/0!", 0x0F: "#VALUE!",
                0x17: "#REF!", 0x1D: "#NAME?", 0x24: "#NUM!", 0x2A: "#N/A"}


def _plain(value):
    """A stored value back into Python: errors were written as {"e": code}."""
    if isinstance(value, dict) and "e" in value:
        return Err(value["e"])
    return value


def _store_value(value):
    if isinstance(value, Err):
        return {"e": value.code}
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return {"e": "#NUM!"}
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


class Rng:
    __slots__ = ("sheet", "r1", "c1", "r2", "c2")

    def __init__(self, sheet, r1, c1, r2, c2):
        self.sheet, self.r1, self.c1, self.r2, self.c2 = sheet, r1, c1, r2, c2


# ─────────────────────────────────────────────────────────────────────────
# Reading the .xlsb: values, and formulas as a token list
# ─────────────────────────────────────────────────────────────────────────

def _signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _tokens(raw, row, col, workbook, ptgs, Formula):
    """pyxlsb2's parsed tokens → our own JSON-able RPN.

    ``row``/``col`` are the cell the formula sits in: a shared formula's
    references are offsets from it.
    """
    from pyxlsb2.ptgs import function_names

    out = []
    for t in Formula.parse(raw)._tokens:
        name = type(t).__name__
        if isinstance(t, (ptgs.NumberPtg, ptgs.IntegerPtg)):
            out.append(["n", float(t.value)])
        elif isinstance(t, ptgs.StringPtg):
            out.append(["n", t.value])
        elif isinstance(t, ptgs.BooleanPtg):
            out.append(["n", bool(t.value)])
        elif isinstance(t, ptgs.ErrorPtg):
            out.append(["n", {"e": _ERROR_CODES.get(t.value, "#N/A")}])
        elif isinstance(t, ptgs.MissArgPtg):
            out.append(["n", None])
        elif isinstance(t, ptgs.RefNPtg):
            r = row + _signed(t.row, 32) if not t.row_rel else t.row
            c = col + _signed(t.col, 14) if not t.col_rel else t.col
            out.append(["r", None, r, c])
        elif isinstance(t, ptgs.AreaNPtg):
            r1 = row + _signed(t.first_row, 32) if not t.first_row_rel else t.first_row
            r2 = row + _signed(t.last_row, 32) if not t.last_row_rel else t.last_row
            c1 = col + _signed(t.first_col, 14) if not t.first_col_rel else t.first_col
            c2 = col + _signed(t.last_col, 14) if not t.last_col_rel else t.last_col
            out.append(["a", None, r1, c1, r2, c2])
        elif isinstance(t, ptgs.Ref3dPtg):
            out.append(["r", _sheet_of(workbook, t.extern_sheet_idx),
                        t.row, t.col])
        elif isinstance(t, ptgs.Area3dPtg):
            out.append(["a", _sheet_of(workbook, t.extern_sheet_idx),
                        t.first_row, t.first_col, t.last_row, t.last_col])
        elif isinstance(t, ptgs.RefPtg):
            out.append(["r", None, t.row, t.col])
        elif isinstance(t, ptgs.AreaPtg):
            out.append(["a", None, t.first_row, t.first_col, t.last_row,
                        t.last_col])
        elif name in _BINARY:
            out.append(["b", _BINARY[name]])
        elif name in _UNARY:
            out.append(["u", _UNARY[name]])
        elif isinstance(t, ptgs.ParenPtg):
            continue
        elif isinstance(t, ptgs.AttrPtg):
            # tAttrSum is SUM of one argument, written compactly; the rest
            # (space, if/goto jumps, volatile) change nothing evaluated
            # eagerly.
            if t.attr_sum:
                out.append(["f", "SUM", 1])
            continue
        elif isinstance(t, ptgs.FuncPtg):
            entry = function_names.get(t.idx, ("#UNKNOWN",))
            if len(entry) < 2:
                raise WorkbookError(f"function {entry[0]} with no fixed "
                                      f"argument count")
            out.append(["f", entry[0], entry[1]])
        elif isinstance(t, ptgs.FuncVarPtg):
            if t.idx == 255:
                # A newer function (_xlfn.CONCAT): its name is the token
                # pushed first among its arguments.
                out.append(["udf", t.argc])
            else:
                out.append(["f", function_names.get(t.idx, ("#UNKNOWN",))[0],
                            t.argc])
        elif isinstance(t, ptgs.NamePtg):
            # A defined name. The cards use one only in their titles; read
            # as Excel reads a name it cannot resolve.
            out.append(["n", {"e": "#NAME?"}])
        elif isinstance(t, ptgs.NameXPtg):
            try:
                label = t.stringify([], workbook)
            except Exception:  # noqa: BLE001
                label = "#NAME"
            out.append(["name", label])
        else:
            raise WorkbookError(f"formula element {name} is not supported")
    return out


_BINARY = {"AddPtg": "+", "SubstractPtg": "-", "MultiplyPtg": "*",
           "DividePtg": "/", "PowerPtg": "^", "ConcatPtg": "&",
           "LessPtg": "<", "LessEqualPtg": "<=", "EqualPtg": "=",
           "GreaterEqualPtg": ">=", "GreaterPtg": ">", "NotEqualPtg": "<>",
           "RangePtg": ":"}
_UNARY = {"UPlusPtg": "+", "UMinusPtg": "-", "PercentPtg": "%"}


def _sheet_of(workbook, extern_idx):
    _link, first, last = workbook.resolve_extern_sheet_id(extern_idx)
    if first == last and first >= 0:
        return workbook.sheets[first].name
    raise WorkbookError("a reference to another workbook")


def _read_sheet(workbook, name, with_formulas):
    """→ {"grid": [[value, …], …], "f": {"r,c": tokens}}."""
    from pyxlsb2 import ptgs, recordtypes as rt
    from pyxlsb2.formula import Formula
    from pyxlsb2.recordreader import RecordReader
    from pyxlsb2.records import BaseRecord

    class _Raw(BaseRecord):
        @classmethod
        def read(cls, reader, rectype, reclen):
            r = cls()
            r.data = reader.read(reclen)
            return r

    RecordReader._records[427] = _Raw  # BrtShrFmla - the shared formulas
    RecordReader._records[426] = _Raw  # BrtArrFmla - the array formulas

    sheet = workbook.get_sheet_by_name(name)
    sheet._fp.seek(sheet._data_offset, os.SEEK_SET)
    cells, shared, row = {}, [], -1
    arrays = set()
    for rectype, rec in RecordReader(sheet._fp):
        if rectype == rt.ROW_HDR:
            row = rec.r
        elif rectype in (426, 427):
            # The range, then (array formulas only) one flags byte, then the
            # formula. Both are reached from their cells through a PtgExp.
            r1, r2, c1, c2 = struct.unpack_from("<iiii", rec.data, 0)
            at = 17 if rectype == 426 else 16
            cce = struct.unpack_from("<i", rec.data, at)[0]
            shared.append(((r1, r2, c1, c2),
                           rec.data[at + 4:at + 4 + cce]))
            if rectype == 426:
                arrays.add((r1, r2, c1, c2))
        elif rt.CELL_BLANK <= rectype <= rt.FMLA_ERROR and rec.c is not None:
            value = rec.v
            if rectype == rt.CELL_ISST and isinstance(value, int):
                strings = workbook.stringtable._strings
                value = strings[value] if 0 <= value < len(strings) else value
            elif type(value).__name__ == "ErrorValue":
                value = {"e": "#N/A"}
            cells[(row, rec.c)] = (value, rec.f)
        elif rectype == rt.END_SHEET_DATA:
            break

    height = max((r for r, _ in cells), default=-1) + 1
    width = max((c for _, c in cells), default=-1) + 1
    grid = [[None] * width for _ in range(height)]
    formulas, problems = {}, []
    for (r, c), (value, raw) in cells.items():
        grid[r][c] = _store_value(value) if not isinstance(value, dict) else value
        if not with_formulas or not raw:
            continue
        try:
            first = Formula.parse(raw)._tokens
            array = False
            if first and isinstance(first[0], ptgs.ExpPtg):
                found = next(((box, data) for box, data in shared
                              if box[0] <= r <= box[1]
                              and box[2] <= c <= box[3]), None)
                if found is None:
                    raise WorkbookError("its shared formula is missing")
                array = found[0] in arrays
                raw = found[1]
            tokens = _tokens(raw, r, c, workbook, ptgs, Formula)
            # An array formula ({=…}) evaluates its ranges whole.
            formulas[f"{r},{c}"] = [["array"]] + tokens if array else tokens
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}!{_a1(r, c)}: {exc}")
    return {"grid": grid, "f": formulas}, problems


def _a1(row, col):
    letters, n = "", col + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row + 1}"


def read_scorecards(stream):
    """The scorecards .xlsb → plain data (see :func:`compute`)."""
    with tempfile.NamedTemporaryFile(suffix=".xlsb", delete=False) as tmp:
        for chunk in (stream.chunks() if hasattr(stream, "chunks")
                      else [stream.read()]):
            tmp.write(chunk)
        path = tmp.name
    try:
        return _read_scorecards_path(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _open_xlsb(path):
    """pyxlsb2's workbook, tolerant of defined names it cannot print.

    It renders every defined name's formula on open, and one that points into
    another workbook (the sales workbook has several) raises - taking the
    whole file down with it. A name's text is never needed here.
    """
    import pyxlsb2.workbook as workbook_module
    from pyxlsb2 import open_workbook
    from pyxlsb2.formula import Formula

    class _Tolerant(Formula):
        def stringify(self, workbook):
            try:
                return super().stringify(workbook)
            except Exception:  # noqa: BLE001
                return ""

    workbook_module.Formula = _Tolerant
    return open_workbook(path)


def _read_scorecards_path(path):
    open_workbook = _open_xlsb

    try:
        workbook = open_workbook(path)
    except Exception as exc:  # noqa: BLE001
        raise WorkbookError(f"that is not an .xlsb workbook ({exc})")
    with workbook:
        names = [s.name for s in workbook.sheets]
        spec = next((s for s in SPECS.values()
                     if "List" in names and s.marker in names), None)
        if spec is None:
            raise WorkbookError(
                "this is neither scorecards workbook - it has no List with a "
                "TELLER_SCORECARD (back office) or Business_Banking (sales) "
                "sheet beside it")
        book = {"book": spec.book, "cards": {}, "tables": {}, "problems": []}
        wanted = set()
        for sheet in sorted(set(spec.role_sheets.values())
                            | ({spec.default_sheet}
                               if getattr(spec, "default_sheet", None)
                               else set())):
            if sheet not in names:
                book["problems"].append(f"{sheet} is not in the workbook")
                continue
            data, problems = _read_sheet(workbook, sheet, True)
            book["cards"][sheet] = data
            book["problems"] += problems
            for tokens in data["f"].values():
                for t in tokens:
                    if t[0] in ("r", "a") and t[1]:
                        wanted.add(t[1])
        summaries = {s[0] for s in spec.summaries}
        for sheet in sorted((wanted | {"List", "Constants"} | summaries)
                            - set(book["cards"])):
            if sheet in names:
                book["tables"][sheet] = _read_sheet(workbook, sheet,
                                                    False)[0]["grid"]
    return book


# ─────────────────────────────────────────────────────────────────────────
# Formulas written as text (.xlsx / .xlsm) → the same RPN
# ─────────────────────────────────────────────────────────────────────────

#: Excel's operator precedence, highest first: negation, percent, power,
#: multiply/divide, add/subtract, join, compare. Negation binds tighter than
#: power (=-2^2 is 4).
_PRECEDENCE = {"u": 7, "^": 5, "*": 4, "/": 4, "+": 3, "-": 3, "&": 2,
               "=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, ":": 8}
_XL_ERRORS = {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!",
              "#N/A"}
_REF = re.compile(r"^\$?([A-Za-z]{1,3})?\$?(\d+)?(?::\$?([A-Za-z]{1,3})?\$?(\d+)?)?$")


def _ref_token(text):
    """``'Summary Allocation'!$BJ:$BJ``, ``$C$2``, ``E6:E9``, ``1:8`` → an
    "r" or "a" token as the .xlsb reader writes them; a reference into
    another workbook is #REF! (the .xlsb reader refuses those too), and a
    defined name #NAME? (as the .xlsb reader reads one)."""
    sheet, ref = None, text
    if "!" in text:
        sheet, ref = text.rsplit("!", 1)
        if sheet.startswith("'") and sheet.endswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
        if sheet.startswith("["):
            return ["n", {"e": "#REF!"}]
    m = _REF.match(ref)
    if not m or not any(m.groups()):
        return ["n", {"e": "#NAME?"}]
    c1, r1, c2, r2 = m.groups()
    if ":" not in ref:
        if not (c1 and r1):
            return ["n", {"e": "#NAME?"}]
        return ["r", sheet, int(r1) - 1, _column_index(c1)]
    col1 = _column_index(c1) if c1 else 0
    col2 = _column_index(c2) if c2 else 16383
    row1 = int(r1) - 1 if r1 else 0
    row2 = int(r2) - 1 if r2 else 1048575
    return ["a", sheet, row1, col1, row2, col2]


def formula_tokens(text):
    """An Excel formula as text (``=SUMIFS(...)``) → our RPN, the list the
    :class:`Evaluator` runs - the same tokens :func:`_tokens` makes from an
    .xlsb. Raises WorkbookError on an element the evaluator has no meaning
    for (array constants)."""
    from openpyxl.formula.tokenizer import Token, Tokenizer

    out, ops, argc = [], [], []
    prev = None

    def pop_until_open():
        while ops and ops[-1][0] not in ("(", "func"):
            out.append(ops.pop()[1])

    for tok in Tokenizer(text).items:
        kind, sub, value = tok.type, tok.subtype, tok.value
        if kind == Token.WSPACE:
            continue
        if kind == Token.OPERAND:
            if sub == Token.NUMBER:
                out.append(["n", float(value)])
            elif sub == Token.TEXT:
                out.append(["n", value[1:-1].replace('""', '"')])
            elif sub == Token.LOGICAL:
                out.append(["n", value.upper() == "TRUE"])
            elif sub == Token.ERROR:
                out.append(["n", {"e": value.upper()}])
            else:
                out.append(_ref_token(value))
        elif kind == Token.FUNC and sub == Token.OPEN:
            name = value[:-1].upper()
            for prefix in ("_XLFN._XLWS.", "_XLFN."):
                if name.startswith(prefix):
                    name = name[len(prefix):]
            ops.append(("func", name))
            argc.append(0)
        elif kind == Token.FUNC and sub == Token.CLOSE:
            if prev is not None and prev.type == Token.SEP:
                out.append(["n", None])          # f(a,) - a missing argument
            pop_until_open()
            _, name = ops.pop()
            count = argc.pop()
            empty = prev is not None and prev.type == Token.FUNC and prev.subtype == Token.OPEN
            out.append(["f", name, 0 if empty else count + 1])
        elif kind == Token.SEP and sub == Token.ARG:
            if prev is not None and (prev.type == Token.SEP or (
                    prev.type == Token.FUNC and prev.subtype == Token.OPEN)):
                out.append(["n", None])          # f(,b) / f(a,,c)
            pop_until_open()
            if argc:
                argc[-1] += 1
        elif kind == Token.PAREN and sub == Token.OPEN:
            ops.append(("(", None))
        elif kind == Token.PAREN and sub == Token.CLOSE:
            pop_until_open()
            if ops and ops[-1][0] == "(":
                ops.pop()
        elif kind == Token.OP_PRE:
            ops.append(("op", ["u", value], _PRECEDENCE["u"], True))
        elif kind == Token.OP_POST:
            out.append(["u", "%"])
        elif kind == Token.OP_IN:
            p = _PRECEDENCE.get(value)
            if p is None:
                raise WorkbookError(f"operator {value!r} is not supported")
            while (ops and ops[-1][0] == "op"
                   and (ops[-1][2] > p or (ops[-1][2] == p and not ops[-1][3]))):
                out.append(ops.pop()[1])
            ops.append(("op", ["b", value], p, False))
        else:
            raise WorkbookError(f"formula element {value!r} is not supported")
        prev = tok
    while ops:
        item = ops.pop()
        if item[0] != "op":
            raise WorkbookError("unbalanced brackets")
        out.append(item[1])
    return out


def _xl_value(v):
    """A cell's cached value as the .xlsb reader stores it: an error as
    {"e": code}."""
    if isinstance(v, str) and v.strip() in _XL_ERRORS:
        return {"e": v.strip()}
    return _store_value(v)


def _read_xl_sheet(formulas_ws, values_ws, with_formulas=True, rewrite=None):
    """One openpyxl sheet (opened with and without data_only) →
    {"grid": [[value, ...]], "f": {"r,c": tokens}}, and the problems.
    ``rewrite``: a function applied to each formula's text first (the HFDI
    workbook's table references become plain ranges)."""
    grid, f, problems = [], {}, []
    for r, row in enumerate(values_ws.iter_rows(values_only=True)):
        values = [_xl_value(v) for v in row]
        while values and values[-1] in (None, ""):
            values.pop()
        grid.append(values)
    while grid and not grid[-1]:
        grid.pop()
    if with_formulas:
        for row in formulas_ws.iter_rows():
            for c in row:
                v = c.value
                text = getattr(v, "text", None)          # an array formula
                array = text is not None
                if text is None:
                    text = v if isinstance(v, str) and v.startswith("=") else None
                if not text:
                    continue
                if rewrite is not None:
                    text = rewrite(text)
                try:
                    tokens = formula_tokens(text)
                    key = f"{c.row - 1},{c.column - 1}"
                    f[key] = [["array"]] + tokens if array else tokens
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{formulas_ws.title}!{c.coordinate}: {exc}")
    return {"grid": grid, "f": f}, problems


# ─────────────────────────────────────────────────────────────────────────
# The mortgage business probation workbook
# ─────────────────────────────────────────────────────────────────────────

#: "Portfolio Management - Mortgage Business Probation scorecards" (.xlsm):
#: the desk's card for a Mortgage Business ARM on probation. Its macro
#: (scorecards_generation) types every "Mortgage Business ARM" on its List
#: into the Mortgage_ARM sheet; the joiners Roy Gitonga (from August),
#: Claudine Odhiambo, Monicah Mwaniki and Dorine Oseko (from September) are
#: on the sales workbook's List but not on its Summary Allocation, so the
#: sales card gave them 0 on every target and no score. Their targets are
#: on this workbook's Summary Allocation - probation sized (disbursements
#: 12m a month for 3 months, loan approvals 20m a month, CASA and new
#: customers 2 a month over the 6 months, training 48 x 6/12 = 24 hours) -
#: and its Mortgage_ARM card weighs the lines differently (Loan Approvals
#: 30%, the two mortgage lines 5% each, no PAR).
PROBATION_KIND = "mortgage_probation"
PROBATION_ROLE_SHEETS = {"Mortgage Business ARM": "Mortgage_ARM"}


def read_probation(stream):
    """The probation workbook → {"year", "cards": {sheet: card},
    "allocation": Summary Allocation grid, "list": List grid, "problems"}.

    The card sheet keeps its formulas (run by the same :class:`Evaluator`
    over the sales workbook's Constants and List, which are laid out the same
    way); Summary Allocation and the List keep their values."""
    from openpyxl import load_workbook

    data = stream.read() if hasattr(stream, "read") else stream
    import io

    try:
        wf = load_workbook(io.BytesIO(data), read_only=True, keep_vba=False)
        wv = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise WorkbookError(f"that is not an .xlsm/.xlsx workbook ({exc})")
    try:
        wanted = set(PROBATION_ROLE_SHEETS.values()) | {"Summary Allocation", "List",
                                                        "Constants"}
        missing = sorted(wanted - set(wf.sheetnames))
        if missing:
            raise WorkbookError("this is not the mortgage probation workbook - it "
                                "has no " + ", ".join(missing) + " sheet")
        out = {"cards": {}, "problems": []}
        for sheet in sorted(set(PROBATION_ROLE_SHEETS.values())):
            card, problems = _read_xl_sheet(wf[sheet], wv[sheet])
            out["cards"][sheet] = card
            out["problems"] += problems
        for sheet, key in (("Summary Allocation", "allocation"), ("List", "list"),
                           ("Constants", "constants")):
            out[key] = _read_xl_sheet(wf[sheet], wv[sheet], False)[0]["grid"]
    finally:
        wf.close()
        wv.close()
    year = _at(out["constants"], 0, 1)
    out["year"] = int(year) if _num(year) and 2000 < year < 2100 else datetime.date.today().year
    return out


def is_probation_workbook(data):
    """Has this .xlsx/.xlsm the probation workbook's sheets?"""
    import io

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
    except Exception:  # noqa: BLE001
        return False
    try:
        names = set(wb.sheetnames)
    finally:
        wb.close()
    return set(PROBATION_ROLE_SHEETS.values()) <= names and "Summary Allocation" in names


# ─────────────────────────────────────────────────────────────────────────
# The Retail Back Office workbook
# ─────────────────────────────────────────────────────────────────────────

def is_retail_bo_workbook(data):
    """Has this .xlsx/.xlsm the Retail Back Office workbook's sheets?"""
    import io

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
    except Exception:  # noqa: BLE001
        return False
    try:
        names = set(wb.sheetnames)
        if not {"List", "Constants", "Monthly_Summary"} <= names:
            return False
        # Its cards read the retail back office actuals template by name -
        # whatever the role sheets are called this year.
        for sheet in wb.worksheets:
            if sheet.title in RBO_TABLE_SHEETS:
                continue
            for row in sheet.iter_rows(max_row=60, max_col=12, values_only=True):
                if any(isinstance(v, str) and RBO_TEMPLATE_MARK in v.lower() for v in row):
                    return True
        return False
    finally:
        wb.close()


def read_retail_bo(stream):
    """The Retail Back Office workbook → (book, desk_actuals).

    ``book`` is shaped as :func:`read_scorecards` shapes an .xlsb: each role
    sheet and INITIATIVES_* sheet keeps its formulas, every other sheet its
    values. ``desk_actuals`` is the desk's own figures in its template's
    layout (PF, code, name, role, branch, zone, January..December), for the
    month the workbook was last run (Constants B2): the cached value of each
    line that reads the template, for the person whose card each sheet was
    last run for. Its actuals template (2026_Actual_Template_Retail_Back_
    office.xlsx) is not loaded anywhere, so for everybody else those lines
    have no figure until a feed gives one."""
    import io

    from openpyxl import load_workbook

    data = stream.read() if hasattr(stream, "read") else stream
    try:
        wf = load_workbook(io.BytesIO(data), read_only=True, keep_vba=False)
        wv = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise WorkbookError(f"that is not an .xlsm/.xlsx workbook ({exc})")
    try:
        names = list(wf.sheetnames)
        missing = sorted(set(RBO_TABLE_SHEETS) - set(names))
        book = {"book": RETAIL_BO, "cards": {}, "tables": {}, "problems": []}
        if missing:
            book["problems"].append("not in the workbook: " + ", ".join(missing))
        # Every sheet but the List, Constants and the summary keeps its
        # formulas; which of them are cards, and which are evaluated with a
        # card, the workbook itself says below.
        for sheet in names:
            if sheet in RBO_TABLE_SHEETS:
                book["tables"][sheet] = _read_xl_sheet(wf[sheet], wv[sheet],
                                                       False)[0]["grid"]
                continue
            card, problems = _read_xl_sheet(wf[sheet], wv[sheet])
            book["cards"][sheet] = card
            book["tables"][sheet] = card["grid"]
            book["problems"] += problems
    finally:
        wf.close()
        wv.close()
    _rbo_layout(book)
    return book, rbo_desk_actuals(book)


#: The workbook's own tables - read as values, never evaluated.
RBO_TABLE_SHEETS = ("List", "Constants", "Monthly_Summary")
RBO_TEMPLATE_MARK = "actual_template_retail_back_office"


def _rbo_layout(book):
    """Which sheets are cards and for which role, and which sheets the cards
    evaluate - read off the workbook, so a new or renamed role sheet needs no
    code (asked 26 Nov 2026: "no code changes when KPIs change").

    A card is a sheet with the "KPI" header and a role in E2 - the cell the
    desk's macro types the role into (RO_COMMERCIAL's E2 is "RELATIONSHIP
    OFFICER - COMMERCIAL"). A sheet a card's formulas reach (INITIATIVES_*) is
    evaluated with it. Everything else keeps its values only."""
    spec = SPECS[RETAIL_BO]
    roles, cards = {}, set()
    for sheet, card in book["cards"].items():
        grid = card["grid"]
        header = any(isinstance(v, str) and v.strip() == spec.header
                     for row in grid[:8] for v in row)
        role = _txt(_at(grid, 1, 4)).strip()                    # E2
        if header and role and card["f"].get(f"{spec.score[0]},{spec.score[1]}"):
            if role.upper() in {r.upper() for r in roles}:
                book["problems"].append(f"two card sheets carry the role {role!r}: "
                                        f"{roles[next(r for r in roles if r.upper() == role.upper())]} "
                                        f"and {sheet} - the first is used")
                continue
            roles[role] = sheet
            cards.add(sheet)
    reached = set()
    for sheet in cards:
        for tokens in book["cards"][sheet]["f"].values():
            for t in tokens:
                if t[0] in ("r", "a") and t[1] and not str(t[1]).startswith("@"):
                    reached.add(t[1])
    book["role_sheets"] = roles
    book["evaluate_sheets"] = sorted((reached & set(book["cards"])) - cards
                                     - set(RBO_TABLE_SHEETS))
    # Sheets neither a card nor reached by one are not needed as formulas.
    for sheet in list(book["cards"]):
        if sheet not in cards and sheet not in book["evaluate_sheets"]:
            book["cards"].pop(sheet)


#: Retail back office people's own card files (Sarah Nzeli_H1_Jun_2026_
#: Scorecard.xlsx): {CODE: {"month": "YYYY-MM", "name", "file", "figures":
#: {feed: actual}}}. A line whose return has no row for the person (the CX
#: CRM logs, the CX survey's contactability) shows the figure the desk put on
#: their own card instead of nothing.
RBO_CARD_FIGURES = "rbo_card_figures"
_PERIOD_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def read_rbo_person_card(data):
    """One person's own RBO card file → {"name", "role", "month", "figures"},
    or None when the file is not one. The card's K column names each line's
    template sheet (its feed), H is the actual, C2 the name, E2 the role, C4
    the review period ("H1_Jun_2026")."""
    import io

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return None
    try:
        if len(wb.sheetnames) != 1:
            return None
        rows = [list(r) for r in wb.worksheets[0].iter_rows(max_row=60, max_col=12,
                                                             values_only=True)]
    finally:
        wb.close()
    if len(rows) < 6:
        return None
    at = lambda r, c: rows[r][c] if r < len(rows) and c < len(rows[r]) else None  # noqa: E731
    role = _txt(at(1, 4)).strip()
    if role.upper() not in {k.upper() for k in RBO_ROLE_SHEETS}:
        return None
    m = re.search(r"([A-Za-z]{3})[A-Za-z]*_(\d{4})", _txt(at(3, 2)))
    if not m or m.group(1).lower() not in _PERIOD_MONTHS:
        return None
    figures = {}
    for r in range(5, len(rows)):
        feed, actual = _txt(at(r, 10)).strip(), at(r, 7)
        if feed and _num(actual) and not isinstance(actual, bool):
            figures[feed] = float(actual)
    return {"name": _txt(at(1, 2)).strip(), "role": role, "figures": figures,
            "month": f"{m.group(2)}-{_PERIOD_MONTHS[m.group(1).lower()]:02d}"}


def rbo_card_figure(code, feed):
    """(value, "YYYY-MM") off the person's own loaded card for this feed, or
    (None, None)."""
    entry = (saved(RBO_CARD_FIGURES) or {}).get((code or "").strip().upper()) or {}
    value = (entry.get("figures") or {}).get(feed)
    return (value, entry.get("month")) if _num(value) else (None, None)


def rbo_role_sheets(book):
    """{List role: card sheet} - the workbook's own, else the macro's."""
    return book.get("role_sheets") or RBO_ROLE_SHEETS


def rbo_role_code(sheet):
    return "rbo_" + str(sheet or "").lower()


def rbo_run_month(book):
    """The month the desk last ran the workbook for (Constants B2) → int."""
    v = _at(book["tables"].get("Constants") or [], *SPECS[RETAIL_BO].month_count)
    return int(v) if _num(v) and 1 <= v <= 12 else None


def _rbo_person_row(book, name):
    """The List row naming ``name`` → [pf, code, name, role, branch, zone]."""
    for row in (book["tables"].get("List") or [])[1:]:
        if len(row) > 2 and _txt(row[2]).strip().lower() == _txt(name).strip().lower():
            return [row[i] if i < len(row) else None for i in range(6)]
    return None


def rbo_desk_actuals(book):
    """The desk's own figures, read off the cards as last run (see
    :func:`read_retail_bo`) → {template sheet: rows}."""
    spec = SPECS[RETAIL_BO]
    month = rbo_run_month(book)
    out = {}
    if month is None:
        return out
    col = spec.cols
    for sheet in rbo_role_sheets(book).values():
        card = book["cards"].get(sheet)
        if not card:
            continue
        person = _rbo_person_row(book, _at(card["grid"], 1, 2))
        if person is None:
            continue
        for key, tokens in card["f"].items():
            r, c = (int(x) for x in key.split(","))
            if c != col["actual"] or not any(
                    t[0] == "f" and t[1] == "INDIRECT" for t in tokens):
                continue
            feed, value = _txt(_at(card["grid"], r, col["feed"])), _at(card["grid"], r, c)
            if not feed or not _num(value) or isinstance(value, bool):
                continue
            rows = out.setdefault(feed, [["staff_pf", "sales_code", "staff_name",
                                          "staff_role", "staff_branch", "staff_zone"]
                                         + [None] * 12])
            row = next((x for x in rows[1:] if x[2] == person[2]), None)
            if row is None:
                row = list(person) + [None] * 12
                rows.append(row)
            row[6 + month - 1] = float(value)
    return out


def rbo_proof(book, actuals):
    """Each role sheet's card as the desk last ran it, recomputed → [{sheet,
    name, desk, computed, same}]. The desk's own figures go in, so every
    card must come back to the score cached on it."""
    spec = SPECS[RETAIL_BO]
    month = rbo_run_month(book)
    people = {h.name.strip().lower(): h for h in holders(book, keep_off=True)}
    out = []
    for sheet in rbo_role_sheets(book).values():
        card = book["cards"].get(sheet)
        if not card or month is None:
            continue
        name = _txt(_at(card["grid"], 1, 2))
        desk = _plain(_at(card["grid"], *spec.score))
        holder = people.get(name.strip().lower())
        if holder is None:
            out.append({"sheet": sheet, "name": name, "desk": desk,
                        "computed": None, "same": False,
                        "why": "not on the List"})
            continue
        import copy as _copy

        h = _copy.copy(holder)
        h.sheet = sheet
        total = compute(book, actuals, h, month)["total"]
        same = _num(total) and _num(desk) and abs(total - desk) < 1e-9
        out.append({"sheet": sheet, "name": name, "desk": desk,
                    "computed": total, "same": bool(same)})
    return out


def is_ib_workbook(data):
    """Has this .xlsm the Institutional Banking scorecards workbook's
    sheets, its cards naming the IB actuals template?"""
    import io

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
    except Exception:  # noqa: BLE001
        return False
    try:
        names = set(wb.sheetnames)
        if not {"List", "Constants", "Monthly_Summary"} <= names:
            return False
        for sheet in IB_ROLE_SHEETS.values():
            if sheet not in names:
                continue
            for row in wb[sheet].iter_rows(max_row=40, max_col=14, values_only=True):
                if any(isinstance(v, str) and IB_TEMPLATE_MARK in v.lower() for v in row):
                    return True
        return False
    finally:
        wb.close()


def read_ib(stream):
    """The Institutional Banking scorecards workbook → book, shaped as
    :func:`read_scorecards` shapes an .xlsb: the role cards keep their
    formulas (and any sheet a card's formulas reach), the List, Constants,
    Monthly_Summary and mapping their values."""
    import io

    from openpyxl import load_workbook

    data = stream.read() if hasattr(stream, "read") else stream
    try:
        wf = load_workbook(io.BytesIO(data), read_only=True, keep_vba=False)
        wv = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise WorkbookError(f"that is not an .xlsm/.xlsx workbook ({exc})")
    try:
        names = list(wf.sheetnames)
        book = {"book": IB, "cards": {}, "tables": {}, "problems": []}
        missing = sorted((set(IB_TABLE_SHEETS) - {"mapping"}
                          | set(IB_ROLE_SHEETS.values())) - set(names))
        if missing:
            book["problems"].append("not in the workbook: " + ", ".join(missing))
        for sheet in names:
            if sheet in IB_TABLE_SHEETS:
                book["tables"][sheet] = _read_xl_sheet(wf[sheet], wv[sheet],
                                                       False)[0]["grid"]
                continue
            card, problems = _read_xl_sheet(wf[sheet], wv[sheet])
            book["cards"][sheet] = card
            book["tables"][sheet] = card["grid"]
            book["problems"] += problems
    finally:
        wf.close()
        wv.close()
    cards = {s for s in IB_ROLE_SHEETS.values() if s in book["cards"]}
    reached = set()
    for sheet in cards:
        for tokens in book["cards"][sheet]["f"].values():
            for t in tokens:
                if t[0] in ("r", "a") and t[1] and not str(t[1]).startswith("@"):
                    reached.add(t[1])
    book["evaluate_sheets"] = sorted((reached & set(book["cards"])) - cards
                                     - set(IB_TABLE_SHEETS))
    for sheet in list(book["cards"]):
        if sheet not in cards and sheet not in book["evaluate_sheets"]:
            book["cards"].pop(sheet)
    return book


#: The IB template's account sheet, kept when the template is loaded on the
#: screen: what ib_feed_probe measures the warehouse against.
IB_PORTFOLIO_KIND = "ib_portfolio"


def ib_portfolio(data):
    """The IB actuals template's Portfolio sheet → grid (values), or None."""
    import io

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return None
    try:
        if "Portfolio" not in wb.sheetnames:
            return None
        grid, empty = [], 0
        for row in wb["Portfolio"].iter_rows(values_only=True):
            values = [_store_value(v) for v in row]
            while values and values[-1] in (None, ""):
                values.pop()
            grid.append(values)
            empty = 0 if values else empty + 1
            if empty >= 1000:
                break
        while grid and not grid[-1]:
            grid.pop()
        return grid
    finally:
        wb.close()


def ib_run_month(book):
    """The month the desk last ran the workbook for (its month-count cell:
    IB Constants B2, HFDI mapping B4)."""
    spec = spec_of(book)
    grid = (book["tables"].get(getattr(spec, "constants_sheet", "Constants"))
            or book["tables"].get("Constants") or [])
    v = _at(grid, *spec.month_count)
    return int(v) if _num(v) and 1 <= v <= 12 else None


def is_hfdi_workbook(data):
    """Has this .xlsm the HFDI Master Scorecard's sheets?"""
    import io

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
    except Exception:  # noqa: BLE001
        return False
    try:
        names = set(wb.sheetnames)
        return ({"staff_list", "mapping", "Monthly_Summ", "Property_Advisor"} <= names)
    finally:
        wb.close()


def _table_ranges(wb):
    """{table name (lower): "'sheet'!A2:R44"} - each Excel table's data rows,
    which ``name[]`` means in a formula."""
    from openpyxl.utils import range_boundaries, get_column_letter

    out = {}
    for ws in wb.worksheets:
        for name, table in ws.tables.items():
            ref = table if isinstance(table, str) else table.ref
            c1, r1, c2, r2 = range_boundaries(ref)
            head = 1 if (getattr(table, "headerRowCount", 1) in (None, 1)) else 0
            tail = int(getattr(table, "totalsRowCount", 0) or 0)
            out[name.lower()] = (f"'{ws.title}'!{get_column_letter(c1)}{r1 + head}:"
                                 f"{get_column_letter(c2)}{r2 - tail}")
    return out


def read_hfdi(stream):
    """The HFDI Master Scorecard → book, shaped as the other books: the
    macro's ten role cards keep their formulas (table references such as
    sales_roles_targets[] turned into the table's own range), staff_list,
    targets, mapping and Monthly_Summ their values. staff_list is also the
    List and mapping also Constants, as the engine names them."""
    import io

    from openpyxl import load_workbook

    data = stream.read() if hasattr(stream, "read") else stream
    try:
        wf = load_workbook(io.BytesIO(data), keep_vba=False)
        wv = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise WorkbookError(f"that is not an .xlsm/.xlsx workbook ({exc})")
    tables = _table_ranges(wf)
    unknown = set()

    def rewrite(text):
        def one(m):
            name = m.group(1).lower()
            if name in tables:
                return tables[name]
            unknown.add(m.group(0))
            return m.group(0)
        return re.sub(r"\b([A-Za-z_][A-Za-z0-9_.]*)\[\]", one, text)

    book = {"book": HFDI, "cards": {}, "tables": {}, "problems": []}
    names = list(wf.sheetnames)
    missing = sorted(set(HFDI_TABLE_SHEETS) - set(names))
    if missing:
        book["problems"].append("not in the workbook: " + ", ".join(missing))
    for sheet in names:
        if sheet in HFDI_TABLE_SHEETS:
            book["tables"][sheet] = _read_xl_sheet(wf[sheet], wv[sheet], False)[0]["grid"]
        elif sheet in HFDI_ROLE_SHEETS.values():
            card, problems = _read_xl_sheet(wf[sheet], wv[sheet], rewrite=rewrite)
            book["cards"][sheet] = card
            book["tables"][sheet] = card["grid"]
            book["problems"] += problems
    if unknown:
        book["problems"].append("table references not found: " + ", ".join(sorted(unknown)))
    book["tables"]["List"] = book["tables"].get("staff_list", [])
    book["tables"]["Constants"] = book["tables"].get("mapping", [])
    return book


def ib_proof(book, actuals):
    """Every IB card holder's card for the month the desk last ran, from the
    workbook's formulas over the template → [{sales_code, name, sheet, desk,
    computed, same}]. ``desk`` is the score its macro wrote on
    Monthly_Summary for that month - so the cards are proven against what
    the desk itself recorded, person by person."""
    month = ib_run_month(book)
    recorded = recorded_scores(book)
    out = []
    for holder in holders(book, keep_off=True):
        if holder.sheet not in book.get("cards", {}) or month is None:
            continue
        desk = recorded.get((holder.sales_code, month))
        total = compute(book, actuals, holder, month)["total"]
        same = _num(total) and _num(desk) and abs(total - desk) < 1e-9
        out.append({"sales_code": holder.sales_code, "name": holder.name,
                    "sheet": holder.sheet, "desk": desk, "computed": total,
                    "same": bool(same),
                    "why": "" if desk is not None else
                    f"no score on Monthly_Summary for month {month}"})
    return out


def _allocation_columns(card):
    """The Summary Allocation columns a card's formulas read."""
    cols = set()
    for tokens in card["f"].values():
        for t in tokens:
            if t[0] in ("r", "a") and t[1] == "Summary Allocation":
                cols.update(range(t[3], (t[5] if t[0] == "a" else t[3]) + 1))
    return cols


def probation_people(book, probation):
    """{SALES CODE: probation card sheet} - who the desk scores on the
    probation workbook: a role its macro puts on a probation card, on its
    List and not marked "left", on the sales List, and NOT on the sales
    Summary Allocation (where the desk allocates everybody it scores on the
    sales card). Somebody the desk later puts on the sales Summary
    Allocation goes back to the sales card."""
    spec = SPECS[SALES]
    sales_list = book["tables"].get("List") or []
    on_list = {str(r[0] or "").strip().upper() for r in sales_list[1:] if r}
    alloc = book["tables"].get(_sheet_named(book["tables"], "Summary Allocation") or "") or []
    allocated = {str(r[1] or "").strip().upper() for r in alloc if len(r) > 1}
    out = {}
    for row in (probation.get("list") or [])[1:]:
        if len(row) < 4:
            continue
        code = str(row[spec.list_cols["code"]] or "").strip().upper()
        role = str(row[spec.list_cols["role"]] or "").strip()
        branch = str(row[spec.list_cols["branch"]] or "").strip().lower()
        sheet = PROBATION_ROLE_SHEETS.get(role)
        if (code and sheet and branch != "left" and code in on_list
                and code not in allocated and sheet in probation.get("cards", {})):
            out[code] = sheet
    return out


def probation_start(book, holder):
    """The sales List's prorate_new for this person (column I, which the
    card's column O looks up) → int; 0 when blank."""
    row = _at_row(book["tables"].get("List") or [], holder.row)
    v = row[8] if len(row) > 8 else None
    return int(v) if _num(v) and 0 < v < 12 else 0


def _at_row(grid, r):
    return grid[r] if 0 <= r < len(grid) and grid[r] else []


#: The template sheet the Loan Approvals line reads - the sales actuals
#: template's own Loan_Approvals sheet (C:R, a running total). Months the
#: desk has not filled take the iApply loan trail's figure
#: (loan_applications.accepted_offers): in compute, and on the live card as
#: the desk's year to date plus what was accepted since.
LOAN_APPROVALS_FEED = "Loan_Approvals"


def complete_loan_approvals(card):
    """The Mortgage_ARM card with its Loan Approvals row scored → card.

    The desk's row 8 ("Loan Approvals (Subject to paid commitment fees &
    offer letter acceptance)", 30%) has only its 2026 FY Target (H8); YTD
    target, actual, score and weighted score are blank, so 30% of every
    probation card counted nothing. Where those cells are blank they get the
    formulas the card's own money line beside it (row 7) uses - YTD target
    prorated from the joining month, actual read by name, score capped at
    120%, weighted - and column M names :data:`LOAN_APPROVALS_FEED`. A row the
    desk completes itself is left exactly as the desk wrote it."""
    grid, f = card["grid"], card["f"]
    for r, row in enumerate(grid):
        text = row[2] if row and len(row) > 2 else None
        if not (isinstance(text, str) and _key(text).startswith("loanapprovals")):
            continue
        if any(f.get(f"{r},{c}") or _at(grid, r, c) not in (None, "")
               for c in (8, 9, 10, 11)):
            return card
        n = r + 1
        cells = {
            8: f"=IFERROR(+H{n}/((12-O{n})/(Constants!$B$6-O{n})),0)",
            9: (f'=+VLOOKUP($C$2,INDIRECT("[2026_Actual_Template.xlsx]"&$M{n}'
                f'&"!" &"$C:$R"),$N$1,0)'),
            10: f"=IFERROR(IF(J{n}/I{n}>1.2,1.2,J{n}/I{n}),0)",
            11: f"=IF(K{n}*E{n}<0,0,K{n}*E{n})",
            13: f"=Constants!$B$6-O{n}",
            14: "=VLOOKUP($C$2,List!B:I,8,0)",
        }
        out = dict(card)
        out["f"] = dict(f)
        out["grid"] = [list(x) if i == r else x for i, x in enumerate(grid)]
        line = out["grid"][r]
        while len(line) < 15:
            line.append(None)
        line[12] = LOAN_APPROVALS_FEED
        for c, text in cells.items():
            out["f"][f"{r},{c}"] = formula_tokens(text)
            if c in (13, 14):
                line[c] = None
        out["completed_rows"] = [n]
        return out
    return card


#: (code, year, month) -> (read at, value): the trail read once a few minutes
#: per person-month, not once per formula pass (a live card computes each
#: month several times).
_APPROVALS_CACHE = {}
_APPROVALS_TTL = 300


def loan_approvals_value(code, year, month):
    """The iApply figure for the Loan Approvals line, year to the month's
    end → float, or None when the trail could not be read."""
    import time

    from . import loan_applications as la

    key = (str(code or "").strip().upper(), int(year), int(month))
    hit = _APPROVALS_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _APPROVALS_TTL:
        return hit[1]
    try:
        value = la.accepted_offers(key[0], year, _month_end(
            datetime.date(year, month, 1)))["amount"]
    except la.LoanTrailUnavailable:
        value = None
    _APPROVALS_CACHE[key] = (time.monotonic(), value)
    return value


def _loan_approvals_rows(card, feed_col):
    """Card rows (0-based) whose feed cell names the Loan Approvals sheet."""
    return [r for r, row in enumerate(card["grid"])
            if row and len(row) > feed_col and row[feed_col] == LOAN_APPROVALS_FEED]


def with_probation(book, year=None, probation=None):
    """The sales workbook with the probation workbook's cards in it → book.

    Adds each probation card sheet, the probation Summary Allocation rows of
    the people :func:`probation_people` finds (written under the sales
    List's spelling of their name, which the card's SUMIFS look up - the
    probation List has "Monica Mwaniki", the sales List "Monicah Mwaniki"),
    and ``book["probation"]`` = {code: sheet}, which :func:`holders` reads.
    Only where every Summary Allocation column the card reads carries the
    same heading in both workbooks; otherwise the book is returned as it
    was, with the reason in its problems."""
    if not book or book.get("book") != SALES or book.get("probation") is not None:
        return book
    if probation is None:
        try:
            probation = saved(PROBATION_KIND, year or book_year(book))
        except Exception:  # noqa: BLE001 - before the table exists
            probation = None
    if not probation:
        return book
    people = probation_people(book, probation)
    if not people:
        return book
    name_of = {str(r[0] or "").strip().upper(): r[1]
               for r in (book["tables"].get("List") or [])[1:] if r}
    alloc_name = _sheet_named(book["tables"], "Summary Allocation") or "Summary Allocation"
    sales_alloc = book["tables"].get(alloc_name) or []
    prob_alloc = probation.get("allocation") or []
    def heading(grid, c):
        # The first text heading in the column (rows 2 and 3): the probation
        # sheet keeps its probation months (6) in C2, above "Name".
        return next((v.strip().lower() for v in (_at(grid, 1, c), _at(grid, 2, c))
                     if isinstance(v, str) and v.strip()), "")

    out = dict(book)
    out["problems"] = list(book.get("problems") or [])
    for sheet in set(people.values()):
        cols = _allocation_columns(probation["cards"][sheet])
        differ = [_a1(1, c) for c in sorted(cols)
                  if heading(sales_alloc, c) != heading(prob_alloc, c)]
        if differ:
            out["problems"].append(
                f"The probation workbook's Summary Allocation is laid out differently "
                f"from the sales workbook's at {', '.join(differ)}; its {sheet} card "
                f"was not used.")
            return out
    rows = []
    for row in prob_alloc[3:]:
        code = str(row[1] if len(row) > 1 else "").strip().upper()
        if code in people:
            row = list(row)
            row[2] = name_of.get(code) or row[2]
            rows.append(row)
    out["cards"] = dict(book["cards"])
    for sheet in set(people.values()):
        out["cards"][sheet] = complete_loan_approvals(probation["cards"][sheet])
    out["tables"] = dict(book["tables"])
    out["tables"][alloc_name] = list(sales_alloc) + rows
    out["probation"] = people
    return out


# ─────────────────────────────────────────────────────────────────────────
# Reading the actuals template
# ─────────────────────────────────────────────────────────────────────────

#: The sales template's sheets that the back-office one does not have.
SALES_TEMPLATE_SHEETS = {"Asset_Drawdown", "Deposit_Growth_Retail",
                         "Asset_Growth", "Revenue_Contribution"}


def read_actuals(stream):
    """The actuals template → {sheet: grid}. Every sheet, every month.

    Every column too: the sales template keeps several blocks of twelve
    months side by side on one sheet (C:R, W:AL, AQ:BF, CE:CT), and the
    cards pick the block with INDIRECT.
    """
    from openpyxl import load_workbook

    try:
        book = load_workbook(stream, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise WorkbookError(f"that is not an .xlsx workbook ({exc})")
    out = {}
    try:
        for sheet in book.worksheets:
            grid, empty = [], 0
            for row in sheet.iter_rows(values_only=True):
                values = [_store_value(v) for v in row]
                while values and values[-1] in (None, ""):
                    values.pop()
                grid.append(values)
                # A sheet formatted to the last row of Excel (the HFDI
                # template's project_titan: 1,048,479 rows, 115 used) took
                # minutes to walk. A template is a row per person: a thousand
                # empty rows in a row is the end of it.
                empty = 0 if values else empty + 1
                if empty >= 1000:
                    break
            while grid and not grid[-1]:
                grid.pop()
            out[sheet.title] = grid
    finally:
        book.close()
    if IB_TEMPLATE_SHEETS <= set(out):
        # The IB template's account-level working sheets are not read by any
        # card, and their columns are not months (template_months counts
        # columns G.. as January..).
        for sheet in IB_RAW_SHEETS:
            out.pop(sheet, None)
        return out
    if HFDI_TEMPLATE_SHEETS <= set(out):
        return out
    if not out.get("KYC") and not out.get("CASA") and not (
            SALES_TEMPLATE_SHEETS & set(out)):
        raise WorkbookError("this is not an actuals template - it has none "
                              "of the KYC, CASA or Asset_Drawdown sheets")
    return out


def actuals_book(actuals):
    """Which workbook's template this is → IB, SALES or BACK_OFFICE."""
    if IB_TEMPLATE_SHEETS <= set(actuals):
        return IB
    if HFDI_TEMPLATE_SHEETS <= set(actuals):
        return HFDI
    return SALES if SALES_TEMPLATE_SHEETS & set(actuals) else BACK_OFFICE


#: A month is in the template when it carries at least this share of the
#: figures its fullest month does. The October 2026 template has 1,753
#: non-zero figures for September and ONE for October - a stray, not a month.
MONTH_SHARE = 0.25


def template_months(actuals, first=6):
    """The months the template has figures for → [1, 2, … 9].

    Counted in non-zero numbers, because several sheets are pre-filled with
    zeros to December. ``first``: January's column (G on the back-office,
    sales and IB templates; E on the HFDI one).
    """
    counts = [0] * 12
    for grid in actuals.values():
        for row in grid[1:]:
            for index in range(12):
                column = first + index
                value = row[column] if column < len(row) else None
                if isinstance(value, (int, float)) and not isinstance(
                        value, bool) and value != 0:
                    counts[index] += 1
    top = max(counts) or 1
    return [i + 1 for i, n in enumerate(counts)
            if n and n >= top * MONTH_SHARE]


# ─────────────────────────────────────────────────────────────────────────
# Evaluating
# ─────────────────────────────────────────────────────────────────────────

class Evaluator:
    """One card sheet, one person, one month."""

    def __init__(self, book, actuals, holder, month):
        self.spec = SPECS[book.get("book", BACK_OFFICE)]
        self.book, self.actuals, self.sheet = book, actuals, holder.sheet
        self.card = book["cards"][holder.sheet]
        self.month = month
        # What the macro types into the card before it reads the score.
        self.inputs = {cell: getattr(holder, field)
                       for cell, field in self.spec.inputs.items()}
        self.memo, self.busy = {}, set()
        self.array = False
        # The admin's proration (see PRORATION): List column -> months, for
        # this person's own List row, which the card reaches by name.
        self.list_name = _txt(holder.name).lower()
        self.list_override = proration_cells(book, holder, month)
        self.holder, self.others = holder, {}

    def _other(self, sheet):
        """Another sheet of this workbook evaluated with its formulas, for
        this person and month (a spec's ``evaluate_sheets``)."""
        if sheet not in self.others:
            import copy as _copy

            h = _copy.copy(self.holder)
            h.sheet = sheet
            ev = Evaluator(self.book, self.actuals, h, self.month)
            ev.inputs = {}      # the macro types into the card, not this sheet
            ev.others = self.others
            self.others[sheet] = ev
        return self.others[sheet]

    # -- cells --------------------------------------------------------------
    def value(self, sheet, r, c):
        if sheet in (None, self.sheet):
            return self.cell(r, c)
        if (sheet in (self.book.get("evaluate_sheets") or getattr(self.spec, "evaluate_sheets", ()))
                and sheet in self.book.get("cards", {})):
            return self._other(sheet).cell(r, c)
        constants = sheet in ("Constants", getattr(self.spec, "constants_sheet", "Constants"))
        if constants and (r, c) == self.spec.month_column:
            # The template column the card reads: January's, then one a month.
            first = getattr(self.spec, "template_first_month", None)
            return float(self.month + (first - 1 if first is not None
                                       else FIRST_MONTH_INDEX - 1))
        if constants and (r, c) == self.spec.month_count:
            return float(self.month)
        grid = self.book["tables"].get(sheet)
        if grid is None:
            return REF
        if (sheet == "List" and c in self.list_override and r > 0
                and _txt(_at(grid, r, self.spec.list_cols["name"])).lower()
                == self.list_name):
            return self.list_override[c]
        return _plain(_at(grid, r, c))

    def cell(self, r, c):
        key = (r, c)
        if key in self.inputs:
            return self.inputs[key]
        if key in self.memo:
            return self.memo[key]
        tokens = self.card["f"].get(f"{r},{c}")
        if tokens is None:
            return _plain(_at(self.card["grid"], r, c))
        if key in self.busy:
            return REF  # a circular reference
        self.busy.add(key)
        outer = self.array
        try:
            self.array = bool(tokens) and tokens[0] == ["array"]
            result = self.run(tokens[1:] if self.array else tokens, r, c)
            if isinstance(result, Rng):
                result = (self.listed(result) if self.array
                          else self.scalar(result, r, c))
            if isinstance(result, list):
                # A single-cell array formula shows its first element.
                result = result[0] if result else VALUE
        finally:
            self.busy.discard(key)
            self.array = outer
        self.memo[key] = result
        return result

    def listed(self, rng):
        """A range as a flat list - how an array formula sees it."""
        return list(self.cells_of(rng))

    def scalar(self, rng, r, c):
        """Implicit intersection - a range used where one value is wanted."""
        if rng.r1 == rng.r2 and rng.c1 == rng.c2:
            return self.value(rng.sheet, rng.r1, rng.c1)
        if rng.c1 == rng.c2 and rng.r1 <= r <= rng.r2:
            return self.value(rng.sheet, r, rng.c1)
        if rng.r1 == rng.r2 and rng.c1 <= c <= rng.c2:
            return self.value(rng.sheet, rng.r1, c)
        return VALUE

    def cells_of(self, rng):
        if rng.sheet and rng.sheet.startswith("@"):
            grid = self.actuals.get(rng.sheet[1:], [])
            last = min(rng.r2, len(grid) - 1)
            for r in range(rng.r1, last + 1):
                for c in range(rng.c1, rng.c2 + 1):
                    yield _plain(_at(grid, r, c))
            return
        if rng.sheet in (None, self.sheet):
            last = min(rng.r2, len(self.card["grid"]) + 5)
        else:
            last = min(rng.r2, len(self.book["tables"].get(rng.sheet, [])))
        for r in range(rng.r1, last + 1):
            for c in range(rng.c1, rng.c2 + 1):
                yield self.value(rng.sheet, r, c)

    # -- the stack machine -------------------------------------------------
    def run(self, tokens, r, c):
        stack = []
        for t in tokens:
            kind = t[0]
            if kind == "n":
                stack.append(_plain(t[1]))
            elif kind == "r":
                stack.append(Rng(t[1], t[2], t[3], t[2], t[3]))
            elif kind == "a":
                stack.append(Rng(t[1], t[2], t[3], t[4], t[5]))
            elif kind == "name":
                stack.append(("name", t[1]))
            elif kind == "u":
                operand = self.get(stack.pop(), r, c)
                if isinstance(operand, list):
                    stack.append([self.unary(t[1], v, r, c) for v in operand])
                else:
                    stack.append(self.unary(t[1], operand, r, c))
            elif kind == "b":
                right, left = stack.pop(), stack.pop()
                stack.append(self.binary(t[1], left, right, r, c))
            elif kind == "f":
                argc = t[2]
                args = stack[len(stack) - argc:] if argc else []
                del stack[len(stack) - argc:]
                stack.append(self.call(t[1], args, r, c))
            elif kind == "udf":
                argc = t[1]
                args = stack[len(stack) - argc:]
                del stack[len(stack) - argc:]
                label = args[0][1] if isinstance(args[0], tuple) else ""
                stack.append(self.call(label.replace("_xlfn.", "").upper(),
                                       args[1:], r, c))
        return stack[-1] if stack else None

    def unary(self, op, v, r, c):
        v = self.number(v, r, c)
        if isinstance(v, Err):
            return v
        if op == "-":
            return -v
        if op == "%":
            return v / 100.0
        return v

    def get(self, v, r, c):
        if not isinstance(v, Rng):
            return v
        if self.array and not (v.r1 == v.r2 and v.c1 == v.c2):
            return self.listed(v)
        return self.scalar(v, r, c)

    def number(self, v, r, c):
        v = self.get(v, r, c)
        if isinstance(v, Err):
            return v
        if v is None or v == "":
            return 0.0
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return float(str(v).replace(",", "").strip())
        except ValueError:
            return VALUE

    def text(self, v, r, c):
        v = self.get(v, r, c)
        if isinstance(v, Err):
            return v
        if v is None:
            return ""
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, float):
            return _general(v)
        return str(v)

    def binary(self, op, left, right, r, c):
        if op == ":":
            if isinstance(left, Rng) and isinstance(right, Rng):
                return Rng(left.sheet, min(left.r1, right.r1),
                           min(left.c1, right.c1), max(left.r2, right.r2),
                           max(left.c2, right.c2))
            return VALUE
        if self.array:
            left, right = self.get(left, r, c), self.get(right, r, c)
            if isinstance(left, list) or isinstance(right, list):
                # Element by element, a single value standing for every one.
                size = max(len(x) for x in (left, right)
                           if isinstance(x, list))
                lefts = left if isinstance(left, list) else [left] * size
                rights = right if isinstance(right, list) else [right] * size
                if len(lefts) != len(rights):
                    return [Err("#N/A")] * size
                return [self.scalar_binary(op, a, b, r, c)
                        for a, b in zip(lefts, rights)]
        return self.scalar_binary(op, left, right, r, c)

    def scalar_binary(self, op, left, right, r, c):
        if op == "&":
            a, b = self.text(left, r, c), self.text(right, r, c)
            if isinstance(a, Err):
                return a
            if isinstance(b, Err):
                return b
            return a + b
        if op in ("<", "<=", "=", ">=", ">", "<>"):
            a, b = self.get(left, r, c), self.get(right, r, c)
            if isinstance(a, Err):
                return a
            if isinstance(b, Err):
                return b
            return _compare(op, a, b)
        a, b = self.number(left, r, c), self.number(right, r, c)
        if isinstance(a, Err):
            return a
        if isinstance(b, Err):
            return b
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return DIV0 if b == 0 else a / b
        if op == "^":
            try:
                return float(a ** b)
            except (OverflowError, ZeroDivisionError, ValueError):
                return Err("#NUM!")
        return VALUE

    # -- functions ----------------------------------------------------------
    def call(self, fn, args, r, c):
        fn = fn.upper()
        if fn == "IF":
            cond = self.get(args[0], r, c)
            if isinstance(cond, Err):
                return cond
            truth = _truth(cond)
            if isinstance(truth, Err):
                return truth
            if truth:
                return self.get(args[1], r, c) if len(args) > 1 else True
            return self.get(args[2], r, c) if len(args) > 2 else False
        if fn in ("AND", "OR"):
            values = []
            for a in args:
                for v in (self.cells_of(a) if isinstance(a, Rng) else [a]):
                    if isinstance(v, Err):
                        return v
                    if v is None or isinstance(v, str):
                        continue
                    values.append(bool(v))
            if not values:
                return VALUE
            return all(values) if fn == "AND" else any(values)
        if fn == "NOT":
            t = _truth(self.get(args[0], r, c))
            return t if isinstance(t, Err) else not t
        if fn in ("MIN", "MAX", "SUM", "AVERAGE", "COUNT"):
            numbers = []
            for a in args:
                if isinstance(a, (Rng, list)):
                    for v in (self.cells_of(a) if isinstance(a, Rng) else a):
                        if isinstance(v, Err):
                            return v
                        if isinstance(v, (int, float)) and not isinstance(
                                v, bool):
                            numbers.append(float(v))
                else:
                    v = self.number(a, r, c)
                    if isinstance(v, Err):
                        return v
                    numbers.append(v)
            if fn == "COUNT":
                return float(len(numbers))
            if fn == "SUM":
                total = 0.0
                for n in numbers:  # left to right, as Excel adds
                    total += n
                return total
            if fn == "AVERAGE":
                return (sum(numbers) / len(numbers)) if numbers else DIV0
            if not numbers:
                return 0.0
            return min(numbers) if fn == "MIN" else max(numbers)
        if fn == "ABS":
            v = self.number(args[0], r, c)
            return v if isinstance(v, Err) else abs(v)
        if fn in ("ROUND", "ROUNDUP", "ROUNDDOWN"):
            v, d = self.number(args[0], r, c), self.number(args[1], r, c)
            if isinstance(v, Err):
                return v
            if isinstance(d, Err):
                return d
            return _round(fn, v, int(d))
        if fn in ("IFERROR",):
            v = self.get(args[0], r, c)
            return self.get(args[1], r, c) if isinstance(v, Err) else v
        if fn in ("ISERROR", "ISNA"):
            v = self.get(args[0], r, c)
            if fn == "ISNA":
                return v == NA
            return isinstance(v, Err)
        if fn == "VLOOKUP":
            return self.vlookup(args, r, c)
        if fn == "INDIRECT":
            return self.indirect(self.text(args[0], r, c))
        if fn in ("CONCAT", "CONCATENATE"):
            out = ""
            for a in args:
                for v in (self.cells_of(a) if isinstance(a, Rng) else [a]):
                    s = self.text(v, r, c)
                    if isinstance(s, Err):
                        return s
                    out += s
            return out
        if fn == "TEXT":
            v = self.get(args[0], r, c)
            fmt = self.text(args[1], r, c)
            return _format(v, fmt)
        if fn == "YEAR":
            v = self.number(args[0], r, c)
            if isinstance(v, Err):
                return v
            return float(_from_serial(v).year)
        if fn == "MONTH":
            v = self.number(args[0], r, c)
            return v if isinstance(v, Err) else float(_from_serial(v).month)
        if fn == "DATE":
            y, m, d = (self.number(a, r, c) for a in args[:3])
            for v in (y, m, d):
                if isinstance(v, Err):
                    return v
            return _to_serial(int(y), int(m), int(d))
        if fn == "COLUMN":
            if args and isinstance(args[0], Rng):
                return float(args[0].c1 + 1)
            return float(c + 1)
        if fn == "ROW":
            if args and isinstance(args[0], Rng):
                rng = args[0]
                if self.array and rng.r2 > rng.r1:
                    return [float(i + 1) for i in range(rng.r1, rng.r2 + 1)]
                return float(rng.r1 + 1)
            return float(r + 1)
        if fn == "SUMIF":
            return self.sumifs(args[2] if len(args) > 2 else args[0],
                               [(args[0], args[1])], r, c)
        if fn == "SUMIFS":
            pairs = [(args[i], args[i + 1]) for i in range(1, len(args) - 1, 2)]
            return self.sumifs(args[0], pairs, r, c)
        return NAME

    def sumifs(self, total, pairs, r, c):
        """SUMIF/SUMIFS over a sheet: the rows whose every criterion holds."""
        if not isinstance(total, Rng):
            return VALUE
        tests = []
        for rng, criterion in pairs:
            if not isinstance(rng, Rng):
                return VALUE
            crit = self.get(criterion, r, c)
            if isinstance(crit, Err):
                return crit
            tests.append((rng, _criterion(crit)))
        grid = self._grid_of(total.sheet)
        last = min(total.r2, len(grid) - 1)
        out = 0.0
        for offset in range(0, last - total.r1 + 1):
            ok = True
            for rng, test in tests:
                v = self._grid_value(rng.sheet, rng.r1 + offset, rng.c1)
                if not test(v):
                    ok = False
                    break
            if not ok:
                continue
            v = self._grid_value(total.sheet, total.r1 + offset, total.c1)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out += float(v)
        return out

    def indirect(self, ref):
        """``[2026_BO_Actual_Template.xlsx]KYC!$c:$R`` → a range on the
        template; ``1:8`` → whole rows here; anything else on this
        workbook."""
        if isinstance(ref, Err):
            return ref
        rows = re.match(r"^\s*\$?(\d+):\$?(\d+)\s*$", ref)
        if rows:
            return Rng(None, int(rows.group(1)) - 1, 0,
                       int(rows.group(2)) - 1, 16383)
        m = re.match(r"^\s*(?:\[[^\]]*\])?'?([^'!]+)'?!\$?([A-Za-z]+)\$?(\d*)"
                     r"(?::\$?([A-Za-z]+)\$?(\d*))?\s*$", ref)
        if not m:
            return REF
        sheet, c1, r1, c2, r2 = m.groups()
        external = ref.strip().startswith("[")
        col1 = _column_index(c1)
        col2 = _column_index(c2 or c1)
        row1 = int(r1) - 1 if r1 else 0
        row2 = int(r2) - 1 if r2 else 1048575
        if external:
            # Excel matches sheet names without case: the Commercial card
            # asks for "Trade_Finance_Income" and the template's sheet is
            # "Trade_Finance_income".
            sheet = _sheet_named(self.actuals, sheet)
            if sheet is None:
                return REF
            return Rng("@" + sheet, row1, col1, row2, col2)
        return Rng(_sheet_named(self.book["tables"], sheet) or sheet, row1,
                   col1, row2, col2)

    def vlookup(self, args, r, c):
        key = self.get(args[0], r, c)
        if isinstance(key, Err):
            return key
        table = args[1]
        if not isinstance(table, Rng):
            return table if isinstance(table, Err) else VALUE
        index = self.number(args[2], r, c)
        if isinstance(index, Err):
            return index
        index = int(index)
        exact = True
        if len(args) > 3:
            mode = self.get(args[3], r, c)
            exact = not _truth(mode) if not isinstance(mode, Err) else True
        if index < 1 or index > table.c2 - table.c1 + 1:
            return REF
        grid = self._grid_of(table.sheet)
        last = min(table.r2, len(grid) - 1)
        if exact:
            for row in range(table.r1, last + 1):
                if _lookup_equal(key, _plain(_at(grid, row, table.c1))):
                    found = self._grid_value(table.sheet, row,
                                             table.c1 + index - 1)
                    return 0.0 if found is None else found
            return NA
        best = None
        for row in range(table.r1, last + 1):
            v = _plain(_at(grid, row, table.c1))
            if v is None or isinstance(v, Err):
                continue
            if _compare("<=", v, key) is True:
                best = row
            else:
                break
        if best is None:
            return NA
        found = self._grid_value(table.sheet, best, table.c1 + index - 1)
        return 0.0 if found is None else found

    def _grid_of(self, sheet):
        if sheet and sheet.startswith("@"):
            return self.actuals.get(sheet[1:], [])
        if sheet in (None, self.sheet):
            return self.card["grid"]
        return self.book["tables"].get(sheet, [])

    def _grid_value(self, sheet, r, c):
        if sheet and sheet.startswith("@"):
            return _plain(_at(self.actuals.get(sheet[1:], []), r, c))
        return self.value(sheet, r, c)


def _at(grid, r, c):
    if 0 <= r < len(grid):
        row = grid[r]
        if 0 <= c < len(row):
            return row[c]
    return None


def _column_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _truth(v):
    if isinstance(v, Err):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().upper()
    if s == "TRUE":
        return True
    if s == "FALSE":
        return False
    return VALUE


def _compare(op, a, b):
    """Excel's comparison: blank is 0 against a number and "" against text;
    text sorts after every number; text compares without case."""
    if a is None:
        a = "" if isinstance(b, str) else 0.0
    if b is None:
        b = "" if isinstance(a, str) else 0.0
    if isinstance(a, bool):
        a_rank, a = 2, float(a)
    elif isinstance(a, (int, float)):
        a_rank, a = 0, float(a)
    else:
        a_rank, a = 1, str(a).lower()
    if isinstance(b, bool):
        b_rank, b = 2, float(b)
    elif isinstance(b, (int, float)):
        b_rank, b = 0, float(b)
    else:
        b_rank, b = 1, str(b).lower()
    left, right = (a_rank, a), (b_rank, b)
    if a_rank != b_rank:
        left, right = (a_rank,), (b_rank,)
    return {"<": left < right, "<=": left <= right, "=": left == right,
            ">=": left >= right, ">": left > right,
            "<>": left != right}[op]


def _lookup_equal(key, value):
    if value is None or isinstance(value, Err):
        return False
    if isinstance(key, str) or isinstance(value, str):
        if not (isinstance(key, str) and isinstance(value, str)):
            return False
        # Exact match ignores case and nothing else: "Bob Waigwa " is not
        # "Bob Waigwa", in Excel or here.
        return key.lower() == value.lower()
    try:
        return float(key) == float(value)
    except (TypeError, ValueError):
        return False


def _sheet_named(sheets, name):
    """The key in ``sheets`` Excel would take ``name`` to mean, or None."""
    if name in sheets:
        return name
    lowered = name.lower()
    return next((key for key in sheets if key.lower() == lowered), None)


def _criterion(crit):
    """A SUMIF criterion → a test. ``"Bob"`` is equal-ignoring-case,
    ``">5"`` and friends compare, a number is numeric equality."""
    if isinstance(crit, str):
        m = re.match(r"^(<=|>=|<>|<|>|=)(.*)$", crit)
        if m:
            op, rest = m.groups()
            try:
                target = float(rest)
            except ValueError:
                target = rest
            return lambda v: (v is not None and not isinstance(v, Err)
                              and _compare(op, v, target) is True)
        return lambda v: isinstance(v, str) and v.lower() == crit.lower()
    if crit is None:
        return lambda v: v in (None, "")
    return lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)
                      and float(v) == float(crit))


def _round(fn, v, digits):
    factor = 10 ** digits
    x = v * factor
    if fn == "ROUND":
        y = math.floor(abs(x) + 0.5)
    elif fn == "ROUNDUP":
        y = math.ceil(abs(x) - 1e-9)
    else:
        y = math.floor(abs(x) + 1e-9)
    return math.copysign(y, x) / factor


def _general(v):
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _format(v, fmt):
    if isinstance(v, Err):
        return v
    if isinstance(fmt, Err):
        return fmt
    if v is None:
        v = 0.0
    if not isinstance(v, (int, float)):
        return str(v)
    m = re.match(r"^0(?:\.(0+))?(%?)$", fmt or "")
    if not m:
        return _general(float(v))
    decimals = len(m.group(1) or "")
    if m.group(2):
        return f"{v * 100:.{decimals}f}%"
    return f"{v:.{decimals}f}"


_EPOCH = datetime.date(1899, 12, 30)


def _from_serial(serial):
    return _EPOCH + datetime.timedelta(days=int(serial))


def _to_serial(year, month, day):
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    first = datetime.date(year, month, 1)
    return float((first - _EPOCH).days + day - 1)


# ─────────────────────────────────────────────────────────────────────────
# Cards
# ─────────────────────────────────────────────────────────────────────────

class Holder:
    """A List row: who, and which card."""

    def __init__(self, spec, row_index, row):
        def at(field):
            index = spec.list_cols.get(field)
            if index is None:
                return None
            return row[index] if index < len(row) else None

        self.book = spec.book
        self.row = row_index
        pf = at("pf")
        self.pf = (str(int(pf)) if isinstance(pf, float) and pf == int(pf)
                   else str(pf or "").strip())
        self.sales_code = str(at("code") or "").strip().upper()
        name = at("name")
        self.name = name if isinstance(name, str) else str(name or "")
        self.role = str(at("role") or "").strip()
        self.branch = at("branch")
        self.bbm = at("bbm")
        self.sheet = (spec.role_sheets.get(self.role)
                      or getattr(spec, "default_sheet", None))


def spec_of(book):
    return SPECS[book.get("book", BACK_OFFICE)]


def roster_roles():
    """sales code -> (name, role, branch, pf, active) off
    branch_employee_dmc_data, the active row first - the roster the platform's
    employee list shows. ``active`` is False when the only row the roster has
    for the code is an inactive one. Kept ten minutes; {} where the table
    cannot be read."""
    from django.core.cache import cache
    from django.db import connection, transaction

    found = cache.get("workbook_roster_roles_v2")
    if found is not None:
        return found
    found = {}
    # The per-person table first, then the branch table behind it - the order
    # live_scorecard.roster_row reads them in. A branch manager can be on the
    # branch table only: Dennis Geni (Naivasha BBM) had no per-person row.
    for table in ("branch_employee_dmc_data", "branch_final_employee_dmc_data"):
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"""
                    SELECT DISTINCT ON (UPPER(REPLACE(TRIM(sales_code), ' ', '')))
                           UPPER(REPLACE(TRIM(sales_code), ' ', '')), staff_name,
                           TRIM(staff_role), staff_branch, staff_pf_number,
                           COALESCE(active::text, '') IN ('1', 'true', 't')
                    FROM {table}
                    WHERE sales_code IS NOT NULL AND TRIM(sales_code) <> ''
                    ORDER BY UPPER(REPLACE(TRIM(sales_code), ' ', '')),
                             active DESC NULLS LAST""")
                for code, name, role, branch, pf, active in cur.fetchall():
                    found.setdefault(code, (name, role, branch, pf, active))
        except Exception:  # noqa: BLE001 - the List alone is still a card
            continue
    cache.set("workbook_roster_roles_v2", found, 600)
    return found


#: HR job title (employee_table.job_title, folded) -> back-office List role.
HR_TITLE_ROLES = {
    "branch service ambassador": "BSA",
    "teller": "Teller",
    "customer service officer": "CSO",
    "branch operations manager": "BOM",
    "retail back office officer": "RBO",
}
#: A List role and the HR title are only at odds across families: the List's
#: "Cash_Center" is a teller, its "CSO_UB" a customer service officer.
ROLE_FAMILIES = {"Teller": "teller", "Cash_Center": "teller",
                 "CSO": "cso", "CSO_UB": "cso", "CSM_DB": "cso",
                 "RBO": "rbo", "TL_RBO": "rbo", "BOM": "bom", "BSA": "bsa"}


def hr_roles():
    """PF -> back-office List role from HR's employee_table job title, for
    people still employed. Kept ten minutes; {} where it cannot be read.

    Felix Saigon (PF 3789) was promoted to Branch Service Ambassador on
    1 Mar 2026; the desk's List still had him as a Teller in November and his
    profile showed the teller card."""
    from django.core.cache import cache
    from django.db import connection, transaction

    found = cache.get("workbook_hr_roles")
    if found is not None:
        return found
    found = {}
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SELECT staff_id, job_title FROM employee_table "
                        "WHERE staff_id IS NOT NULL AND COALESCE(exit, 0) = 0")
            for pf, title in cur.fetchall():
                role = HR_TITLE_ROLES.get(" ".join(str(title or "").lower().split()))
                if role:
                    found[str(int(pf))] = role
    except Exception:  # noqa: BLE001 - the List alone is still a card
        found = {}
    cache.set("workbook_hr_roles", found, 600)
    return found


def _branch_key(branch):
    """A branch however it is written → one key: "HARAMBEE AVE BRANCH",
    "Harambee" -> HARAMBEE; "SAMEER BUSINESS PARK", "SameerPark" -> SAMEERPARK;
    "RIVER ROAD", "Riverroad" -> RIVERROAD."""
    text = re.sub(r"\s+branch\s*$", "", str(branch or "").strip(), flags=re.I).upper()
    text = re.sub(r"\b(AVENUE|AVE|BUSINESS)\b", " ", text)
    return re.sub(r"[^A-Z]", "", text)


def _list_branch(branch, list_branches):
    """The List's own spelling of ``branch`` (exact key, else a unique
    prefix either way), or None when the List never names it."""
    key = _branch_key(branch)
    if not key:
        return None
    exact = [b for b in list_branches if _branch_key(b) == key]
    if exact:
        return exact[0]
    near = [b for b in list_branches
            if _branch_key(b) and (_branch_key(b).startswith(key) or key.startswith(_branch_key(b)))]
    return near[0] if len(near) == 1 else None


def _branch_name(branch):
    """'EMBU BRANCH' -> 'Embu', as the back-office List writes branches."""
    text = re.sub(r"\s+branch\s*$", "", str(branch or "").strip(), flags=re.I)
    return text.title()


NO_CARD = "no_card"


def no_card():
    """{SALES CODE: {"from": "YYYY-MM", "reason": str}} - people the desk's
    workbooks still carry who are no longer in a scored role. Julie Ambundo
    (JMA1138) was still a Kisumu BOM in the back-office workbook in November
    2026 after moving to CX Manager at head office, and was being scored.
    Set with ``manage.py scorecard_no_card``."""
    from django.core.cache import cache

    found = cache.get(NO_CARD)
    if found is None:
        try:
            found = saved(NO_CARD) or {}
        except Exception:  # noqa: BLE001 - before the table exists
            found = {}
        cache.set(NO_CARD, found, 300)
    return found


def off_card(sales_code, month=None):
    """The no-card entry for ``sales_code`` if it applies to ``month`` (a date,
    default today) → dict, or None. Months before its "from" keep their card."""
    entry = no_card().get((sales_code or "").replace(" ", "").upper())
    if not entry:
        return None
    month = month or datetime.date.today()
    start = entry.get("from") or ""
    return entry if not start or f"{month:%Y-%m}" >= start else None


#: The desk's List decides every back-office person's role and branch; the HR
#: roster and job titles do not override it (decided 23 Nov 2026).
LIST_WINS = True


def role_after_change(spec, book, holder, month):
    """(role, sheet) the person holds in ``month`` after a role change or
    promotion an administrator recorded on the Proration screen, or None.

    The desk's List wins (23 Nov 2026) - for the months it covers. A change
    recorded after it is newer than the List: Ivan Ombiru (IO3870), a Teller
    on the Q3 List, CSO from October 2026, went back to the Teller card for
    November when the roster's role was switched off for everybody. From the
    month of the recorded change on, the person holds their current role on
    the roster (the entry records that the role changed, the roster to what).
    A role in the same family as the List's stands, as it always has."""
    if spec.book != BACK_OFFICE:
        return None
    entries = [e for e in (proration().get((holder.sales_code or "").upper()) or [])
               if e.get("reason") in ("role_change", "promotion") and _ym(e.get("from"))]
    started = [e for e in entries if _ym(e["from"]) <= (month.year, month.month)]
    if not started:
        return None
    found = roster_roles().get(holder.sales_code)
    if not found or not found[4]:
        return None
    role = {k.upper(): k for k in spec.role_sheets}.get(str(found[1] or "").strip().upper())
    if (not role or role == holder.role
            or (ROLE_FAMILIES.get(role) is not None
                and ROLE_FAMILIES.get(role) == ROLE_FAMILIES.get(holder.role))
            or spec.role_sheets[role] not in (book.get("cards") or {})):
        return None
    return role, spec.role_sheets[role]


def holders(book, keep_off=False):
    """The workbook's card holders. Somebody on the no-card list (see
    :func:`no_card`) is left out from their month on; ``keep_off`` keeps them
    for compute_all, which scores the months before it."""
    spec = spec_of(book)
    grid = book["tables"].get("List", [])
    out = []
    # Branch managers come from the branch-manager workbook's List only: the
    # branch table still named Dennis Geni for Naivasha after he left on
    # 10 March 2026, and adding roster BBMs gave him a card.
    # The desk's List wins (the business, 23 Nov 2026: "the desk's List wins
    # for all of them"). The roster and HR job-title corrections below moved
    # people to roles and branches the desk had not: Jasper Ondari (BOM ->
    # CSO, 76.2% -> 51.4%), Ivan Ombiru (Teller -> CSO), Sharon Wanjiru,
    # Jennifer Kiango (TRM -> Naivasha) and others, and a respelt branch
    # blanked every Harambee and SameerPark card. They stay switched off;
    # the List is the record. LIST_WINS = False brings them back.
    roster = roster_roles() if spec.book == BACK_OFFICE and not LIST_WINS else {}
    list_branches = sorted({str(r[spec.list_cols["branch"]]).strip()
                            for r in grid[1:]
                            if spec.list_cols.get("branch") is not None
                            and len(r) > spec.list_cols["branch"]
                            and str(r[spec.list_cols["branch"]] or "").strip()})
    hr = hr_roles() if spec.book == BACK_OFFICE and not LIST_WINS else {}
    by_role = {k.upper(): k for k in spec.role_sheets}
    # The desk's probation card (see with_probation), for the people it
    # scores there.
    on_probation = book.get("probation") or {}
    for index, row in enumerate(grid[1:], start=1):
        holder = Holder(spec, index, row)
        if spec.book == RETAIL_BO:
            # The workbook's own role -> sheet (E2 of each card), so a new or
            # renamed role sheet needs no code.
            by_role = {k.strip().upper(): v for k, v in rbo_role_sheets(book).items()}
            holder.sheet = by_role.get(holder.role.strip().upper())
        if not (holder.name and (holder.sales_code or holder.pf)):
            continue
        active_col = getattr(spec, "active_col", None)
        if active_col is not None:
            # The HFDI macro runs only rows whose "active" is 1.
            flag = row[active_col] if active_col < len(row) else None
            if str(flag).strip() not in ("1", "1.0"):
                continue
        if on_probation.get(holder.sales_code) in book.get("cards", {}):
            holder.sheet = on_probation[holder.sales_code]
        if not keep_off and off_card(holder.sales_code):
            continue
        found = roster.get(holder.sales_code)
        # An inactive roster row is a past posting, not a correction: Felix
        # Saigon's only DMC row (TELLER, MACHAKOS, active 0) replaced the
        # List's BSA at Komarock with Machakos, so his branch lines read
        # Machakos's figures.
        if found and not found[4]:
            found = None
        if spec.book == BACK_OFFICE and found:
            # The desk's List lags the roster: Joseph Kinuthia, a CSO at Embu
            # on the roster, still had the List's BOM card for Naivasha.
            role = by_role.get(str(found[1] or "").upper())
            # A more specific List role of the same family stands: the roster's
            # "CSO" against the List's "CSO_UB", "RBO" against "TL_RBO" - and,
            # by ROLE_FAMILIES (the rule the HR override below already used),
            # "TELLER" against "Cash_Center" and "CSO" against "CSM_DB". Matching
            # only on the names' letters turned Christine Adhiambo (CA3780,
            # Cash_Center, Rehani) into a Teller: the teller card's 43
            # transactions a day scored her 4.7% on a quarter of her weight and
            # 59% overall, where the desk's cash-centre card gave her about 80%
            # every month.
            same_family = role and (
                (ROLE_FAMILIES.get(role) is not None
                 and ROLE_FAMILIES.get(role) == ROLE_FAMILIES.get(holder.role))
                or holder.role.upper().endswith(role.upper())
                or holder.role.upper().startswith(role.upper())
                or role.upper().startswith(holder.role.upper()))
            if role and role != holder.role and not same_family:
                holder.role, holder.sheet = role, spec.role_sheets[role]
            if found[2]:
                moved = _list_branch(found[2], list_branches)
                # Only a different branch moves the person, and only into the
                # List's own spelling of it - the card looks targets up by
                # branch (a teller's Productivity target is per branch), so
                # "Harambee Ave" for the List's "Harambee" turned Productivity
                # and the whole score into #N/A for every Harambee and
                # SameerPark card (Joseph Gatundu, Christine Kamande, Purity
                # Zawadi ...). A branch the List never spells is not a move
                # the card can read, so the List's stands.
                if moved and _branch_key(moved) != _branch_key(holder.branch):
                    holder.branch = moved
        if spec.book == BACK_OFFICE and holder.pf:
            # HR's job title, where it puts the person in another role family
            # than the List - and the workbook has that card.
            hr_role = hr.get(holder.pf)
            if (hr_role and hr_role in spec.role_sheets
                    and ROLE_FAMILIES.get(hr_role) != ROLE_FAMILIES.get(holder.role)
                    and spec.role_sheets[hr_role] in book.get("cards", {})):
                holder.role, holder.sheet = hr_role, spec.role_sheets[hr_role]
        out.append(holder)
    return out


def _layout(spec, card):
    """Where the lines are: the header row says, and the end marker (the
    TOTAL row, or the signature block) ends them."""
    grid = card["grid"]
    header = next((i for i, row in enumerate(grid)
                   if any(isinstance(v, str) and v.strip() == spec.header
                          for v in row)), 7)
    end = next((i for i, row in enumerate(grid)
                if i > header and any(
                    isinstance(v, str) and v.strip().upper().startswith(
                        tuple(m.upper() for m in spec.ends))
                    for v in row)), len(grid))
    return header, end


#: Targets the business changed after the desk's workbook was set, from a
#: month on. Each puts its values into the card's own target cells, so the
#: workbook's formulas score against them unchanged; months before keep the
#: workbook's.
#:
#: Mortgage Business RM / ARM (both on the Mortgage_Business card), TAT (Loan):
#: "< 7 Days" became "< 14 Days" from the October 2026 scorecard (asked for on
#: 10 Nov 2026). The row's score is IF(actual <= YTD target, 1,
#: IF(actual <= YTD target + 1, 0.5, 0)) over the typed 7 in GROWTH, 2026 FY
#: and YTD Target.
#:
#: Branch Service Ambassador (BSA_SCORECARD), Leave Management: the sheet's
#: FY target was 48 - the Training hours target on the row above, copied
#: down - so a fully adherent BSA (actual 1.0) scored 1/24 = 4.2% (Felix
#: Saigon, Komarock, Nov 2026). The RBO and TL_RBO cards' identical row
#: carries 1.0, a share. Only the FY cell is set: the YTD cell is the sheet's
#: own FY * (months - prorated months) / 12 and recomputes from it.
TARGET_CHANGES = (
    {"sheet": "Mortgage_Business", "measure": "TAT (Loan)", "from": (2026, 10),
     "cells": {"growth": 14.0, "fy": 14.0, "ytd": 14.0},
     "initiative": "< 14 Days (Binary 90%)"},
    {"sheet": "BSA_SCORECARD", "measure": "Leave Management", "from": (2026, 1),
     "cells": {"fy": 1.0}},
)


#: Lines awarded their full score while nothing measures them, as the CX team
#: asked on 19 Nov 2026 for the Branch Service Ambassador card - the only card
#: carrying SLA and CSAT (both template sheets blank all year):
#:   * SLA is tied to the branch automation process, not yet deployed: full
#:     score until it is (``until`` None - remove the entry when it goes live).
#:   * CSAT: CX's survey starts November 2026, so October and before get the
#:     full score; from November the line waits for CX's score (``then``
#:     "wait") instead of carrying the desk's blank September as a 0.
#: Full score = 100% of the line's weight (the actual set to the YTD target),
#: not the 120% cap. Open months only: a month the desk closed keeps its card.
AWARDED_FULL = (
    {"sheet": "BSA_SCORECARD", "feed": "SLA", "until": None,
     "why": "SLA is tied to the branch automation process, which is not yet deployed"},
    {"sheet": "BSA_SCORECARD", "feed": "CSAT", "until": (2026, 10), "then": "wait",
     "why": "the CX satisfaction survey had not started"},
)


def awarded_full(sheet, feed, year, month):
    """The AWARDED_FULL entry for this card line and month → (entry, state):
    state "full" (score it in full), "wait" (no figure yet: not counted), or
    (None, None)."""
    for entry in AWARDED_FULL:
        if entry["sheet"] != sheet or _key(entry["feed"]) != _key(feed):
            continue
        if entry["until"] is None or (year, month) <= entry["until"]:
            return entry, "full"
        if entry.get("then") == "wait":
            return entry, "wait"
    return None, None


#: Proration an administrator sets for one person (asked 11 Nov 2026; Joseph
#: Kinuthia JKK3227, acting BOM May-Aug 2026, scored as a CSO after it).
#:
#: The workbook already prorates: its List carries prorate_new,
#: prorate_role_change, prorate_promotion and prorate_acting_other, and a
#: card's target formulas subtract them from the months elapsed. Read off
#: the BO workbook (Q2 with updated targets):
#:   * every card's monthly and yearly lines: months - prorate_new;
#:   * the CSO card's monthly lines (Digital Onboarding, CRM, KYC, CASA):
#:     months - prorate_new - IF(role_change>0, role_change,
#:     IF(acting_other>0, acting_other, 0));
#:   * the RBO card reads role_change, promotion and acting_other too.
#: So an entry here fills that List column for that person, and the card's
#: own formulas decide which lines it moves - exactly as if the desk had
#: typed it. The value is month by month: the months excluded up to the
#: card's month, so an earlier month is never cut by a later absence.
#:
#: Rule from the business: a joiner or new role is counted from the month
#: AFTER the start (joined in July -> target from August); acting, sick
#: leave and maternity leave exclude the months away.
PRORATION = "proration"
PRORATION_REASONS = {
    # reason: (List column, a span of months?, wording)
    "joined": ("prorate_new", False, "joined"),
    "role_change": ("prorate_role_change", False, "moved to a new role"),
    "promotion": ("prorate_promotion", False, "promoted"),
    "acting": ("prorate_acting_other", True, "acting in another role"),
    "sick_leave": ("prorate_acting_other", True, "on sick leave"),
    "maternity_leave": ("prorate_acting_other", True, "on maternity leave"),
}


def proration():
    """{sales code: [entry]}, kept five minutes."""
    from django.core.cache import cache

    found = cache.get(PRORATION)
    if found is None:
        found = saved(PRORATION) or {}
        cache.set(PRORATION, found, 300)
    return found


def _ym(text):
    """'2026-07' -> (2026, 7), or None."""
    try:
        y, m = (int(p) for p in str(text or "").split("-")[:2])
    except ValueError:
        return None
    return (y, m) if 1 <= m <= 12 else None


def excluded_months(entry, year, month):
    """How many months of ``year``, up to ``month``, the entry takes out."""
    reason = PRORATION_REASONS.get(entry.get("reason"))
    if reason is None:
        return 0
    if reason[1]:
        start, end = _ym(entry.get("from")), _ym(entry.get("to"))
        if start is None or end is None:
            return 0
    else:
        # Counted from the month after the start: that month and everything
        # before it in the year are out.
        start, end = (0, 1), _ym(entry.get("from"))
        if end is None:
            return 0
    return sum(1 for m in range(1, month + 1) if start <= (year, m) <= end)


def proration_columns(book):
    """List column header -> its index, for the proration columns this
    workbook's List has."""
    header = (book["tables"].get("List") or [[]])[0]
    wanted = {r[0] for r in PRORATION_REASONS.values()}
    return {str(v).strip().lower(): i for i, v in enumerate(header)
            if str(v or "").strip().lower() in wanted}


def proration_column(entry, columns):
    """The List column an entry fills on this workbook → name, or None.

    Its reason's own column where the List has it. Where it does not, the
    months go into prorate_new - the one column every card's targets count
    (months - prorate_new). The sales List has prorate_new alone: Elijah
    Kilonzi (EK3843, Business_Banking), acting BBM January to April 2026,
    was entered as "acting" and his card did not move (72.25% either way),
    because the column that reason names is not on that List."""
    column = PRORATION_REASONS.get(entry.get("reason"), (None,))[0]
    if column is None:
        return None
    if column in columns:
        return column
    return "prorate_new" if "prorate_new" in columns else None


def proration_cells(book, holder, month):
    """{List column index: months} for this person and month, from the admin's
    entries; {} when there are none."""
    entries = proration().get((holder.sales_code or "").upper())
    if not entries:
        return {}
    columns = proration_columns(book)
    year = book_year(book)
    out = {}
    for entry in entries:
        column = proration_column(entry, columns)
        if column is None:
            continue
        index = columns[column]
        out[index] = out.get(index, 0.0) + float(excluded_months(entry, year, month))
    return out


def proration_note(book, holder, month):
    """The sentence a card carries when the admin's proration applies, or ""."""
    entries = proration().get((holder.sales_code or "").upper()) or []
    columns = proration_columns(book)
    year = book_year(book)
    parts = []
    for entry in entries:
        reason = PRORATION_REASONS.get(entry.get("reason"))
        if reason is None or proration_column(entry, columns) is None:
            continue
        months = excluded_months(entry, year, month)
        end = _ym(entry.get("to") if reason[1] else entry.get("from"))
        # A month inside the absence (or the start month) is not this card's:
        # the desk's own record for it stands.
        if not months or end is None or (year, month) <= end:
            continue
        when = (f"{entry.get('from')} to {entry.get('to')}" if reason[1]
                else f"from {entry.get('from')}")
        parts.append(f"{reason[2]} ({when}): {months} month(s) out of the "
                     f"target")
    return ("Targets prorated: " + "; ".join(parts) + ".") if parts else ""


def _target_changes(spec, card, sheet, year, month):
    """{(row, col): value} for the TARGET_CHANGES in force for ``month``."""
    out = {}
    for change in TARGET_CHANGES:
        if change["sheet"] != sheet or (year, month) < change["from"]:
            continue
        for r, row in enumerate(card["grid"]):
            text = row[spec.cols["measure"]] if len(row) > spec.cols["measure"] else None
            if _txt(text) != change["measure"]:
                continue
            for field, value in change["cells"].items():
                if spec.cols.get(field) is not None:
                    out[(r, spec.cols[field])] = value
            if change.get("initiative"):
                out[(r, spec.cols["initiative"])] = change["initiative"]
    return out


def _keep_lines_proration_empties(book, actuals, holder, month, ev, spec,
                                  header, end):
    """Lines the admin's proration leaves with no target keep their score
    from before it -> the card rows (0-based) so kept.

    Some lines count one month behind the card: on the BO CSO card Digital
    Onboarding's year-to-date target is eight a month to the month before
    (72 at October). A role change from September takes all of those months
    out, so the workbook itself would show #DIV/0! there. Those months are
    before the change - the desk's record for them stands, as it does for
    any month inside an absence (Ivan Ombiru IO3870, CSO from October 2026).
    """
    col = spec.cols
    plain = Evaluator(book, actuals, holder, month)
    plain.list_override = {}
    plain.inputs = dict(ev.inputs)
    fields = [f for f in ("fy", "ytd", "actual", "score", "weighted")
              if col.get(f) is not None]
    kept = set()
    for r in range(header + 1, end):
        weight = ev.cell(r, col["weight"])
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            continue
        target = ev.cell(r, col["ytd"]) if col.get("ytd") is not None else None
        score = ev.cell(r, col["score"])
        if not (isinstance(score, Err) or target == 0):
            continue
        before = plain.cell(r, col["score"])
        if isinstance(before, Err):
            continue  # an error with or without proration: the workbook's own
        for f in fields:
            ev.inputs[(r, col[f])] = plain.cell(r, col[f])
        kept.add(r)
    if kept:
        ev.memo.clear()
    return kept


def _named_for(actuals, holder):
    """The template with the person's row findable by their List name.

    The card reads each sheet with VLOOKUP on the person's NAME, so a row the
    template spells differently is #N/A - a quarter of Joseph Gatundu's
    (JN3465, teller, Harambee) card went blank on Productivity while the
    desk's own run scored him 85.2%. Where a sheet has no row under the name
    but has one under the person's sales code (or PF), that row is theirs:
    a copy of it carries the List's name. Sheets that already have the name
    are shared untouched; nothing is changed when neither matches.
    """
    name = holder.name
    code = (holder.sales_code or "").strip().upper()
    pf = str(holder.pf or "").strip()
    if not (name and (code or pf)):
        return actuals
    out = None
    for sheet, grid in (actuals or {}).items():
        if not isinstance(grid, list) or len(grid) < 2:
            continue
        rows = grid[1:]
        if any(len(r) > 2 and _compare("=", r[2], name) for r in rows):
            continue

        def same_person(r):
            if len(r) > 1 and code and str(r[1] or "").strip().upper() == code:
                return True
            if pf and len(r) > 0 and r[0] not in (None, ""):
                try:
                    return str(int(float(r[0]))) == pf
                except (TypeError, ValueError):
                    return False
            return False

        hit = next((i for i, r in enumerate(rows, start=1) if same_person(r)), None)
        if hit is None:
            continue
        if out is None:
            out = dict(actuals)
        fixed = list(grid)
        row = list(fixed[hit])
        row[2] = name
        fixed[hit] = row
        out[sheet] = fixed
    return actuals if out is None else out


def _whole_customer_targets(book, card, spec, ev, holder, month, header, end):
    """A customer is a whole number: round a customer line's YTD target UP.

    The sales card's count lines already do this on the desk's own sheet -
    Number of Property (I11) and non-life policies (I14) are
    =ROUNDUP(...,0) - but New Business Banking Customers (I6) is not, so
    Naomi Kamau (NK4492) was set 0.17 of a customer for October. The same
    rounding is put on every line whose KPI names customers.

    A month the desk scored itself (its summary sheet has the score) keeps
    the workbook exactly as the desk ran it: that is the card it sent.
    """
    ytd = spec.cols.get("ytd")
    if ytd is None or (str(holder.sales_code or "").upper(), month) in \
            _recorded_for(book):
        return
    for r in range(header + 1, end):
        label = " ".join(_txt(ev.cell(r, spec.cols[k])) for k in
                         ("measure", "initiative") if spec.cols.get(k) is not None)
        tokens = card["f"].get(f"{r},{ytd}")
        if "customer" not in label.lower() or not tokens or any(
                t[0] == "f" and t[1] in ("ROUNDUP", "ROUND", "INT", "CEILING")
                for t in tokens):
            continue
        value = ev.cell(r, ytd)
        if _num(value) and not isinstance(value, bool) and value > 0 \
                and abs(value - round(value)) > 1e-9:
            ev.memo.clear()
            ev.inputs[(r, ytd)] = float(math.ceil(value - 1e-9))


_RECORDED = {}


def _recorded_for(book):
    """recorded_scores, once per loaded book."""
    key = id(book)
    hit = _RECORDED.get(key)
    if hit is None or hit[0] is not book:
        if len(_RECORDED) > 16:
            _RECORDED.clear()
        hit = _RECORDED[key] = (book, recorded_scores(book))
    return hit[1]


def compute(book, actuals, holder, month, overrides=None):
    """One person's card for one month → dict, as the workbook would show it.

    ``overrides`` puts a value straight into a card cell - {(row, col):
    value} - which is how the live card hands the formulas today's figures
    in place of the template's.
    """
    actuals = _named_for(actuals, holder)
    spec = spec_of(book)
    card = book["cards"][holder.sheet]
    ev = Evaluator(book, actuals, holder, month)
    ev.inputs.update(_target_changes(spec, card, holder.sheet, book_year(book), month))
    # Loan Approvals has no template sheet: the iApply trail's figure goes
    # into the line's actual cell (see complete_loan_approvals).
    # A month the desk filled on its own Loan_Approvals sheet keeps the desk's
    # figure (RG4072 18.5m, MM4047 14m for September).
    for r in _loan_approvals_rows(card, spec.cols["feed"]):
        if (r, spec.cols["actual"]) not in (overrides or {}) and not _num(
                _get_template(actuals, LOAN_APPROVALS_FEED, holder.sales_code,
                              month, 0, holder.name)):
            value = loan_approvals_value(holder.sales_code, book_year(book), month)
            if value is not None:
                ev.inputs[(r, spec.cols["actual"])] = value
    ev.inputs.update(overrides or {})
    col = spec.cols
    header, end = _layout(spec, card)
    _whole_customer_targets(book, card, spec, ev, holder, month, header, end)
    kept_unprorated = _keep_lines_proration_empties(
        book, actuals, holder, month, ev, spec, header, end) if ev.list_override else set()

    def at(r, field):
        index = col.get(field)
        return None if index is None else _out(ev.cell(r, index))

    lines, perspective = [], ""
    for r in range(header + 1, end):
        weight = ev.cell(r, col["weight"])
        measure = ev.cell(r, col["measure"])
        initiative = ev.cell(r, col["initiative"])
        label = ev.cell(r, col["perspective"])
        if isinstance(label, str) and label.strip():
            perspective = " ".join(label.split())
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            continue
        if not (_txt(measure) or _txt(initiative)):
            continue  # the weights' own total row
        feed = ev.cell(r, col["feed"])
        lines.append({
            "row": r + 1,
            "perspective": perspective,
            "measure": _txt(measure),
            "initiative": _txt(initiative),
            "weight": float(weight),
            "prior": at(r, "prior"),
            "growth": at(r, "growth"),
            "pm": at(r, "fy"),
            "ytd_target": at(r, "ytd"),
            "actual": at(r, "actual"),
            "score": at(r, "score"),
            "weighted": at(r, "weighted"),
            "feed": _txt(feed),
            # A line whose actual the card settles itself - typed
            # (complaints) or worked out on the card (compliments = its own
            # target) - rather than reading the template through INDIRECT.
            "typed": not any(
                t[0] == "f" and t[1] == "INDIRECT"
                for t in card["f"].get(f"{r},{col['actual']}", [])),
            "empty": (_feed_empty(actuals, feed, holder.name, month)
                      if spec.book == BACK_OFFICE else None),
        })
    score = ev.cell(*spec.score)
    out = {"sheet": holder.sheet, "month": month, "lines": lines,
           "role": holder.role, "total": _out(score)}
    if ev.list_override:
        note = proration_note(book, holder, month)
        kept = [ln["measure"] or ln["initiative"] for ln in lines
                if ln["row"] - 1 in kept_unprorated]
        if note and kept:
            note += (" " + ", ".join(kept) + " keep" + ("s" if len(kept) == 1 else "")
                     + " the score from before: every month it counts is "
                       "before the change.")
        if note:
            out["prorated"] = note
    if spec.book != BACK_OFFICE:
        # E3 and E4 of the sales and branch cards: "Reports to:" (the BBM the
        # macro types) and "Report to Title:", as the card itself shows them.
        out["reports_to"] = _txt(ev.cell(2, 4))
        out["report_to_title"] = _txt(ev.cell(3, 4))
    return out


def _txt(v):
    return " ".join(v.split()) if isinstance(v, str) else ""


def _out(v):
    if isinstance(v, Err):
        return {"e": v.code}
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return {"e": "#NUM!"}
    return v


def _feed_empty(actuals, feed, name, month):
    """Is this person's cell for the month blank on the template sheet?"""
    if not isinstance(feed, str) or feed not in actuals:
        return None
    for row in actuals[feed][1:]:
        if len(row) > 2 and isinstance(row[2], str) and isinstance(name, str) \
                and row[2].lower() == name.lower():
            column = 6 + month - 1
            value = row[column] if column < len(row) else None
            return value in (None, "")
    return None


def recorded_scores(book):
    """What the macro wrote, by person → {(sales code, month): score}.

    Matched on the sales code column, not the row: the List has been
    re-ordered since some of these months were written.
    """
    spec = spec_of(book)
    out = {}
    last = 12
    if getattr(spec, "summary_upto_run_month", False):
        run = _at(book["tables"].get("Constants") or [], *spec.month_count)
        last = int(run) if _num(run) and 1 <= run <= 12 else 12
    for sheet, header, code_col, first in spec.summaries:
        grid = book["tables"].get(sheet, [])
        for row in grid[header + 1:]:
            code = str(row[code_col] if len(row) > code_col else ""
                       ).strip().upper()
            if not code:
                continue
            for month in range(1, last + 1):
                column = first + month - 1
                v = row[column] if column < len(row) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[(code, month)] = float(v)
    return out


# ─────────────────────────────────────────────────────────────────────────
# Storing, and showing
# ─────────────────────────────────────────────────────────────────────────

def _first_of(year, month):
    return datetime.date(year, month, 1)


def book_year(book):
    grid = book["tables"].get("Constants", [])
    year = _at(grid, *spec_of(book).year)
    if isinstance(year, (int, float)) and 2000 < year < 2100:
        return int(year)
    return datetime.date.today().year


def running_totals_filled(actuals, month):
    """The template with each running total's unfilled cell for ``month`` given
    the person's last figure → a template copy (sheets it does not touch shared).

    On a sheet that only grows (:data:`ACCUMULATING_SHEETS`) a blank, or a nought
    after a figure, is a cell the desk had not filled - never a fall. The stored
    September card for Naomi Kagiri read Value of Property Sales 0 because the
    30 Oct template had 29m (Jul), 38m (Aug), 0 (Sep); the desk's own workbook
    showed 38m. The live card applied this already (:func:`_carry_forward`)."""
    from .bb_live_feeds import BLOCK_WIDTH

    out = dict(actuals)
    for sheet, rows in actuals.items():
        if _key(sheet) not in ACCUMULATING_SHEETS or len(rows) < 2:
            continue
        filled = [rows[0]]
        for row in rows[1:]:
            row = list(row)
            for o in range(0, len(row), BLOCK_WIDTH):
                at = o + 5 + month
                if at >= len(row):
                    break
                cell = row[at]
                if _num(cell) and cell != 0:
                    continue
                if cell not in (None, "") and not _num(cell):
                    continue
                last = next((row[o + 5 + e] for e in range(month - 1, 0, -1)
                             if o + 5 + e < len(row) and _num(row[o + 5 + e])
                             and row[o + 5 + e] != 0), None)
                if last is not None:
                    row[at] = last
            filled.append(row)
        out[sheet] = filled
    return out


def rescore(sales_code):
    """Recompute and store one person's months in every loaded workbook, after
    their proration changed → how many months were stored."""
    code = (sales_code or "").replace(" ", "").upper()
    stored = 0
    pairs = [(spec, year) for spec in SPECS.values()
             for year in stored_years(spec.files[0])]
    for spec, year in pairs:
        book, actuals = saved(spec.files[0], year), saved(spec.files[1], year)
        if book is None or actuals is None:
            continue
        results = compute_all(book, actuals, only={code})
        if results:
            stored += store(results, book_year(book), recorded_scores(book),
                            loaded_by="proration")
    return stored


def compute_all(book, actuals, months=None, only=None):
    """Every holder × every month with figures → [(holder, month, card)].
    ``only``: a set of sales codes, to recompute just those people."""
    spec = spec_of(book)
    months = months or template_months(
        actuals, first=getattr(spec, "template_first_month", None) or 6)
    if getattr(spec, "cap_to_run_month", False):
        # The IB template's later columns hold leftovers its account sheet
        # computes from blank balances (November's deposit growth = 0 less
        # December's), which a count of figures takes for a month. The desk
        # says which month it ran (IB Constants B2, HFDI mapping B4): nothing
        # after it is its.
        run = ib_run_month(book)
        months = [m for m in months if run and m <= run]
    by_month = {month: running_totals_filled(actuals, month) for month in months}
    changed = {month: any(by_month[month][k] is not actuals[k]
                          and by_month[month][k] != actuals[k] for k in actuals)
               for month in months}
    out = []
    year = book_year(book)
    on_probation = book.get("probation") or {}
    for holder in holders(book, keep_off=True):
        if holder.sheet is None or holder.sheet not in book["cards"]:
            continue
        if only is not None and holder.sales_code not in only:
            continue
        started = (probation_start(book, holder)
                   if holder.sales_code in on_probation else 0)
        for month in months:
            if off_card(holder.sales_code, datetime.date(year, month, 1)):
                continue
            if month <= started:
                # Before the probation targets start: the card's YTD target
                # is (month - prorate_new) / (12 - prorate_new) of the year's,
                # 0 or less, and the sheet divides by it.
                continue
            card = compute(book, by_month[month], holder, month)
            if changed[month]:
                # Which lines took the person's last running total: the desk's
                # recorded score predates them (see card_payload).
                plain = compute(book, actuals, holder, month)
                moved = [ln["measure"] or ln["initiative"]
                         for ln, was in zip(card["lines"], plain["lines"])
                         if ln["actual"] != was["actual"]]
                if moved:
                    card["filled_running_totals"] = moved
            out.append((holder, month, card))
    return out


def store(results, year, recorded=None, loaded_by=""):
    """One row per person per month, replaced on reload → how many."""
    from django.db import transaction

    from .models import BoScorecard

    recorded = recorded or {}
    with transaction.atomic():
        for holder, month, card in results:
            total = card["total"]
            BoScorecard.objects.update_or_create(
                book=holder.book, sales_code=holder.sales_code or holder.pf,
                month=_first_of(year, month),
                defaults={
                    "staff_pf": holder.pf, "staff_name": holder.name,
                    "sheet": holder.sheet, "branch": str(holder.branch or ""),
                    "card": card,
                    "total": total if _num(total) else None,
                    "recorded": recorded.get((holder.sales_code, month)),
                    "loaded_by": loaded_by,
                })
    return len(results)


#: The workbooks a year's cards are computed from. Each is kept per year
#: ("scorecards@2026"), because the KPIs - lines, weights, targets - can change
#: from one year to the next: loading 2027's workbook must not re-score a 2026
#: card. Every other kind is one row, as before.
YEARLY_KINDS = frozenset({"scorecards", "actuals", "sales_scorecards",
                          "sales_actuals", "bb_scorecards", PROBATION_KIND,
                          "rbo_scorecards", "rbo_actuals",
                          "ib_scorecards", "ib_actuals",
                          "hfdi_scorecards", "hfdi_actuals", "ib_portfolio"})


def year_kind(kind, year):
    return f"{kind}@{int(year)}"


def stored_years(kind):
    """The years ``kind`` is loaded for → sorted list."""
    from .models import BoWorkbookFile

    years = []
    for name in BoWorkbookFile.objects.filter(
            kind__startswith=f"{kind}@").values_list("kind", flat=True):
        tail = name.rsplit("@", 1)[1]
        if tail.isdigit():
            years.append(int(tail))
    return sorted(years)


def _year_for(kind, year):
    """Which loaded year serves ``year``: that year's own; else the latest
    before it (January, before the new year's workbook is in, still runs on
    last year's); else the earliest there is. None when nothing is loaded."""
    years = stored_years(kind)
    if not years:
        return None
    if year in years:
        return year
    earlier = [y for y in years if y < year]
    return earlier[-1] if earlier else years[0]


def save_file(kind, payload, file_name="", loaded_by="", year=None):
    """Store a file. A :data:`YEARLY_KINDS` file is stored for ``year``
    (default this year)."""
    from .models import BoWorkbookFile

    if kind in YEARLY_KINDS:
        kind = year_kind(kind, year or datetime.date.today().year)
    BoWorkbookFile.objects.update_or_create(
        kind=kind, defaults={"payload": payload, "file_name": file_name,
                             "loaded_by": loaded_by})


def saved(kind, year=None):
    """A stored file's payload, or None. A :data:`YEARLY_KINDS` file is the
    one for ``year`` (default this year) - see :func:`_year_for`."""
    from .models import BoWorkbookFile

    base = kind
    if kind in YEARLY_KINDS:
        found = _year_for(kind, int(year or datetime.date.today().year))
        if found is None:
            return None
        kind = year_kind(kind, found)
    row = BoWorkbookFile.objects.filter(kind=kind).first()
    payload = row.payload if row is not None else None
    if base == SPECS[SALES].files[0] and payload is not None:
        # The probation joiners' cards ride on the sales workbook.
        payload = with_probation(payload, found)
    return payload


def check(book, actuals):
    """What loading would do → a report. Nothing is written.

    The proof is the macro's own record: every month it wrote on
    Monthly_Summ is recomputed and compared, by sales code.
    """
    spec = spec_of(book)
    months = template_months(actuals,
                             first=getattr(spec, "template_first_month", None) or 6)
    if getattr(spec, "cap_to_run_month", False):
        run = ib_run_month(book)
        months = [m for m in months if run and m <= run]
    people = [h for h in holders(book) if h.sheet in book["cards"]]
    recorded = recorded_scores(book)
    by_month, differ = {}, []
    for holder in people:
        for month in months:
            score = recorded.get((holder.sales_code, month))
            if score is None:
                continue
            total = compute(book, actuals, holder, month)["total"]
            tally = by_month.setdefault(month, {"recorded": 0, "same": 0})
            tally["recorded"] += 1
            if _num(total) and abs(total - score) < 1e-9:
                tally["same"] += 1
            else:
                differ.append({"sales_code": holder.sales_code,
                               "name": holder.name, "role": holder.role,
                               "month": month, "recorded": score,
                               "computed": total})
    roles = {}
    for holder in holders(book):
        roles[holder.role or "(blank)"] = roles.get(holder.role or "(blank)",
                                                    0) + 1
    return {
        "book": spec.book,
        "year": book_year(book),
        "months": months,
        "people": len(people),
        "cards": sorted({h.sheet for h in people}),
        "roles_without_a_card": sorted(
            r for r in roles
            if r not in spec.role_sheets and r != "(blank)"),
        "left": sum(1 for h in people
                    if str(h.branch or "").strip().lower() == "left"),
        "against_the_macro": [
            {"month": m, "recorded": t["recorded"], "same": t["same"]}
            for m, t in sorted(by_month.items())],
        "differences": differ[:200],
        "problems": book.get("problems", []),
    }


def rebuild(book, actuals, loaded_by=""):
    """Compute and store every card for every month → how many stored."""
    results = compute_all(book, actuals)
    return store(results, book_year(book), recorded_scores(book),
                 loaded_by=loaded_by)


def stored_for(sales_code, as_at=None, book=BACK_OFFICE):
    from .models import BoScorecard

    code = (sales_code or "").strip()
    rows = BoScorecard.objects.filter(book=book, sales_code__iexact=code)
    if as_at is not None:
        rows = rows.filter(month__lte=as_at)
    return rows.order_by("-month").first()


def stored_month(sales_code, month_start, book):
    """The stored card for exactly this month, or None."""
    from .models import BoScorecard

    return BoScorecard.objects.filter(
        book=book, sales_code__iexact=(sales_code or "").strip(),
        month=month_start).first()


def months_loaded(sales_code, book=BACK_OFFICE):
    from .models import BoScorecard

    return [m.strftime("%Y-%m") for m in BoScorecard.objects.filter(
        book=book, sales_code__iexact=(sales_code or "").strip())
        .order_by("month").values_list("month", flat=True)]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _month_end(first):
    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt - datetime.timedelta(days=1)


def card_payload(record, asked=None):
    """A stored workbook card in the shape every card has."""
    spec = SPECS.get(getattr(record, "book", BACK_OFFICE) or BACK_OFFICE,
                     SPECS[BACK_OFFICE])
    data = record.card or {}
    perspectives, seen = [], {}
    scored = unscored = 0.0
    month_end = _month_end(record.month)
    for line in data.get("lines", []):
        name = line["perspective"] or "Other"
        if name not in seen:
            seen[name] = {"perspective": name, "weight": 0.0, "lines": []}
            perspectives.append(seen[name])
        seen[name]["weight"] += line["weight"]
        score, weighted = line.get("score"), line.get("weighted")
        if _num(score):
            scored += line["weight"]
        else:
            unscored += line["weight"]
        pm, ytd, actual = line.get("pm"), line.get("ytd_target"), \
            line.get("actual")
        prior, growth = line.get("prior"), line.get("growth")
        error = next((v["e"] for v in (actual, score) if isinstance(v, dict)),
                     "")
        pending = ""
        if error:
            pending = (f"The workbook itself shows {error} here: "
                       f"{record.staff_name} has no row on the "
                       f"{line.get('feed') or 'actuals'} sheet of the actuals "
                       f"template." if error == "#N/A" else
                       f"The workbook itself shows {error} on this line.")
        as_at = f"as at {month_end.day} {month_end:%b %Y}"
        if line.get("typed"):
            as_at = "typed on the card in the workbook"
        elif line.get("empty"):
            as_at = (f"no figure for {month_end:%B} on the "
                     f"{line.get('feed')} sheet - read as 0, as the workbook "
                     f"reads it")
        seen[name]["lines"].append({
            "kpi_code": (line.get("feed") or line["measure"]).lower(),
            "kpi_name": line["measure"] or line["initiative"],
            "measure_of_success": line["initiative"] or line["measure"],
            # The KPI cell is blank because the workbook merges it with the
            # line above - VIC Premium over its life and non-life lines. The
            # download merges them the same way.
            "continues_kpi": not line["measure"] and bool(line["initiative"]),
            "weight": line["weight"],
            "ytd_target": ytd if _num(ytd) else None,
            "annual_target": pm if _num(pm) else None,
            "target_text": pm if isinstance(pm, str) else "",
            "prior_year": prior if _num(prior) else None,
            "growth_target": growth if _num(growth) else None,
            "target_field": "",
            "target_source": spec.source,
            "full_year_target": pm == ytd,
            "ytd_actual": actual if _num(actual) else None,
            "warehouse_said": None,
            "score": score if _num(score) else None,
            "weighted_score": weighted if _num(weighted) else None,
            "counted_in_total": True,
            "as_at": as_at,
            "as_at_date": month_end.isoformat(),
            "higher_is_better": True,
            "full_marks_rule": "",
            "score_cap": None,
            "pending": pending,
            "pending_label": "Workbook error" if pending else "",
            "diagnostic": "",
        })
    total = record.total
    sheet = record.sheet
    empty = sum(1 for ln in data.get("lines", [])
                if ln.get("empty") and not ln.get("typed"))
    # The macro's own record wins: it is what the desk sent, with the List
    # and the targets as they were that month. The workbook carries only
    # today's - Q2's revised targets, today's branches, leavers marked
    # "left" - so recomputing an old month can come out differently, and
    # where it does the card says so rather than quietly replacing a score
    # somebody signed.
    recorded = record.recorded
    notes = []
    filled = data.get("filled_running_totals") or []
    if filled and _num(total):
        # The desk's run predates a running total it had not yet filled in:
        # Naomi Kagiri's September run recorded 73.8% with Value of Property
        # Sales at 0; her year to date is 38m, and the workbook then gives 75.6%.
        # The year to date sticks, so the recomputed score is the one shown.
        if _num(recorded) and abs(recorded - total) >= 1e-9:
            notes.append(
                f"The desk's scorecard run recorded {recorded:.1%} for "
                f"{record.month:%B %Y} before {', '.join(filled)} had the "
                f"year-to-date figure. With it, the workbook gives "
                f"{total:.1%}, which is the score shown.")
        recorded = None
    if data.get("prorated"):
        # The admin's proration postdates the desk's run, which had none.
        notes.append(data["prorated"])
        if _num(recorded) and _num(total) and abs(recorded - total) >= 1e-9:
            notes.append(f"The desk's scorecard run recorded {recorded:.1%} for "
                         f"{record.month:%B %Y} without it; prorated, the "
                         f"workbook gives {total:.1%}, which is the score shown.")
        recorded = None
    if _num(recorded) and not (_num(total) and abs(recorded - total) < 1e-9):
        notes.append(
            f"The desk's scorecard run recorded {recorded:.1%} for "
            f"{record.month:%B %Y}, with the targets and List as they were "
            f"then, and that is the score shown. The lines below are the "
            f"month recomputed from the workbook as it is now (revised "
            f"targets, current branches), which gives "
            + (f"{total:.1%}." if _num(total) else
               "an error in the workbook itself."))
        total = recorded
    if empty:
        notes.append(
            f"{empty} line(s) had no figure for {record.month:%B %Y} on the "
            f"actuals template, so they read as 0 - as the workbook reads "
            f"them.")
    return {
        "has_card": True,
        "live": False,
        "workbook_card": spec.book,
        "back_office_workbook": spec.book == BACK_OFFICE,
        "staff": {
            "sales_code": record.sales_code,
            "name": record.staff_name,
            "title": (TITLES.get(sheet, sheet) if spec.book == BACK_OFFICE
                      else getattr(spec, "title", "")
                      or data.get("role") or sheet),
            "role_code": (ROLE_CODES.get(sheet, sheet)
                          if spec.book == BACK_OFFICE else
                          getattr(spec, "role_code", "")
                          or (rbo_role_code(sheet) if spec.book == RETAIL_BO else None)
                          or (IB_ROLE_CODES.get(sheet) if spec.book == IB else None)
                          or (HFDI_ROLE_CODES.get(sheet) if spec.book == HFDI else None)
                          or SALES_ROLE_CODES.get(data.get("role", ""),
                                                  sheet)),
            "branch": record.branch,
            "team_leader": data.get("reports_to") or "",
            "report_to_title": data.get("report_to_title") or "",
            "roster": f"{spec.source}'s List",
            "started": None,
        },
        "book": {"customers": None, "note": ""},
        "period": {"label": record.month.strftime("%B %Y"),
                   "as_at": month_end.isoformat()},
        "target_source": spec.source,
        "performance_score": round(total, 4) if _num(total) else None,
        "scored_lines": sum(1 for p in perspectives for ln in p["lines"]
                            if ln["score"] is not None),
        "pending_lines": sum(1 for p in perspectives for ln in p["lines"]
                             if ln["pending"]),
        "scored_weight": round(scored, 4),
        "unscored_weight": round(unscored, 4),
        "perspectives": perspectives,
        "months_loaded": months_loaded(record.sales_code, spec.book),
        "coverage_note": " ".join(notes),
        "showing_other_month": (
            "" if asked is None or asked.replace(day=1) == record.month else
            f"Nothing is loaded for {asked:%B %Y}; this is "
            f"{record.month:%B %Y}, the latest month on or before it."),
        "how_scored": (f"Computed from {spec.source}'s own formulas over "
                       f"the actuals template - the same cells the desk's "
                       f"macro fills and reads, so the score is the one the "
                       f"workbook gives."),
    }


# ─────────────────────────────────────────────────────────────────────────
# The live card: the workbook's rules, today's figures
# ─────────────────────────────────────────────────────────────────────────

def _key(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def waiting_on(sales_code):
    """A loaded workbook's List holds this person but no card of theirs is
    computed yet → the sentence saying which file is missing, or None.

    The cards are computed only once both a workbook and the actuals
    template it reads are loaded; until then the person is on no roster that
    gives them a card, and "no scorecard for your role" would be wrong.
    """
    code = (sales_code or "").strip().upper()
    if not code:
        return None
    for spec in SPECS.values():
        book = saved(spec.files[0])
        if book is None or not any(h.sales_code == code
                                   for h in holders(book)):
            continue
        if saved(spec.files[1]) is None:
            return (f"You are on the {spec.label} scorecards workbook, but "
                    f"the actuals template it reads has not been loaded, so "
                    f"no card is computed yet. Administration loads it under "
                    f"Scorecards → Figures to load → Load the scorecard "
                    f"workbooks.")
        return (f"You are on the {spec.label} scorecards workbook, but no "
                f"card was computed for you - load the actuals template "
                f"again under Scorecards → Figures to load.")
    return None


def _template_row(actuals, sheet, code, block=0, person=None):
    """One person's row on a template sheet, or None: by sales code, then by
    name where given, as the back-office template keys some sheets one way
    and some the other."""
    from .bb_live_feeds import BLOCK_WIDTH

    o = block * BLOCK_WIDTH
    name = _sheet_named(actuals, sheet)
    rows = (actuals.get(name) or [] if name else [])[1:]
    wanted = [(o + 1, code)] + ([(o + 2, person)] if person else [])
    for column, value in wanted:
        for row in rows:
            if len(row) > column and str(row[column] or "").strip().upper() == \
                    str(value).strip().upper():
                return row
    return None


def _put_template(actuals, sheet, code, month, value, block=0, person=None):
    """Write one person's figure for one month into a template copy → True
    when their row was there. ``block`` is which of a sheet's side-by-side
    tables (20 columns apart) - the bancassurance sheet keeps three."""
    from .bb_live_feeds import BLOCK_WIDTH

    o = block * BLOCK_WIDTH
    row = _template_row(actuals, sheet, code, block, person)
    if row is None:
        return False
    while len(row) < o + 6 + month:
        row.append(None)
    row[o + 6 + month - 1] = value
    return True


#: Template sheets that only grow through the year: counts and sums of what
#: was sold, opened or disbursed. Balances, rates and charges are not here.
#: Checked on both templates: on these, the desk's own monthly figures
#: never fall for 93-100% of people. The back office's VIC and HFCB
#: properties sheets are the same measures under that template's names.
ACCUMULATING_SHEETS = {"plotsalesvolume", "plotsalesvalue",
                       "tradefinanceincome", "bancaassuranceincome",
                       "newcustomers", "assetdrawdown", "traininghours",
                       "vic", "viclife", "vicnonlife", "loanapprovals",
                       "hfcbpropertiesvalue", "hfcbpropertiesvolume"}


#: Year-to-date figures the business holds at what the person already
#: achieved (11 Nov 2026), higher-is-better only: an RM at 0.82 on the desk's
#: September Weighted Sales (102.2% of 0.8) read 0.79 live in November; Asset
#: Growth 63,969,185 at September read 62,221,053 at October. A live figure
#: replaces the desk's once it is higher.
STICKY_SHEETS = {"weightedsales", "assetgrowth", "depositgrowthretail"}


#: Back-office sheets that are running COUNTS, measured on the BO template:
#: CASA (accounts opened, 4 a month; never falls for 67 of 74 people),
#: Digital_Customers (61/61), KYC (85/89), CRM (27/32 - complaints logged).
#: Back office only: the sales template's CASA is a deposit BALANCE, which falls.
BO_ACCUMULATING_SHEETS = {"casa", "digitalcustomers", "kyc", "crm"}

#: Off until the desk's Digital_Customers source is known. The 12 Nov 2026
#: check found the Whizz onboarding report (created_by, named via res_users)
#: is NOT it: 3 of 36 months agreed, most CSOs with desk figures never appear
#: as a Whizz creator, and the desk's totals fall in places (a current count,
#: not onboardings). The card keeps the desk's figures meanwhile.
WHIZZ_ON_CARDS = False


#: Back-office account-opening turnaround: the desk's figure is the month's
#: own rate (accounts_tat.py, per iApply user, by month), keyed on the
#: person's AD username in the template's code column. The engine's reader
#: was the branch's whole-year average span per application: Joseph
#: Kinuthia (Embu) read 5.48 and 18.97 days in November against the desk's
#: 0.23 and 0.6 for September. These lines read
#: account_opening.desk_turnaround instead, which gave the desk's own Jul-Sep
#: figures for him; with no step in the month the desk's latest month stands.
BO_DESK_TAT_SHEETS = {"accountopeningpb", "accountopeningbb"}
#: The template's audit sheets, read off Internal Audit's branch return.
BO_AUDIT_SHEETS = {"branchaudit", "branchauditresolution"}
#: "Annual audit score of 1.65" - a grade, lower is better (audit_returns).
BO_AUDIT_TARGET = 1.65


#: Cards whose CASA line is not the person's own accounts: the RBOs' counts
#: accounts processed (hundreds a month), and the Ultimate CSO's and Diaspora
#: CSM's is an average over their RMs (42.93, 25.32 on the template).
BO_CASA_NOT_OWN = {"RBO_SCORECARD", "TL_RBO_SCORECARD", "CSO_UB_SCORECARD",
                   "CSM_DB_SCORECARD"}


def _get_template(actuals, sheet, code, month, block=0, person=None):
    """One person's figure for one month on the template, or None."""
    from .bb_live_feeds import BLOCK_WIDTH

    o = block * BLOCK_WIDTH
    row = _template_row(actuals, sheet, code, block, person)
    if row is None:
        return None
    return row[o + 5 + month] if len(row) > o + 5 + month else None


def _carry_forward(actuals, sheet, month):
    """Put the desk's latest month into ``month`` for EVERY row of a sheet
    on a template copy → the month it came from, or None.

    The template is year to date (balances, YTD sums, rates), so the desk's
    latest month IS each person's year to date - a line the warehouse has
    no live figure for shows that and is scored, rather than reading nought
    while the person may already have made the target.

    Every row, not one person's: the card's own formula (INDIRECT +
    VLOOKUP) then finds the person exactly as Excel does - by sales code on
    one sheet, by AD username or name on another, as the back office
    template mixes them. Every side-by-side table of the sheet is carried,
    so each line finds its own. "Latest" is the last month with any figure
    for anyone on that table; the months after it are blank or a formula's
    nought for everyone, so nothing the desk entered is overwritten.
    """
    from .bb_live_feeds import BLOCK_WIDTH

    name = _sheet_named(actuals, sheet)
    rows = (actuals.get(name) or []) if name else []
    if len(rows) < 2:
        return None, {}
    width = max(len(r) for r in rows)
    used, months = None, {}
    for o in range(0, width, BLOCK_WIDTH):
        people = [r for r in rows[1:]
                  if any(len(r) > o + i and r[o + i] not in (None, "")
                         for i in (0, 1, 2))]
        # The desk's latest month is read off the rows it keys (column B):
        # rows without a key - the RBBMs on Branch_Audit - come pre-filled
        # with a figure for all twelve months.
        keyed = [r for r in people if len(r) > o + 1 and r[o + 1]]
        latest = next((m for m in range(month, 0, -1)
                       if any(len(r) > o + 5 + m and _num(r[o + 5 + m])
                              and r[o + 5 + m] != 0 for r in keyed)), None)
        if latest is None:
            # Nought for everyone (no operation losses, say) is still the
            # desk's figure: the last month it entered anything.
            latest = next((m for m in range(month, 0, -1)
                           if any(len(r) > o + 5 + m and _num(r[o + 5 + m])
                                  for r in keyed)), None)
        if latest is None:
            continue
        if latest <= month:
            growing = _key(sheet) in ACCUMULATING_SHEETS
            for r in people:
                while len(r) < o + 6 + month:
                    r.append(None)
                if latest == month:
                    # The desk's latest month itself: a person's own figure there
                    # stands, unless it is blank, or a nought after a figure on a
                    # sheet that only grows. Naomi Kagiri's Value of Property
                    # Sales read 29m (Jul), 38m (Aug), 0 (Sep) on a template the
                    # desk had not finished, and the card scored her 0.
                    cell = r[o + 5 + month]
                    if _num(cell) and not (cell == 0 and growing and any(
                            _num(r[o + 5 + e]) and r[o + 5 + e] != 0
                            for e in range(1, month))):
                        continue
                # Each person's own latest: blank in the desk's latest month
                # means the desk did not fill them that month, so their last
                # entered month stands; on a sheet that only grows, a nought
                # after a figure is a formula over blanks, not a fall.
                value, own = None, None
                for m in range(latest, 0, -1):
                    v = r[o + 5 + m]
                    if not _num(v):
                        continue
                    if v == 0 and growing and any(
                            _num(r[o + 5 + e]) and r[o + 5 + e] != 0
                            for e in range(1, m)):
                        continue
                    value, own = v, m
                    break
                r[o + 5 + month] = value
                if own:
                    for i in (0, 1, 2):
                        ident = str(r[o + i] or "").strip().upper()
                        if ident:
                            months[ident] = max(months.get(ident, 0), own)
        used = max(used or 0, latest)
    return used, months


def _line_blocks(book, actuals, holder, month, base, feeds_live):
    """{card row: block} for the lines on a sheet with more than one table
    proven: a marker is put in each block in turn, and the lines whose
    actual moves are the ones reading it. Exact, where guessing the block
    from a line's label would not be."""
    import copy

    out = {}
    for wl in base["lines"]:
        blocks = feeds_live.get(_key(wl["feed"])) or {}
        if set(blocks) == {0} or wl["row"] in out:
            continue
        for b in blocks:
            trial = copy.deepcopy(actuals)
            if not _put_template(trial, wl["feed"], holder.sales_code, month,
                                 987654321.0, b):
                continue
            moved = compute(book, trial, holder, month)
            for before, after in zip(base["lines"], moved["lines"]):
                if before["actual"] != after["actual"]:
                    out[after["row"]] = b
    return out


def _engine_match(pool, wl):
    """The engine line a workbook line reads: sheet and name, then sheet,
    then name - the matching the live figures use."""
    return (next((p for p in pool if p["feed"] and p["name"]
                  and p["feed"] == _key(wl["feed"])
                  and p["name"] == _key(wl["measure"])), None)
            or next((p for p in pool if p["feed"] and
                     p["feed"] == _key(wl["feed"])), None)
            or next((p for p in pool if p["name"] and
                     p["name"] == _key(wl["measure"])), None)
            # A line whose KPI cell is merged with the one above (VIC
            # Premiums / "non-life as per assigned Target") is named only by
            # its measure of success.
            or (next((p for p in pool if p["name"] and
                      p["name"] == _key(wl.get("initiative"))), None)
                if not _key(wl["measure"]) else None))


#: Asset Growth's cap per role, read from the desk's Summary Allocation
#: formula (Portfolio Management - Q3 2026): asset_growth =
#: IF(Assets x rate >= cap, cap, Assets x rate), the cap typed into each row
#: and the same for every row of a role. Used only when the loaded sheet has
#: no capped row for the role to read it from.
ASSET_GROWTH_CAPS = {
    "PB ARM": 40500000.0, "PB BBC": 40500000.0, "PB RM": 60750000.0,
    "SME ARM": 92880000.0, "SME BBC": 74304000.0, "SME RM": 116100000.0,
    "ULTIMATE RM": 109375000.0, "COMMERCIAL RM": 160510204.0,
    "COMMERCIAL RM- TRADE": 160510204.0,
}


def asset_growth_cap(book, role, rate):
    """The cap on a role's Asset Growth target, or None.

    Read off the loaded Summary Allocation: a row of this role whose
    asset_growth (column M) is below Assets (column L) x rate was capped, and
    that figure is the cap. Else the cap read from the sheet's formula."""
    role_key = str(role or "").strip().upper()
    grid = ((book or {}).get("tables") or {}).get(
        _sheet_named((book or {}).get("tables") or {}, "Summary Allocation") or "") or []
    found = []
    for row in grid[3:]:
        if len(row) < 13 or str(row[3] or "").strip().upper() != role_key:
            continue
        assets, growth = row[11], row[12]
        if _num(assets) and _num(growth) and growth > 0 and growth + 1 < assets * rate:
            found.append(float(growth))
    if found:
        return max(found)
    return ASSET_GROWTH_CAPS.get(role_key)


def engine_target_cells(spec, lines, pool, prorate_of, cap_of=None):
    """{row: (cells, engine line)}: the targets the workbook has none of.

    The sales workbook takes every target off its Summary Allocation sheet by
    the person's name, so somebody the desk has not put on it - a joiner such
    as Jackson Nyawa (JN3696, PB ARM, from September) - gets 0 on every line
    and #DIV/0! everywhere, although his targets are allocated on the DMC
    tables. The live engine already reads those (allocation sheet, then the
    person's own DMC row, then the role's target); this puts its GROWTH into
    the card's growth cell, prorated exactly as the workbook prorates the
    sheet's figure (x (12 - prorate_new) / 12), and its prior year into the
    prior cell, so the card's own 2026 FY, YTD and score formulas run as they
    do for everybody else. A target the workbook does have is never touched.
    """
    cols = spec.cols
    out = {}
    if cols.get("growth") is None:
        return out
    # Each engine line answers one card line, in order: VIC Premiums and its
    # non-life line read the same sheet, and without taking the first match
    # out of the pool both got the life target (Jackson Nyawa: 1,408.5 on
    # non-life where his DMC row sets 51,815).
    pool = list(pool)
    for wl in lines:
        if wl.get("typed"):
            continue
        match = _engine_match(pool, wl)
        if match is not None:
            pool.remove(match)
        if any(_num(wl.get(f)) and wl.get(f) != 0 for f in ("pm", "growth")):
            continue
        if match is None or match["negate"]:
            continue
        ln = match["line"]
        annual, prior, growth = (ln.get("annual_target"), ln.get("prior_year"),
                                 ln.get("growth_target"))
        if not _num(growth):
            # A rate line's annual target IS the growth (20% x the base) and
            # its prior year the base; a level's growth is level - base.
            if ln.get("target_is_rate"):
                growth = annual
            else:
                growth = (annual - prior) if _num(annual) and _num(prior) else annual
        if not _num(growth) or growth == 0:
            continue
        # Asset Growth is capped per role, as Summary Allocation caps it.
        if (cap_of and ln.get("target_is_rate")
                and ln.get("base_key") == "december_loan_book"
                and _num(ln.get("target_rate"))):
            cap = cap_of(float(ln["target_rate"]))
            if _num(cap) and growth > cap:
                growth = cap
        prorate = prorate_of(wl["row"])
        prorate = float(prorate) if _num(prorate) and 0 <= prorate < 12 else 0.0
        cells = {(wl["row"] - 1, cols["growth"]): float(growth) * (12 - prorate) / 12}
        if cols.get("prior") is not None and _num(prior):
            cells[(wl["row"] - 1, cols["prior"])] = float(prior)
        out[wl["row"]] = (cells, ln)
    return out


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
           "oct", "nov", "dec")


def _loan_book_from_start(spec, card_lines, engine_for_row, code, prorate_of, as_at,
                          cap_of=None):
    """{row: (cells, why)}: Asset Growth for somebody whose allocated book
    started after December.

    The rule is 38% of the December loan book: the book the person held when
    their year's targets began. A joiner's targets begin later - the List's
    prorate_new (Jackson Nyawa, JN3696: 9, so from October) - and the loans
    on the customers allocated to them may start after December too (his 6
    loans: 0 in every 2025 column, the first balances in June and September
    2026). So the base is the allocated customers' book at the end of the
    month before their targets start - September for him, December for
    everybody who holds the year - and the actual is growth since that base,
    measured from the same point. Only where the December base was read and
    is zero; nobody else's card changes.
    """
    from services import portfolio_service as svc

    out = {}
    cols = spec.cols
    if spec.book != SALES or cols.get("growth") is None:
        return out
    for wl in card_lines:
        ln = engine_for_row.get(wl["row"]) or {}
        if not (ln.get("base_is_zero") and ln.get("base_key") == "december_loan_book"
                and _num(ln.get("target_rate"))):
            continue
        p = prorate_of(wl["row"])
        p = int(p) if _num(p) and 1 <= p < 12 else 0
        if not p or p >= as_at.month:
            continue
        yy = str(as_at.year)[-2:]
        now_col = (f"{_MONTHS[as_at.month - 1]}_{yy}_bal"
                   if as_at.month != datetime.date.today().month
                   or as_at.year != datetime.date.today().year else "yester_1_bal")
        try:
            base = svc.allocated_loan_book(code, f"{_MONTHS[p - 1]}_{yy}_bal")
            now = svc.allocated_loan_book(code, now_col)
        except Exception:  # noqa: BLE001 - the line stays not applicable
            continue
        if not base:
            continue
        r = wl["row"] - 1
        growth = float(ln["target_rate"]) * base
        cap = cap_of(float(ln["target_rate"])) if cap_of else None
        if _num(cap) and growth > cap:
            growth = cap
        cells = {(r, cols["growth"]): growth * (12 - p) / 12,
                 (r, cols["actual"]): (now or 0.0) - base}
        if cols.get("prior") is not None:
            cells[(r, cols["prior"])] = base
        out[wl["row"]] = (cells, f"{float(ln['target_rate']):.0%} of the loan book of "
                                 f"the customers allocated to you at the end of "
                                 f"{datetime.date(as_at.year, p, 1):%B %Y} ({base:,.0f}), "
                                 f"the month before your targets start; growth is "
                                 f"measured from that same book")
    return out


def live_card(sales_code, engine_card, as_at):
    """The month still open, scored by the workbook's own formulas over the
    figures the warehouse gives today → a card, or None.

    A closed month is the stored card - the template the desk filled, the
    score the desk sent. The open month has no template yet, so each line's
    actual is the live engine's warehouse figure for that line, put into the
    card's actual cell; the workbook's own targets, caps and weights then
    score it. A line the warehouse has no figure for is shown as waiting for
    one, never as a zero.
    """
    from .models import BoScorecard
    from .scorecard_automation.models import ScKpi

    code = (sales_code or "").strip()
    latest = (BoScorecard.objects.filter(sales_code__iexact=code)
              .order_by("-month").first())
    # Which workbook: the one the desk last sent this person's card from - or,
    # for somebody the desk never sent one (Dennis Geni, a branch manager the
    # branch-manager List does not carry), the workbook that holds them now.
    order = ([latest.book] if latest is not None else []) + [
        b for b in (BRANCH_BUSINESS, SALES, BACK_OFFICE)
        if latest is None or b != latest.book]
    spec = book = actuals = holder = None
    for name in order if latest is None else order[:1]:
        spec = SPECS.get(name, SPECS[BACK_OFFICE])
        # The card's own year's workbook and template, never a later year's.
        book = saved(spec.files[0], as_at.year)
        actuals = saved(spec.files[1], as_at.year)
        if book is None or actuals is None:
            continue
        holder = next((h for h in holders(book)
                       if h.sales_code == code.upper() and h.sheet), None)
        if holder is not None and holder.sheet in book["cards"]:
            break
        holder = None
    if holder is None or book is None or actuals is None:
        return None

    if as_at is None:
        first_this = datetime.date.today().replace(day=1)
        as_at = first_this - datetime.timedelta(days=1)
    changed = role_after_change(spec, book, holder, as_at)
    if changed:
        holder.role, holder.sheet = changed
    if as_at.year != book_year(book):
        return None
    month = as_at.month

    if spec.book in (IB, HFDI):
        # Institutional Banking and HFDI: a month its actuals template has is
        # the stored card - the workbook's formulas over the desk's figures,
        # exactly. A month it does not have gets no card rather than a made-up
        # one: the IB template's later columns hold leftovers (a blank balance
        # less December's), which scored the head -23.6% for November. The IB
        # month still open reads the warehouse (ib_live) when its feed is on.
        record = stored_month(code, datetime.date(as_at.year, month, 1), spec.book)
        if record is not None:
            return card_payload(record, asked=as_at)
        if spec.book == IB:
            from . import ib_live

            live = ib_live.live_ib_card(book, actuals, holder, as_at)
            if live is not None:
                return live
        title = "Institutional Banking" if spec.book == IB else "HFDI"
        return {"has_card": False, "reason": f"{spec.book}_month_not_loaded",
                "sales_code": code.upper(),
                "detail": (f"Your {as_at:%B %Y} {title} card fills in when the "
                           f"{title} scorecards workbook and actuals template run "
                           f"for {as_at:%B %Y} are loaded under Scorecards.")}

    # The live engine's figure for each of its lines, labelled with the
    # template sheet that line reads - which is what the workbook names too.
    live_lines = [ln for p in (engine_card or {}).get("perspectives", [])
                  for ln in p["lines"]]
    kpis = {k: (sheet, negate) for k, sheet, negate in ScKpi.objects.filter(
        kpi_code__in=[ln["kpi_code"] for ln in live_lines])
        .values_list("kpi_code", "actuals_sheet", "negate")}
    pool = [{"feed": _key((kpis.get(ln["kpi_code"]) or ("", False))[0] or ""),
             "name": _key(ln.get("kpi_name")), "line": ln,
             # The template stores this line the other way round (PL_Charge
             # holds a loan loss as a negative; the engine reads the charge
             # as a positive), and the card's formula reads the template's
             # sign: +653,403 against a target of -1,150,476 scored 120%.
             "negate": bool((kpis.get(ln["kpi_code"]) or ("", False))[1])}
            for ln in live_lines]

    # Pass one with the template's own figures for the month, so the rows
    # and feeds are known; then the same card with today's figures in.
    base = compute(book, actuals, holder, month)
    actual_col = spec.cols["actual"]
    overrides, found = {}, {}
    # Targets the workbook has none of, from the engine's per-person targets
    # (see engine_target_cells). Sales cards: the back office's targets are
    # the role's own numbers on the card, not an allocation.
    target_cells, target_from = {}, {}
    # The engine's line for each card row, kept for its reason when neither
    # the workbook nor the engine has a target.
    engine_for_row = {}
    _left = list(pool)
    for _wl in base["lines"]:
        _m = _engine_match(_left, _wl)
        if _m is not None:
            _left.remove(_m)
            engine_for_row[_wl["row"]] = _m["line"]
    if spec.book == SALES:
        _prorate_ev = Evaluator(book, actuals, holder, month)
        filled = engine_target_cells(spec, base["lines"], pool,
                                     lambda r: _prorate_ev.cell(r - 1, 14),
                                     cap_of=lambda rate: asset_growth_cap(
                                         book, holder.role, rate))
        for row, (cells, ln) in filled.items():
            target_cells.update(cells)
            target_from[row] = ln.get("target_source") or "your own allocated target"
        if filled:
            # Some lines build 2026 FY straight off the allocation rather than
            # from the growth cell (VIC, non-life, drawdowns): where FY is
            # still 0, the same prorated figure goes into the FY cell.
            growth_col, fy_col = spec.cols["growth"], spec.cols["fy"]
            for wl in compute(book, actuals, holder, month, target_cells)["lines"]:
                if wl["row"] not in filled or (_num(wl.get("pm")) and wl["pm"] != 0):
                    continue
                value = filled[wl["row"]][0].get((wl["row"] - 1, growth_col))
                if _num(value):
                    target_cells[(wl["row"] - 1, fy_col)] = value
    overrides.update(target_cells)
    # The back office first reads the feeds the probe has proven - a count
    # off transaction_diary that gave the desk's own figures for a closed
    # month (bo_live_feeds). They win over the engine, whose readers look
    # up a seller code that a teller does not sell under.
    # A branch manager's row is the branch's own total, so the branch
    # feeds the probe has proven (bb_live_feeds) are read by branch - the
    # engine's per-person readers never give a branch total.
    feeds_live, reader = {}, None
    if spec.book == BACK_OFFICE:
        from . import bo_live_feeds

        feeds_live = {_key(k): v for k, v in bo_live_feeds.proven().items()
                      if not v.get("roles") or str(holder.role or "") in v["roles"]}
        reader = lambda feed: bo_live_feeds.live_value(  # noqa: E731
            feed, code, as_at, branch=holder.branch, name=holder.name)
    elif spec.book == BRANCH_BUSINESS:
        from . import bb_live_feeds

        # sheet → {block: feed}: one sheet can hold several proven tables.
        for k, v in bb_live_feeds.proven().items():
            feeds_live.setdefault(_key(k.split("#")[0]), {})[
                int(v.get("block") or 0)] = v
        reader = lambda feed: bb_live_feeds.live_value(  # noqa: E731
            feed, holder.branch, as_at)
        blocks = _line_blocks(book, actuals, holder, month, base, feeds_live)
        # Which table each line on a several-table sheet reads, proven or not:
        # the label of a line still on the desk's figure names what was tried.
        table_of = _line_blocks(book, actuals, holder, month, base,
                                bb_live_feeds.defined_blocks())
    from . import sales_live_feeds

    # RM lines proven against a closed month read the warehouse.
    sales_proven = sales_live_feeds.proven() if spec.book == SALES else {}
    # Back-office lines the engine has been shown to read as the desk does.
    bo_engine = set()
    if spec.book == BACK_OFFICE:
        from . import bo_live_feeds

        bo_engine = {k for k, v in bo_live_feeds.engine_proven().items()
                     if v.get("live")}
    elif spec.book == SALES:
        bo_engine = {k for k, v in sales_proven.items() if v.get("live")}
    live_rows, template_live = set(), None
    # The back office finds some people by name; what was written, to check.
    person = holder.name if spec.book == BACK_OFFICE else None
    written = {}
    # Every line starts from the desk's latest year-to-date figure; a live
    # one then writes over it. All three books.
    import copy

    carried = {}
    template_live = copy.deepcopy(actuals)
    by_sheet = {}
    # Lines the business scores in full for now, or that wait for a figure the
    # desk never had (AWARDED_FULL): row -> (entry, "full" | "wait").
    awarded = {}
    for wl in base["lines"]:
        if wl["typed"] or not wl["feed"]:
            continue
        entry, state = awarded_full(holder.sheet, wl["feed"], as_at.year, month)
        if entry is not None:
            awarded[wl["row"]] = (entry, state)
            continue
        k = _key(wl["feed"])
        if k not in by_sheet:
            by_sheet[k] = _carry_forward(template_live, wl["feed"], month)
        latest, months = by_sheet[k]
        if latest:
            # The month the person's own figure is from, for the label.
            own = next((months[i] for i in (
                code.upper(), str(holder.name or "").strip().upper(),
                str(holder.pf or "").strip().upper()) if i and i in months),
                None)
            carried[wl["row"]] = own or latest
    # The desk's year to date per line, before anything live is put in.
    desk_card = (compute(book, template_live, holder, month, target_cells)["lines"]
                 if carried else [])
    desk = {wl["row"]: wl["actual"] for wl in desk_card}
    # What the desk's latest figure scores against THIS month's target.
    desk_score = {wl["row"]: wl["score"] for wl in desk_card}
    prior = {}
    beside = {}     # row -> scored on the warehouse's figure, not yet matched to the desk
    dashboard = {}  # row -> the month of the Weighted TAT Dashboard it read
    cx_return = {}  # row -> which CX return (CRM logs / data update) it read
    measured = {}   # row -> how a back-office dormancy / CASA figure was read
    finance = {}    # row -> the month of Finance's Branch Accounts it read
    tat_report = {}  # row -> (iApply user, month) read off the accounts TAT report
    approvals_rows = set()  # Loan Approvals: the desk's YTD plus iApply since
    no_tat = {}     # row -> why TAT (Loan) has no figure this month
    for wl in base["lines"]:
        if wl["typed"]:
            continue
        if carried.get(wl["row"]) == month:
            # The desk has this person's figure for this very month - the
            # figure that is signed. Nothing live replaces it.
            continue
        if wl["row"] in awarded:
            if awarded[wl["row"]][1] == "full" and _num(wl.get("ytd_target")):
                overrides[(wl["row"] - 1, actual_col)] = float(wl["ytd_target"])
            continue
        if wl["feed"] == LOAN_APPROVALS_FEED:
            # Accepted offers off the iApply loan trail (the TAT (Loan)
            # line's source), year to this month's end. Where the desk's
            # template has an earlier month, its year to date stands and
            # only what was accepted after that month is added - as topped
            # does for the mortgage lines.
            value = loan_approvals_value(code, as_at.year, month)
            then = carried.get(wl["row"])
            how = ("approved amount on your applications whose offer letter "
                   "was accepted, year to date (iApply loan trail)")
            if value is not None and then and then < month and _num(desk.get(wl["row"])):
                before = loan_approvals_value(code, as_at.year, then)
                if before is None:
                    continue
                value = float(desk[wl["row"]]) + max(0.0, value - before)
                how = (f"the desk's year to date to "
                       f"{datetime.date(as_at.year, then, 1):%b %Y} "
                       f"({float(desk[wl['row']]):,.0f}) plus offers accepted "
                       f"since (iApply loan trail)")
            if value is not None:
                overrides[(wl["row"] - 1, actual_col)] = float(value)
                measured[wl["row"]] = how
                approvals_rows.add(wl["row"])
            continue
        if spec.book == RETAIL_BO:
            # The individual lines (rbo_live_feeds), read for every open
            # month. A line proven against the desk's own figures moves both
            # ways. One not yet proven still reads, but - the rule every
            # workbook card has (11 Nov 2026) - cannot score a person LOWER
            # than the desk's own latest figure did; where it would, the
            # desk's stands and the card says what was read.
            from . import rbo_live_feeds as rlf

            if rlf.handles(wl["feed"]):
                proof = rlf.proven().get(wl["feed"]) or {}
                has_desk = _num(desk.get(wl["row"])) and wl["row"] in carried
                try:
                    got, label, why = rlf.value(wl["feed"], holder, as_at.year, month)
                except Exception as exc:  # noqa: BLE001 - never lose the card
                    import logging

                    logging.getLogger(__name__).exception(
                        "retail back office feed %s", wl["feed"])
                    got, label, why = None, "", f"the feed could not be read ({type(exc).__name__})"
                if got is not None:
                    overrides[(wl["row"] - 1, actual_col)] = got
                    if proof.get("live"):
                        note = (f"proven: gave the desk's figure for {proof['matched']} "
                                f"of {proof['people']} people ({proof['month']})")
                        carried.pop(wl["row"], None)
                    else:
                        if not proof:
                            note = "not yet checked against the desk's figures"
                        elif not proof.get("evidence") and proof.get("matched"):
                            # Agreeing only where the desk had 0 proves nothing.
                            note = (f"not proven: the desk's {proof['month']} figures "
                                    f"it agreed with were all 0")
                        else:
                            note = (f"not proven: gave the desk's figure for "
                                    f"{proof['matched']} of {proof['people']} people "
                                    f"({proof['month']})")
                        if has_desk:
                            beside[wl["row"]] = True     # the "worse" guard applies
                        else:
                            carried.pop(wl["row"], None)
                            # The same guard against the person's own loaded
                            # card, where the workbook holds no desk figure
                            # for them: an unproven feed cannot score them
                            # below what the desk gave (Sarah Nzeli, Funded
                            # Accounts 0 read, 9 on her H1 June card). Not on
                            # turnaround lines, where lower is better.
                            own, then = rbo_card_figure(code, wl["feed"])
                            if (own is not None and got < own
                                    and not str(rlf.reader_of(wl["feed"]) or "").startswith("iapply:")):
                                overrides[(wl["row"] - 1, actual_col)] = own
                                note = (f"your own {then} scorecard, as the desk scored it - "
                                        f"the feed reads {got:,.0f}, {note}")
                    measured[wl["row"]] = f"{label} - {note}"
                elif not has_desk:
                    carried.pop(wl["row"], None)
                    own, then = rbo_card_figure(code, wl["feed"])
                    if own is not None:
                        # The return has no row for them; the desk put a
                        # figure on their own card (Sarah Nzeli, CRM 95 and
                        # engagement 0.57 on her H1 June card).
                        overrides[(wl["row"] - 1, actual_col)] = own
                        measured[wl["row"]] = (
                            f"your own {then} scorecard, as the desk scored it - {why}")
                    else:
                        no_tat[wl["row"]] = why
                continue
        if spec.book == SALES and _key(wl["feed"]) == "tatloans":
            # TAT (Loan) is the month's own figure off the iApply loan TAT
            # report's seller view (loan_tat_seller - the desk's report, step
            # by step). It used to carry the desk's September figure into
            # every later month, and a September 0 - no loan actions that
            # month - scored 100% under the card's =IF(J<=I,1,...): marks for
            # nothing measured. No actions this month is no figure: the line
            # waits and is not scored, as on the RM live card.
            from . import loan_tat_seller
            from .loan_applications import seller_codes

            # Every code iApply files this person under (a former DSR code
            # too - see loan_applications.seller_codes).
            codes = seller_codes(code)
            found_tat = loan_tat_seller.tat_for_codes(codes, as_at.year, month)
            carried.pop(wl["row"], None)
            if found_tat is None:
                no_tat[wl["row"]] = ("The iApply loan TAT report for "
                                     f"{datetime.date(as_at.year, month, 1):%B %Y} "
                                     "is being read; the line fills in when it is.")
            elif not found_tat[1]:
                no_tat[wl["row"]] = (
                    f"No loan actions under {', '.join(codes)} in "
                    f"{datetime.date(as_at.year, month, 1):%B %Y} on the iApply "
                    f"loan TAT report, so there is no turnaround to score.")
            else:
                overrides[(wl["row"] - 1, actual_col)] = float(found_tat[0])
                former = [c for c in found_tat[1] if c != codes[0]]
                measured[wl["row"]] = ("iApply loan TAT report, seller view, "
                                       "the month's own figure"
                                       + (f" - includes {', '.join(former)}, the same "
                                          f"person's former seller code" if former else ""))
            continue
        if _key(wl["feed"]) == "weightedtat":
            # Weighted TAT is the desk's monthly dashboard (see weighted_tat):
            # by sales code on a person's card, by branch on a branch manager's.
            from . import weighted_tat

            on_branch = spec.book == BRANCH_BUSINESS
            value = weighted_tat.score(
                as_at, code=None if on_branch else code,
                branch=holder.branch if on_branch else None)
            if value is not None:
                if template_live is None:
                    import copy

                    template_live = copy.deepcopy(actuals)
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    dashboard[wl["row"]] = as_at.replace(day=1)
                    continue
        if (WHIZZ_ON_CARDS and spec.book == BACK_OFFICE
                and _key(wl["feed"]) == "digitalcustomers"):
            # Customers onboarded on Whizz (whizz_onboarding): the person's
            # own officer rows by sales code, AD login or name.
            from . import whizz_onboarding as wo
            from .management.commands.load_whizz_onboarding import logins_for

            row = _template_row(template_live, wl["feed"], code, 0, person)
            names = (holder.name, row[2] if row and len(row) > 2 else None)
            logins = set()
            for n in names:
                if n:
                    logins |= logins_for(template_live, str(n))
            value, loaded = wo.running_total(as_at.year, month,
                                             codes=(code, *logins), names=names)
            if value is not None:
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    measured[wl["row"]] = (f"customers you onboarded on Whizz "
                                           f"(Whizz onboarding report, loaded "
                                           f"{loaded})")
                    continue
        if (spec.book == BACK_OFFICE and _key(wl["feed"]) == "digitalcustomers"
                and _num(wl.get("ytd_target")) and wl["ytd_target"] >= 1):
            # Digital Onboarding: your weighted-sales customers registered on
            # the mobile app (bo_branch_measures.digital_onboarded) - a COUNT,
            # so only on a card whose target is a count (a CSO's 15 a month).
            # A teller's Digital Onboarding target is a RATE (0.8, Francis
            # Ochieng FO4213, 16 Nov 2026): a count written there would score
            # 120% on nothing like the desk's measure, so that line keeps the
            # desk's figure until the rate's own definition is known.
            from . import bo_branch_measures as bm

            value = bm.digital_onboarded_to(as_at.year, month, code)
            if value is not None:
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    measured[wl["row"]] = (
                        "your weighted-sales customers registered on the "
                        "mobile app, each counted once (registration data)")
                    continue
        if spec.book == BACK_OFFICE and (
                _key(wl["feed"]) == "reactivation"
                or (_key(wl["feed"]) == "casa"
                    and holder.sheet not in BO_CASA_NOT_OWN)):
            # Dormancy and CASA as the desk measures them (bo_branch_measures).
            from . import bo_branch_measures as bm

            row = _template_row(template_live, wl["feed"], code, 0, person)
            if _key(wl["feed"]) == "reactivation":
                value, how = bm.dormancy(as_at, (
                    row[4] if row and len(row) > 4 else None, holder.branch))
            else:
                opened = bm.funded_accounts(as_at.year, month)
                value = (None if opened is None
                         else opened.get(str(code or "").strip().upper(), 0))
                how = ("funded accounts you opened, take-on and staff "
                       "accounts left out (daily sales report)")
            if value is not None:
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    measured[wl["row"]] = how
                    continue
        if spec.book == BACK_OFFICE and _key(wl["feed"]) in BO_AUDIT_SHEETS:
            # Internal Audit's branch return (audit_returns), loaded on
            # Scorecards -> Audit returns. The desk's two audit sheets are that
            # return for the person's branch: Branch_Audit_Resolution is the
            # implementation rate (Eldoret 0.93, Embu 0.80, Rehani 0.82 from
            # June = the return's 93% / 80% / 82%), and Branch_Audit the grade
            # on the bank's audit band (scheme_cards "audit_band": 1.65 or
            # better 1, under 2.49 0.8, else 0 - Eldoret and Embu 1.65 -> 1,
            # Rehani 1.72 -> 0.8). A branch's audit stands until it is audited
            # again; no return that had closed by then and the desk's figure
            # stands.
            from . import audit_returns

            row = _template_row(template_live, wl["feed"], code, 0, person)
            branch = (row[4] if row and len(row) > 4 and row[4] else holder.branch)
            audit = audit_returns.latest_for_branch(branch, as_at=as_at)
            value, how = None, ""
            if audit and _key(wl["feed"]) == "branchaudit" and _num(audit.get("audit_score")):
                grade = float(audit["audit_score"])
                value = (1.0 if 0 <= grade <= BO_AUDIT_TARGET
                         else 0.8 if BO_AUDIT_TARGET < grade < 2.49 else 0.0)
                how = (f"Internal Audit's return ({audit['period']}, {audit['branch']}): "
                       f"grade {grade:g}, {value:g} on the bank's audit band")
            elif audit and _num(audit.get("implementation")):
                value = float(audit["implementation"])
                how = (f"Internal Audit's return ({audit['period']}, {audit['branch']}): "
                       f"implementation {value:.0%}")
            if value is not None:
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    measured[wl["row"]] = how
                    continue
        if spec.book == BACK_OFFICE and _key(wl["feed"]) in ("crm", "kyc"):
            # The CX team's returns (see cx_returns): CRM logs by the person,
            # data-update forms by branch, as running totals. The template's
            # own row says which branch (and spelling) the desk used for them.
            from . import cx_returns

            kind = _key(wl["feed"])
            if template_live is None:
                import copy

                template_live = copy.deepcopy(actuals)
            row = _template_row(template_live, wl["feed"], code, 0, person)
            value = cx_returns.running_total(
                kind, as_at.year, month,
                names=(holder.name, row[2] if row and len(row) > 2 else None),
                branches=(row[4] if row and len(row) > 4 else None,
                          holder.branch))
            if value is not None:
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    cx_return[wl["row"]] = cx_returns.LABELS[kind]
                    continue
        if (spec.book == BRANCH_BUSINESS
                and _key(wl["feed"]) in ("plotsalesvolume", "plotsalesvalue")):
            # A branch's property = HFDI units sold by its staff (the proven
            # branch feed, else the desk's latest figure) PLUS the branch's
            # affordable-housing applications as the AFH Applications report's
            # branch table counts them. The branch feeds read HFDI only, so
            # River Road's six AFH applications reached its RMs' cards but
            # never the branch manager's (13 Nov 2026).
            from .live_scorecard import _afh_property_ytd

            proven_feed = (feeds_live.get(_key(wl["feed"])) or {}).get(0)
            hfdi = reader(proven_feed) if proven_feed is not None else None
            hfdi_how = "HFDI sales" if hfdi is not None else None
            if hfdi is None:
                hfdi = _get_template(template_live, wl["feed"], code, month, 0, person)
                if _num(hfdi) and wl["row"] in carried:
                    hfdi_how = (f"HFDI sales to "
                                f"{datetime.date(as_at.year, carried[wl['row']], 1):%b %Y} "
                                f"(the desk's figure)")
            afh_units, afh_value, mapped = _afh_property_ytd(
                code, holder.name, as_at.year, branch=holder.branch, up_to=as_at)
            afh = afh_units if _key(wl["feed"]) == "plotsalesvolume" else afh_value
            if mapped and afh and _num(hfdi):
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                value = float(hfdi) + float(afh)
                if _put_template(template_live, wl["feed"], code, month,
                                 value, 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = value
                    carried.pop(wl["row"], None)
                    measured[wl["row"]] = (
                        f"{hfdi_how or 'HFDI sales'} plus {afh_units} affordable-"
                        f"housing application{'s' if afh_units != 1 else ''} at "
                        f"{holder.branch} (AFH Applications report), to "
                        f"{as_at:%d %b %Y}")
                    continue
        if (spec.book == BACK_OFFICE
                and (feeds_live.get(_key(wl["feed"])) or {}).get("kind")
                == "branch_loan_tat"):
            # Branch_Loan_TAT: the iApply loan TAT report's branch view, for
            # the branch the template's own row names (the List spells some
            # differently). No figure yet: the desk's latest month stands.
            from . import bo_live_feeds as blf

            feed = feeds_live[_key(wl["feed"])]
            row = _template_row(template_live if template_live is not None
                                else actuals, wl["feed"], code, 0, person)
            branch = row[4] if row and len(row) > 4 else None
            value = blf.branch_loan_tat_value(feed, branch, as_at)
            if value is not None:
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    measured[wl["row"]] = (
                        f"the iApply loan TAT report, branch view "
                        f"({blf._branch_spelling(branch).title()})")
            continue
        feed = feeds_live.get(_key(wl["feed"]))
        block = 0
        if feed is not None and spec.book == BRANCH_BUSINESS:
            only_first = set(feed) == {0}
            block = 0 if only_first else blocks.get(wl["row"])
            feed = feed.get(block) if block is not None else None
        if feed is not None:
            value = reader(feed)
            if value is not None and spec.book in (BRANCH_BUSINESS, BACK_OFFICE):
                # Into the template's cell for the month, not the card's:
                # the card's own formula takes the 2025 base off a balance
                # (deposits, loans), and writing over that cell would lose it.
                # The template's cell is also what the proof compared.
                if template_live is None:
                    import copy

                    template_live = copy.deepcopy(actuals)
                prior[wl["row"]] = (wl["feed"], block, _get_template(
                    template_live, wl["feed"], code, month, block, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), block, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    if feed.get("kind") in ("finance_pbt", "finance_loss"):
                        from . import branch_accounts

                        finance[wl["row"]] = (branch_accounts.figures(
                            as_at.year, as_at.month, exact=False)[0], feed["kind"])
                continue
            if value is not None:
                overrides[(wl["row"] - 1, actual_col)] = float(value)
                continue
        if spec.book == BRANCH_BUSINESS:
            continue
        # A month the desk did not fill is scored on the warehouse's figures
        # (decided 9 Nov 2026: the September template is the last; October and
        # after read live, as of the month the person asks for). A month the
        # desk filled kept its figure above. A line not yet matched to the desk
        # says so on the card.
        if spec.book == BACK_OFFICE and _key(wl["feed"]) in BO_DESK_TAT_SHEETS:
            # The desk's own measure (account_opening.desk_turnaround), for the
            # iApply user the desk keys this person's row on. No step that
            # month, or no row: the desk's latest month stands.
            from . import account_opening as ao

            row = _template_row(template_live if template_live is not None
                                else actuals, wl["feed"], code, 0, person)
            user = str(row[1] or "").strip() if row and len(row) > 1 else ""
            try:
                value, _steps = ao.desk_turnaround(user, _key(wl["feed"]),
                                                   as_at.replace(day=1))
            except ao.AccountOpeningUnavailable:
                value = None
            if value is not None:
                if template_live is None:
                    import copy

                    template_live = copy.deepcopy(actuals)
                prior[wl["row"]] = (wl["feed"], 0, _get_template(
                    template_live, wl["feed"], code, month, 0, person))
                if _put_template(template_live, wl["feed"], code, month,
                                 float(value), 0, person):
                    live_rows.add(wl["row"])
                    written[wl["row"]] = float(value)
                    tat_report[wl["row"]] = (user, as_at.replace(day=1))
            continue
        unproven = (wl["row"] in carried
                    and sales_live_feeds.line_key(wl) not in bo_engine)
        # Sheet and name together first: both mortgage lines read
        # Asset_Drawdown, and only the name tells commercial from not.
        match = _engine_match(pool, wl)
        if match is None:
            continue
        pool.remove(match)
        value = match["line"].get("ytd_actual")
        if match["negate"] and _num(value):
            value = -value
        found[wl["row"]] = match["line"]
        # A warehouse nought where the desk has a figure is a reader that found nothing,
        # not a result: Digital Adoption read 0 against the desk's 585.
        if _num(value) and not (value == 0 and _num(desk.get(wl["row"])) and desk[wl["row"]]):
            overrides[(wl["row"] - 1, actual_col)] = float(value)
            if unproven:
                beside[wl["row"]] = float(value)
    from_start = _loan_book_from_start(spec, card_lines=base["lines"],
                                       engine_for_row=engine_for_row, code=code,
                                       prorate_of=(lambda r: Evaluator(
                                           book, actuals, holder, month).cell(r - 1, 14)),
                                       as_at=as_at,
                                       cap_of=lambda rate: asset_growth_cap(
                                           book, holder.role, rate))
    for row, (cells, _why) in from_start.items():
        overrides.update(cells)
        live_rows.add(row)
        carried.pop(row, None)
    card = compute(book, template_live or actuals, holder, month, overrides)

    # A year-to-date count or sum cannot fall below what the desk already
    # recorded for the year. Where a live reader gives less - property put
    # on nobody because the seller's name is spelt differently, a register
    # not yet reloaded - the desk's figure stands.
    # A line counts up through the year when its sheet is one that only grows
    # (ACCUMULATING_SHEETS, and on a back-office card BO_ACCUMULATING_SHEETS).
    # NOT inferred from a growing YTD target: a balance-growth target is
    # prorated too, and a balance can fall - Asset Growth's live figure was
    # thrown away for the desk's September one on that inference.
    by_month = {}

    def at_month(then):
        if then not in by_month:
            # With that month's unfilled running totals given the person's last
            # figure, as the stored cards are: Naomi Kagiri's November card
            # carried 38m Value of Property Sales, then re-scored it at September
            # off the template's unfilled September cell and showed 0.
            by_month[then] = {w["row"]: w for w in compute(
                book, running_totals_filled(template_live or actuals, then),
                holder, then, target_cells)["lines"]}
        return by_month[then]

    def accumulates(wl):
        key = _key(wl["feed"])
        return key in ACCUMULATING_SHEETS or key in STICKY_SHEETS or (
            spec.book == BACK_OFFICE and key in BO_ACCUMULATING_SHEETS)

    dropped, refused = [], {}
    # A balance-growth line (STICKY_SHEETS) whose live growth is below the
    # desk's: the card shows the real growth and holds the SCORE (19 Nov 2026).
    # River Road's deposits: September's 3.81bn growth was a quarter-end
    # balance (4.48bn at Sep, 1.56bn at Oct, as at Mar and Jun before it);
    # holding the whole line showed September's spike as his growth today.
    # row -> (the desk's year to date, its score at this month's target, month)
    held = {}
    for wl in card["lines"]:
        r = wl["row"]
        is_live =(r - 1, actual_col) in overrides or r in live_rows
        shrank = (is_live and r in carried
                  and _num(wl["actual"]) and _num(desk.get(r))
                  and wl["actual"] < desk[r]
                  and accumulates(wl))
        # A definition never proven against the desk cannot make a line WORSE
        # than the figure the desk already recorded (11 Nov 2026: PAR 0.02 ->
        # 1, Leave 1 -> 0.71 on an RM card). Compared on the score at this
        # month's target, so direction (PAR lower-is-better) and a target that
        # grew (VIC: same premiums, higher target) are both handled by the
        # card's own formula. Proven lines, the desk's Weighted TAT dashboard
        # and the accounts TAT report still move both ways.
        if spec.book == SALES:
            proven_line = not sales_live_feeds.note(sales_proven, wl)
        else:
            proven_line = r not in beside
        worse = (is_live and r in carried and not proven_line
                 and r not in dashboard and r not in tat_report
                 and r not in approvals_rows
                 and _num(wl.get("score")) and _num(desk_score.get(r))
                 and wl["score"] < desk_score[r] - 1e-9)
        # A back-office line is live only if the card's own formula found the
        # figure: never a "live" label on the desk's number.
        unread = (spec.book == BACK_OFFICE and r in written and not (
            _num(wl["actual"]) and abs(wl["actual"] - written[r]) < 1e-6))
        if (shrank and not worse and not unread
                and _key(wl["feed"]) in STICKY_SHEETS):
            held[r] = (desk[r], desk_score.get(r), carried[r])
            continue
        if (shrank or worse) and _num(wl["actual"]):
            # Said on the card, so "why is this not live" answers itself.
            refused[r] = (wl["actual"], "below the desk's" if shrank
                          else "scores lower on a definition not yet matched "
                               "to the desk's")
        shrank = shrank or worse
        if shrank or unread:
            dropped.append(r)
            overrides.pop((r - 1, actual_col), None)
            if r in live_rows:
                live_rows.discard(r)
                sheet, block, old = prior[r]
                _put_template(template_live, sheet, code, month, old, block, person)

    # A running total whose warehouse year to date reads below the desk's is a
    # definition that counts differently, not sales that vanished. What was
    # sold AFTER the desk's month still counts: the desk's year to date plus
    # the warehouse's movement since then (13 Nov 2026: Michael Odhiambo's
    # commercial-rate mortgages stuck at the desk's September 120.2m although
    # he drew more in October).
    topped = {}
    earlier_engine = {}
    for wl in card["lines"]:
        r = wl["row"]
        line = found.get(r)
        then = carried.get(r)
        key = _key(wl["feed"])
        # Sums of what was sold only - not a weighted-sales ratio or a balance.
        sums = key in ACCUMULATING_SHEETS or (
            spec.book == BACK_OFFICE and key in BO_ACCUMULATING_SHEETS)
        if (r not in dropped or line is None or not then or then >= month
                or r in written or not sums or not _num(desk.get(r))
                or (kpis.get(line.get("kpi_code")) or ("", False))[1]):
            continue
        if then not in earlier_engine:
            from .live_scorecard import _engine_card

            end = (datetime.date(as_at.year, then, 28)
                   + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
            try:
                eng = _engine_card(code, as_at=end, warehouse_only=True)
            except Exception:  # noqa: BLE001 - no movement read: the desk's figure stands
                eng = {}
            earlier_engine[then] = {ln.get("kpi_code"): ln.get("ytd_actual")
                                    for p in eng.get("perspectives", [])
                                    for ln in p["lines"]}
        now_value, then_value = line.get("ytd_actual"), earlier_engine[then].get(
            line.get("kpi_code"))
        if not (_num(now_value) and _num(then_value)):
            continue
        movement = float(now_value) - float(then_value)
        if movement <= 0:
            continue
        overrides[(r - 1, actual_col)] = float(desk[r]) + movement
        topped[r] = (float(desk[r]), movement, then)
        refused.pop(r, None)
        dropped.remove(r)
    if dropped or topped:
        card = compute(book, template_live or actuals, holder, month,
                       overrides)

    # A line carrying the desk's year to date from an earlier month is
    # scored against that month's target: September's actual measured
    # against ten months of target reads a month short. The workbook's own
    # formulas, run for the month the figure is from, give the target,
    # score and weighted score the desk itself would have shown.
    # The retail back office desk TYPES most actuals - the group's year to
    # date as at its run (Constants B2) - so a typed figure there is the
    # desk's figure from that month too, and is scored at that month's
    # target the same way: 170 approvals to September against November's
    # 91.7 target read short of what the desk's own card gave.
    typed_then = rbo_run_month(book) if spec.book == RETAIL_BO else None
    typed_at = set()
    for wl in card["lines"]:
        r = wl["row"]
        then = carried.get(r)
        if wl["typed"] and typed_then and typed_then < month \
                and _num(wl.get("actual")):
            then = typed_then
            earlier = at_month(then).get(r) or {}
            if earlier.get("ytd_target") != wl.get("ytd_target"):
                typed_at.add(r)
        elif wl["typed"]:
            continue
        if (not then or then >= month
                or (r - 1, actual_col) in overrides or r in live_rows):
            continue
        earlier = at_month(then).get(r)
        if earlier is not None:
            # A joiner's own proration can make the figure's month an error
            # in the workbook itself: prorate_new 9 counts from October, and
            # the YTD formula divides by (months - prorate) = 9 - 9 = 0 for
            # September (Jackson Nyawa). That month is not theirs to be
            # scored at; the card's month, which is, stands.
            if (isinstance(earlier.get("score"), dict)
                    and not isinstance(wl.get("score"), dict)):
                continue
            for field in ("ytd_target", "actual", "score", "weighted"):
                wl[field] = earlier[field]

    # The held lines: the real growth stays as the actual; the score is the
    # higher of the two, the weighted part following it the card's own way.
    for wl in card["lines"]:
        h = held.get(wl["row"])
        if not h or not (_num(wl.get("score")) and _num(h[1]) and _num(wl.get("weighted"))):
            continue
        if h[1] > wl["score"] + 1e-9:
            wl["weighted"] = (wl["weighted"] * h[1] / wl["score"] if wl["score"]
                              else h[1] * wl["weight"])
            wl["score"] = h[1]
            wl["held"] = h

    total, waiting = 0.0, 0
    for wl in card["lines"]:
        live = ((wl["row"] - 1, actual_col) in overrides
                or wl["row"] in live_rows)
        if wl["typed"] or live:
            if _num(wl["weighted"]):
                total += wl["weighted"]
            continue
        if wl["row"] in carried and _num(wl["actual"]):
            wl["carried"] = carried[wl["row"]]
            if _num(wl["weighted"]):
                total += wl["weighted"]
            continue
        waiting += 1
        engine = found.get(wl["row"]) or {}
        wl["actual"] = wl["score"] = wl["weighted"] = None
        if wl["row"] in awarded:
            entry = awarded[wl["row"]][0]
            wl["waiting"] = (f"Waiting for the CX team's {entry['feed']} score; "
                             f"up to {datetime.date(*entry['until'], 1):%B %Y} "
                             f"it was scored in full because {entry['why']}."
                             if entry.get("until") else
                             f"Waiting for the CX team's {entry['feed']} score.")
            continue
        wl["waiting"] = (no_tat.get(wl["row"]) or engine.get("pending") or
                         "The warehouse has no figure for this line yet.")
    card["total"] = total
    # A line the workbook itself shows as an error (#DIV/0!, #N/A ...) makes
    # the workbook's own total that error too - SUM over an error is the
    # error - so the desk's run writes no score for that person. Adding up
    # only the lines that happen to have a number gave Jackson Nyawa (JN3696,
    # PB ARM, joined September 2026) 28.1% for October on 27.5% of his
    # weight: his targets grow a 2025 book he does not have, so 13 lines
    # divide by a target of 0, and the desk's Monthly_Summ has no score for
    # him in any month. The card now does what the workbook does.
    def error_of(wl):
        return next((v["e"] for v in (wl.get("actual"), wl.get("score"),
                                      wl.get("weighted"))
                     if isinstance(v, dict) and v.get("e")), "")

    # A line the workbook can't read because the person has no row on that
    # sheet (#N/A) is a gap in the template, not a verdict: the desk's own run
    # scored Joseph Gatundu where our copy had no Productivity row for him. It
    # waits like any line with no figure - named, not counted, and the card
    # stays incomplete so it is not sent.
    for wl in card["lines"]:
        if wl.get("waiting") or error_of(wl) != "#N/A":
            continue
        wl["waiting"] = (f"{holder.name} has no row on the {wl.get('feed') or 'actuals'} "
                         f"sheet of the actuals template (by name, sales code or PF), "
                         f"so this line has no figure.")
        wl["actual"] = wl["score"] = wl["weighted"] = None
        waiting += 1
    # Any other error - #DIV/0!, a target of 0 - makes the workbook's own
    # total that error too (SUM over an error is the error), so the desk's run
    # writes no score for that person. Adding up only the lines that happen to
    # have a number gave Jackson Nyawa (JN3696, PB ARM, joined September 2026)
    # 28.1% for October on 27.5% of his weight: his targets grow a 2025 book
    # he does not have, so 13 lines divide by a target of 0, and the desk's
    # Monthly_Summ has no score for him in any month.
    # A #DIV/0! line whose base was READ on the customers allocated to the
    # person and is genuinely zero - a book that started this year, so 38% of
    # a December loan book of 0, or last year's income of 0 grown 20% - is not
    # a missing figure: the bank's rule gives it no target. It is left off and
    # the card is scored on the rest of its weight, brought back to 100%.
    # Jackson Nyawa (JN3696): his 49 allocated customers' 6 loans all date
    # from 2026, and they had no 2025 revenue. A line that is blank because
    # something could NOT be read stays an error: no score from missing data.
    not_applicable = []
    for wl in card["lines"]:
        if wl.get("waiting") or error_of(wl) != "#DIV/0!":
            continue
        why = (engine_for_row.get(wl["row"]) or {}).get("base_is_zero")
        if why:
            wl["not_applicable"] = why
            wl["actual"] = wl["score"] = wl["weighted"] = None
            not_applicable.append(wl)
    errored = [wl for wl in card["lines"] if not wl.get("waiting") and error_of(wl)]
    applicable_note = ""
    if not_applicable and not errored:
        left_out = sum(_num(wl.get("weight")) and wl["weight"] or 0.0
                       for wl in not_applicable)
        if left_out < 1 - 1e-9:
            card["total"] = total / (1 - left_out)
            applicable_note = (
                f"Not applicable: {', '.join(wl['measure'] or wl['initiative'] for wl in not_applicable)} "
                f"({left_out:.1%} of the weight) - the base these lines grow is "
                f"zero on the customers allocated to {holder.name}, so the "
                f"bank's rule sets no target. The card is scored on the other "
                f"{1 - left_out:.1%} of its weight, brought back to 100%.")
    not_scored = ""
    if errored:
        card["total"] = None
        codes = sorted({error_of(wl) for wl in errored})
        names = [wl["measure"] or wl["initiative"] for wl in errored]
        not_scored = (
            f"Not scored: the workbook itself shows {' / '.join(codes)} on "
            f"{len(errored)} line{'s' if len(errored) != 1 else ''} "
            f"({', '.join(names)}), so its total is an error as well and the "
            f"desk's run gives no score."
            + (" #DIV/0! means the line's target is 0 - no target is set for "
               "this person on it (a target grows the person's own prior-year "
               "figure, which a new joiner does not have)."
               if "#DIV/0!" in codes else ""))

    record = type("LiveRecord", (), {})()
    record.book, record.card, record.total = spec.book, card, card["total"]
    record.recorded, record.month = None, as_at.replace(day=1)
    record.sales_code, record.staff_name = code.upper(), holder.name
    record.sheet, record.branch = holder.sheet, str(holder.branch or "")
    payload = card_payload(record)
    for p in payload["perspectives"]:
        for ln, wl in zip(p["lines"], [w for w in card["lines"]
                                       if (w["perspective"] or "Other")
                                       == p["perspective"]]):
            engine_ln = engine_for_row.get(wl["row"]) or {}
            if (str(ln.get("pending") or "").startswith("The workbook itself shows #DIV/0!")
                    and engine_ln.get("pending_label") == "No target set"
                    and engine_ln.get("pending")):
                ln["pending"] = (f"No target for this line: {engine_ln['pending']}")
            if wl.get("not_applicable"):
                ln["pending"] = (f"Not applicable: {wl['not_applicable']}, so "
                                 f"the bank's rule sets no target. Left off; "
                                 f"the card is scored on its other lines.")
                ln["pending_label"] = "Not applicable"
                ln["score"] = ln["weighted"] = None
            if wl["row"] in from_start:
                ln["target_source"] = from_start[wl["row"]][1]
            elif wl["row"] in target_from:
                ln["target_source"] = (f"{target_from[wl['row']]} - not on the "
                                       f"workbook's Summary Allocation, so the "
                                       f"target comes from the DMC tables")
            if wl.get("waiting"):
                ln["pending"] = wl["waiting"]
                ln["pending_label"] = "Waiting for data"
                ln["as_at"] = ""
            elif wl.get("carried"):
                # Every template sheet is year to date except turnaround
                # time, which is the month's own rate.
                kind = ("latest month" if "tat" in _key(wl["feed"])
                        or _key(wl["feed"]) in BO_DESK_TAT_SHEETS
                        else "year to date")
                ln["as_at"] = (
                    f"{kind}, the desk's latest figure "
                    f"({datetime.date(as_at.year, wl['carried'], 1):%b %Y})")
                if wl["row"] in refused:
                    got, why = refused[wl["row"]]
                    ln["as_at"] += (f" - the warehouse reads {got:,.4g} to "
                                    f"{as_at:%d %b %Y}, {why}, so the desk's "
                                    f"figure stands" if abs(got) < 10
                                    else f" - the warehouse reads {got:,.0f} to "
                                    f"{as_at:%d %b %Y}, {why}, so the desk's "
                                    f"figure stands")
                elif spec.book == BRANCH_BUSINESS and not wl["typed"]:
                    from . import bb_live_feeds

                    ln["as_at"] += " - " + bb_live_feeds.why_not_live(
                        wl["feed"], blocks.get(wl["row"])
                        or table_of.get(wl["row"]) or 0)

            elif wl["typed"]:
                # Part of the card itself: nothing read it from anywhere.
                ln["as_at"] = "typed on the desk's card"
                if wl["row"] in typed_at:
                    ln["as_at"] += (
                        f", year to date to "
                        f"{datetime.date(as_at.year, typed_then, 1):%b %Y} - "
                        f"scored against that month's target, as the desk's "
                        f"card scored it")
            elif wl.get("held"):
                desk_ytd, _score, then = wl["held"]
                ln["as_at"] = (
                    f"live, as at {as_at:%d %b %Y}; the score is held at the "
                    f"desk's year to date to "
                    f"{datetime.date(as_at.year, then, 1):%b %Y} "
                    f"({desk_ytd:,.0f}), which scored higher")
            elif finance.get(wl["row"]) and finance[wl["row"]][0]:
                closed, kind = finance[wl["row"]]
                ln["as_at"] = (
                    f"Finance's Branch Accounts, year to "
                    f"{datetime.date(as_at.year, closed, 1):%B %Y} "
                    + ("(PBT after provisions, before head-office cost, plus "
                       "bancassurance commission)" if kind == "finance_pbt"
                       else "(loan loss: P&L charge less interest adjustment)"))
            elif awarded.get(wl["row"], (None, None))[1] == "full":
                ln["as_at"] = (f"full score awarded: "
                               f"{awarded[wl['row']][0]['why']} (CX team, 19 Nov 2026)")
            elif wl["row"] in dashboard:
                ln["as_at"] = (f"the desk's Weighted TAT Dashboard, "
                               f"{dashboard[wl['row']]:%B %Y}")
            elif wl["row"] in measured:
                ln["as_at"] = f"{measured[wl['row']]}, {as_at:%B %Y}"
            elif wl["row"] in cx_return:
                ln["as_at"] = (f"the CX team's {cx_return[wl['row']]} return, "
                               f"year to {as_at:%B %Y}")
            elif wl["row"] in topped:
                base, moved, then = topped[wl["row"]]
                ln["as_at"] = (
                    f"the desk's year to date to "
                    f"{datetime.date(as_at.year, then, 1):%b %Y} ({base:,.0f}) "
                    f"plus {moved:,.0f} from the warehouse since, to "
                    f"{as_at:%d %b %Y}")
            elif wl["row"] in tat_report:
                user, then = tat_report[wl["row"]]
                ln["as_at"] = (f"the accounts TAT report, your iApply steps "
                               f"({user}), {then:%B %Y}, to {as_at:%d %b %Y}")
            else:
                ln["as_at"] = f"live, as at {as_at:%d %b %Y}"
                if spec.book == SALES:
                    note = sales_live_feeds.note(sales_proven, wl)
                    if note:
                        ln["as_at"] += f" - {note}"
                elif wl["row"] in beside:
                    ln["as_at"] += (" - warehouse figure, not yet matched to the "
                                    "desk's")
    read_now = [w for w in card["lines"]
                if not w.get("carried") and not w.get("waiting") and not w["typed"]]
    desk_months = sorted({w["carried"] for w in card["lines"] if w.get("carried")})
    read_from = len(card["lines"]) - sum(1 for w in card["lines"] if w["typed"])
    desk_note = (f" {sum(1 for w in card['lines'] if w.get('carried'))} show the desk's "
                 f"latest figure (up to "
                 f"{datetime.date(as_at.year, desk_months[-1], 1):%B %Y})."
                 if desk_months else "")
    # A line left off because its base is zero is NOT weight without a
    # source: the bank's rule sets it no target, and the card is already
    # brought back to 100% without it. Counting it as unscored made Naomi
    # Kamau's (NK4492) card say "15.0% has no source" under a banner saying
    # why those two lines are not applicable.
    na_weight = sum(_num(w.get("weight")) and w["weight"] or 0.0
                    for w in not_applicable)
    payload.update({
        "live": True,
        "live_lines": len(read_now),
        "pending_lines": waiting,
        "scored_lines": len(card["lines"]) - waiting - len(not_applicable),
        "not_applicable_lines": len(not_applicable),
        "not_applicable_weight": round(na_weight, 4),
        "unscored_weight": round(max(0.0, float(
            payload.get("unscored_weight") or 0) - na_weight), 4),
        # Every month of the year to now: stored where the desk closed it,
        # live where it has not.
        "months_loaded": [f"{as_at.year}-{m:02d}"
                          for m in range(1, as_at.month + 1)],
        "coverage_note": " ".join(x for x in (
            not_scored, applicable_note,
            "" if not waiting else
            f"{waiting} line(s) have no live figure yet and are not counted; "
            f"they fill in as the warehouse has them.") if x),
        "not_scored": not_scored,
        "not_applicable": applicable_note,
        "how_scored": (f"{len(read_now)} of {read_from} lines read today's figures."
                       f"{desk_note} All are scored by {spec.source}'s own targets, "
                       f"caps and weights. Closed months show the card the desk sent."),
    })
    return payload
