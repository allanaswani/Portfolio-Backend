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
* **Dates are mixed** - real dates, '30/1/2023' as text, Excel serials that
  lost their formatting, and '9/31/2026', which is not a date at all because
  September has thirty days. Unparseable values are left blank and reported,
  never guessed.
"""

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
STAGE_MAP = {
    "discussion": (P.BROAD_DISCUSSION, "discussion"),
    "application": (P.BROAD_APPLICATION, ""),
    "at branch": (P.BROAD_APPLICATION, "at_branch"),
    "credit analysis": (P.BROAD_APPLICATION, "at_credit_analyst"),
    "credit analyis": (P.BROAD_APPLICATION, "at_credit_analyst"),   # sic
    "analysis": (P.BROAD_APPLICATION, "at_credit_analyst"),
    "rm analysis": (P.BROAD_APPLICATION, "at_credit_analyst"),
    "at credit analyst": (P.BROAD_APPLICATION, "at_credit_analyst"),
    "credit risk": (P.BROAD_APPLICATION, "at_credit_risk"),
    "at credit risk": (P.BROAD_APPLICATION, "at_credit_risk"),
    "approved": (P.BROAD_APPROVED, ""),
    "disbursed": (P.BROAD_DISBURSED, "disbursement"),
    "disbursement": (P.BROAD_DISBURSED, "disbursement"),
}

DEPOSIT_PRODUCTS = {"casa": "CASA", "fd": "FD"}


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
        if sheet not in wb.sheetnames:
            warnings.append(f"{sheet}: not in this workbook - skipped.")
            continue
        rows = list(wb[sheet].iter_rows(values_only=True))
        if not rows:
            continue

        header = [text(c) for c in rows[0]]
        if not header or header[0].lower() != first_header.lower():
            warnings.append(
                f"{sheet}: first column is {header[:1]!r}, expected "
                f"{first_header!r} - skipped rather than guessed.")
            continue

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

            if "deposit_product" in columns.values():
                dp = text(values.get("deposit_product")).lower()
                entry.deposit_product = DEPOSIT_PRODUCTS.get(dp, "")
                if dp and not entry.deposit_product:
                    warnings.append(
                        f"{sheet} row {n}: product {dp!r} is neither CASA nor FD.")

            if "expected_date" in columns.values():
                raw_date = values.get("expected_date")
                entry.expected_date = when(raw_date)
                if raw_date is not None and entry.expected_date is None:
                    warnings.append(
                        f"{sheet} row {n}: {text(raw_date)!r} is not a date - "
                        f"left blank for {customer}.")

            stage_raw = text(values.get("_broad_stage_raw")).lower()
            if stage_raw:
                mapped = STAGE_MAP.get(stage_raw)
                if mapped:
                    entry.broad_stage, entry.stage = mapped
                else:
                    warnings.append(
                        f"{sheet} row {n}: stage {stage_raw!r} not recognised - "
                        f"left blank for {customer}.")

            entries.append(entry)

    return entries, warnings, skipped
