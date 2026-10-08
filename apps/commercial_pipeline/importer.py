"""Reading the Commercial Pipeline workbook.

Lives here rather than inside the management command because the workbook is
uploaded through the page as well: getting a file onto the application host
needs SSH and a password not everybody has, so the people who actually keep
this spreadsheet could never run the command. One parser, two callers, so an
upload and a command can never disagree about what a row means.

The mapping is taken from the workbook dated 07.09.2026 and is asserted against
the header row, so a file with different columns is refused rather than quietly
loaded into the wrong fields.

The messy parts of the file, and what happens to each:

* **Stages are free text and disagree with the Explanations sheet.** 'Credit
  Risk' and 'Credit Analyis' (sic) appear in the BROAD column, where neither is
  a broad stage. Both are mapped to their real place.
* **Products are spelled several ways** - contract financing appears five ways.
  They are imported verbatim: normalising somebody's product name on the way in
  would be deciding, silently, that a spelling was wrong.
* **The Liabilities sheet has no VIC column**, because it predates the split.
  Those rows import with ``insurance_type`` blank and the RM sets it when they
  next open the line. Deriving it from the product text would be inventing it.
* **Dates are mixed** - real dates, '30/1/2023' as text, Excel serials that
  lost their formatting, and '9/31/2026', which is not a date at all because
  September has thirty days. Unparseable values are left blank and reported,
  never guessed.
"""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from .models import PipelineEntry as P

#: sheet -> (kind, expected first header, column index -> field)
SHEETS = {
    "Assets Pipeline": (P.KIND_ASSET, "Branch", {
        0: "branch", 1: "rm_name", 2: "customer_name",
        3: "amount", 4: "amount_to_disburse", 5: "product",
        6: "_broad_stage_raw", 7: "comments",
    }),
    "Trade Pipeline": (P.KIND_TRADE, "Branch", {
        0: "branch", 1: "rm_name", 2: "customer_name",
        3: "amount", 4: "revenue", 5: "product",
        6: "_broad_stage_raw", 7: "comments",
    }),
    "Deposits": (P.KIND_DEPOSIT, "Branch", {
        0: "branch", 1: "rm_name", 2: "customer_name",
        3: "expected_date", 4: "deposit_product", 5: "amount", 6: "comments",
    }),
    # Liabilities puts the RM first and the branch second - the only sheet that
    # does, which is exactly the kind of thing a positional import gets wrong
    # if nobody checks.
    "Liabilities": (P.KIND_LIABILITY, "RM", {
        0: "rm_name", 1: "branch", 2: "customer_name", 3: "account_no",
        4: "amount", 5: "expected_date", 6: "comments",
    }),
}

#: Every stage spelling found in the file, mapped to (broad, specific).
#:
#: The spellings below the rule are not in the workbook - they are the stage
#: names from "Additional System requirements.xlsx". They are here so that the
#: NEXT version of the file, which the desk will keep in the new vocabulary,
#: imports without a warning on every row. Importing a file is the one place
#: where being generous about spelling is right: refusing a row because
#: somebody wrote "Credit Evaluation" instead of a slug loses a real deal.
STAGE_MAP = {
    # As found in the 07.09.2026 workbook.
    "discussion": (P.BROAD_DISCUSSION, "discussion"),
    "application": (P.BROAD_APPLICATION, ""),
    "at branch": (P.BROAD_APPLICATION, "at_branch"),
    "credit analysis": (P.BROAD_CREDIT_ANALYSIS, ""),
    "credit analyis": (P.BROAD_CREDIT_ANALYSIS, ""),               # sic
    "analysis": (P.BROAD_APPLICATION, "at_credit_analyst"),
    "rm analysis": (P.BROAD_APPLICATION, "at_credit_analyst"),
    "at credit analyst": (P.BROAD_APPLICATION, "at_credit_analyst"),
    "credit risk": (P.BROAD_APPLICATION, "at_credit_risk"),
    "at credit risk": (P.BROAD_APPLICATION, "at_credit_risk"),
    "approved": (P.BROAD_APPROVED, ""),
    # "Remove-Disbursed": both spellings now land on Disbursement, and the
    # specific stage is left blank rather than set to the retired one.
    "disbursed": (P.BROAD_DISBURSEMENT, ""),
    "disbursement": (P.BROAD_DISBURSEMENT, ""),

    # --- the requirements sheet's own words ---
    "rm only": (P.BROAD_RM_ONLY, "relationship_manager"),
    "rm": (P.BROAD_RM_ONLY, "relationship_manager"),
    "relationship manager": (P.BROAD_RM_ONLY, "relationship_manager"),
    "relationship manager (rm)": (P.BROAD_RM_ONLY, "relationship_manager"),
    "credit analyst": (P.BROAD_CREDIT_ANALYSIS, "credit_analyst"),
    "credit origination manager": (P.BROAD_CREDIT_ANALYSIS,
                                   "credit_origination_manager"),
    "credit evaluation": (P.BROAD_CREDIT_EVALUATION, ""),
    "ccm": (P.BROAD_CREDIT_EVALUATION, "ccm"),
    "dcr": (P.BROAD_CREDIT_EVALUATION, "dcr"),
    "bmd": (P.BROAD_CREDIT_EVALUATION, "bmd"),
    "mlc": (P.BROAD_CREDIT_EVALUATION, "mlc"),
    "board": (P.BROAD_CREDIT_EVALUATION, "board"),
    # PRE sits at three points in the journey. With nothing but the one cell
    # to go on, the broad stage is left blank rather than guessed at, and the
    # row is reported - see parse_workbook.
    "pre": (None, "pre"),
    "branch / rm": (P.BROAD_APPROVED, "branch_rm"),
    "branch/rm": (P.BROAD_APPROVED, "branch_rm"),
    "valuation adoption": (P.BROAD_APPROVED, "valuation_adoption"),
    "instructions to lawyers": (P.BROAD_APPROVED, "instructions_to_lawyers"),
    "joint registration": (P.BROAD_APPROVED, "joint_registration"),
    "bank attorneys execution": (P.BROAD_APPROVED, "bank_attorneys_execution"),
    "confirmation of securities": (P.BROAD_DISBURSEMENT,
                                   "confirmation_of_securities"),
    "disbursement officer": (P.BROAD_DISBURSEMENT, "disbursement_officer"),
    "insurance confirmation": (P.BROAD_DISBURSEMENT, "insurance_confirmation"),
    "trade middle officer": (P.BROAD_DISBURSEMENT, "trade_middle_officer"),
    "cpc": (P.BROAD_DISBURSEMENT, "cpc"),
}

#: Other names the same sheet may arrive under. The app now calls these two
#: pipelines "Deposits Pipeline" and "Insurance Pipeline", so the next copy of
#: the workbook the desk saves is likely to have the tabs renamed to match.
#: Without this, a renamed tab is reported as "not in this workbook" and every
#: row on it is silently dropped - a whole pipeline missing from the Team
#: Leader's totals, with nothing to show that it ever existed.
SHEET_ALIASES = {
    "Assets Pipeline": ("Assets", "Asset Pipeline"),
    "Trade Pipeline": ("Trade",),
    "Deposits": ("Deposits Pipeline", "Deposit Pipeline"),
    "Liabilities": ("Insurance Pipeline", "Insurance", "Liability"),
}

#: VIC / non-VIC, as somebody would write it in a cell. Read from whichever
#: column carries it rather than from a fixed position: the old sheet has no
#: such column at all, so there is no position to assume, and the one Finance
#: eventually adds will be wherever they put it.
INSURANCE_TYPES = {
    "vic": P.INSURANCE_VIC,
    "non-vic": P.INSURANCE_NON_VIC,
    "non vic": P.INSURANCE_NON_VIC,
    "nonvic": P.INSURANCE_NON_VIC,
    "non-vic cover": P.INSURANCE_NON_VIC,
}


#: A header cell that is naming the VIC column, and not one that merely
#: contains those three letters - "Service" does.
VIC_HEADER = re.compile(r"\bnon[\s\-]?vic\b|\bvic\b|insurance\s+type", re.I)


def insurance_type(value):
    """VIC, non-VIC, or "" - never a guess.

    Non-VIC is tested first on purpose: "non-vic" contains "vic", and matching
    the shorter one would file every non-VIC cover as Britam business.
    """
    raw = text(value).lower().strip().rstrip(".")
    if not raw:
        return ""
    if raw in INSURANCE_TYPES:
        return INSURANCE_TYPES[raw]
    if "non" in raw and "vic" in raw:
        return P.INSURANCE_NON_VIC
    if raw == "vic" or raw.startswith("vic ") or "britam" in raw:
        return P.INSURANCE_VIC
    return ""


#: The workbook's two, plus the requirements sheet's cash margin and escrow.
DEPOSIT_PRODUCTS = {
    "casa": "CASA",
    "fd": "FD",
    "fixed deposit": "FD",
    "cash margin": "CASH_MARGIN",
    "cash margins": "CASH_MARGIN",
    "escrow": "ESCROW",
}


def text(value):
    if value is None:
        return ""
    # Non-breaking spaces are in this file - '\xa0FD' is a real cell value.
    return str(value).replace("\xa0", " ").strip()


def money(value):
    if value is None or text(value) == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("KES", "").strip())
    except (InvalidOperation, ValueError):
        return None


def when(value):
    """A date, or None. Never a guess."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%d-%b-%Y",
                "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # An Excel serial date that lost its formatting and came through as text -
    # '44957' is 30 Jan 2023. The epoch is 1899-12-30, not 1900-01-01: Excel
    # treats 1900 as a leap year, which it was not, and the offset absorbs it.
    if raw.isdigit() and 20000 <= int(raw) <= 60000:
        return date(1899, 12, 30) + timedelta(days=int(raw))

    return None


def parse_workbook(source):
    """Read a workbook into unsaved PipelineEntry objects.

    ``source`` is a path or any file-like object, so the same code serves the
    management command and an upload.

    Returns ``(entries, warnings, skipped)``. Nothing is written - the caller
    decides, which is what lets both callers offer a dry run.
    """
    import openpyxl

    wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    entries, warnings, skipped = [], [], 0

    for sheet, (kind, first_header, columns) in SHEETS.items():
        found_as = next(
            (name for name in (sheet, *SHEET_ALIASES.get(sheet, ()))
             if name in wb.sheetnames),
            None)
        if found_as is None:
            warnings.append(f"{sheet}: not in this workbook - skipped.")
            continue
        if found_as != sheet:
            warnings.append(f"{sheet}: read from the tab named {found_as!r}.")
        rows = list(wb[found_as].iter_rows(values_only=True))
        if not rows:
            continue

        header = [text(c) for c in rows[0]]
        if not header or header[0].lower() != first_header.lower():
            warnings.append(
                f"{found_as}: first column is {header[:1]!r}, expected "
                f"{first_header!r} - skipped rather than guessed.")
            continue

        # Whichever column says VIC, if any. By header, not by position: the
        # old sheet has no such column, so there is no position to assume.
        #
        # The word boundaries matter. A plain "vic" in name.lower() also
        # matches a column headed "Service", which contains the letters v-i-c.
        vic_at = None
        if kind == P.KIND_LIABILITY:
            vic_at = next(
                (i for i, name in enumerate(header)
                 if VIC_HEADER.search(name)),
                None)

        for n, raw in enumerate(rows[1:], start=2):
            values = {field: (raw[idx] if idx < len(raw) else None)
                      for idx, field in columns.items()}

            customer = text(values.get("customer_name"))
            if not customer:
                skipped += 1
                continue

            entry = P(
                kind=kind,
                customer_name=customer[:200],
                rm_name=text(values.get("rm_name"))[:150],
                branch=text(values.get("branch"))[:120] or "Commercial",
                segment="COMMERCIAL",
                comments=text(values.get("comments")),
                amount=money(values.get("amount")),
                amount_to_disburse=money(values.get("amount_to_disburse")),
                revenue=money(values.get("revenue")),
                product=text(values.get("product"))[:160],
                account_no=text(values.get("account_no"))[:40],
            )

            if vic_at is not None:
                cell = raw[vic_at] if vic_at < len(raw) else None
                entry.insurance_type = insurance_type(cell)
                if text(cell) and not entry.insurance_type:
                    warnings.append(
                        f"{found_as} row {n}: {text(cell)!r} is neither VIC nor "
                        f"non-VIC - left blank for {customer}.")

            if "deposit_product" in columns.values():
                dp = text(values.get("deposit_product")).lower()
                entry.deposit_product = DEPOSIT_PRODUCTS.get(dp, "")
                if dp and not entry.deposit_product:
                    warnings.append(
                        f"{found_as} row {n}: deposit type {dp!r} is not one of "
                        f"CASA, FD, cash margin or escrow.")

            if "expected_date" in columns.values():
                raw_date = values.get("expected_date")
                entry.expected_date = when(raw_date)
                if raw_date is not None and entry.expected_date is None:
                    warnings.append(
                        f"{found_as} row {n}: {text(raw_date)!r} is not a date - "
                        f"left blank for {customer}.")

            stage_raw = text(values.get("_broad_stage_raw")).lower()
            if stage_raw:
                mapped = STAGE_MAP.get(stage_raw)
                if mapped:
                    broad, specific = mapped
                    if broad is None:
                        # A unit that sits at more than one point in the
                        # journey. The specific stage is certain, the broad one
                        # is not, and a guess here would put the row in the
                        # wrong bucket of the Team Leader's totals.
                        entry.stage = ""
                        warnings.append(
                            f"{found_as} row {n}: {stage_raw!r} happens at more "
                            f"than one stage - left blank for {customer}, set "
                            f"it on the line.")
                    else:
                        entry.broad_stage, entry.stage = broad, specific
                else:
                    warnings.append(
                        f"{found_as} row {n}: stage {stage_raw!r} not recognised - "
                        f"left blank for {customer}.")

            entries.append(entry)

    return entries, warnings, skipped
