"""Load the existing Commercial Pipeline workbook into the app.

    python manage.py import_commercial_pipeline "/path/Commercial Pipeline ....xlsx"
    python manage.py import_commercial_pipeline <file> --apply

A dry run unless --apply is given, because it writes to a live table and the
first thing anybody wants is to see what it read.

Four sheets, four kinds. The mapping is taken from the workbook dated
07.09.2026 and is asserted against the header row, so a file with different
columns is refused rather than silently loaded into the wrong fields.

The messy parts of the file, and what happens to each:

* **Stages are free text and disagree with the Explanations sheet.** 'Credit
  Risk' and 'Credit Analyis' (sic) appear in the BROAD column, where neither is
  a broad stage. Both are mapped to their real place: broad 'Application',
  specific 'At credit risk' / 'At credit analyst'.
* **Products are spelled several ways** - contract financing appears five
  ways. They are imported verbatim. Normalising somebody's product name on the
  way in would be deciding, silently, that a spelling was wrong.
* **Dates are mixed** - real dates, '30/1/2023' as text, and '9/31/2026',
  which is not a date at all because September has thirty days. Unparseable
  values are left blank and reported, never guessed.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.commercial_pipeline.models import PipelineEntry as P

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
    # Liabilities puts the RM first and the branch second - the only sheet
    # that does, which is exactly the kind of thing a positional import gets
    # wrong if nobody checks.
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


def _text(value):
    if value is None:
        return ""
    # Non-breaking spaces are in this file - '\xa0FD' is a real cell value.
    return str(value).replace("\xa0", " ").strip()


def _money(value):
    if value is None or _text(value) == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("KES", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _when(value):
    """A date, or None. Never a guess."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%d-%b-%Y",
                "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # An Excel serial date that lost its formatting and came through as text -
    # '44957' is 30 Jan 2023. The epoch is 1899-12-30, not 1900-01-01: Excel
    # treats 1900 as a leap year, which it was not, and the offset absorbs it.
    if text.isdigit() and 20000 <= int(text) <= 60000:
        return date(1899, 12, 30) + timedelta(days=int(text))

    return None


class Command(BaseCommand):
    help = "Load the Commercial Pipeline workbook into the pipeline table."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the .xlsx file.")
        parser.add_argument("--apply", action="store_true",
                            help="Write. Without it nothing is saved.")
        parser.add_argument("--replace", action="store_true",
                            help="Clear previously imported rows of each sheet "
                                 "first, so re-running does not duplicate them.")

    def handle(self, *args, **o):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("openpyxl is needed: pip install openpyxl")

        try:
            wb = openpyxl.load_workbook(o["path"], data_only=True, read_only=True)
        except Exception as exc:
            raise CommandError(f"Could not open that file: {exc}")

        made, skipped, warnings = 0, 0, []
        created_rows = []

        for sheet, (kind, first_header, columns) in SHEETS.items():
            if sheet not in wb.sheetnames:
                warnings.append(f"{sheet}: not in this workbook — skipped.")
                continue
            ws = wb[sheet]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue

            header = [_text(c) for c in rows[0]]
            if not header or header[0].lower() != first_header.lower():
                warnings.append(
                    f"{sheet}: first column is {header[:1]!r}, expected "
                    f"{first_header!r} — skipped rather than guessed.")
                continue

            for n, raw in enumerate(rows[1:], start=2):
                values = {}
                for idx, field in columns.items():
                    values[field] = raw[idx] if idx < len(raw) else None

                customer = _text(values.get("customer_name"))
                if not customer:
                    skipped += 1
                    continue

                entry = P(
                    kind=kind,
                    customer_name=customer[:200],
                    rm_name=_text(values.get("rm_name"))[:150],
                    branch=_text(values.get("branch"))[:120] or "Commercial",
                    segment="COMMERCIAL",
                    comments=_text(values.get("comments")),
                    amount=_money(values.get("amount")),
                    amount_to_disburse=_money(values.get("amount_to_disburse")),
                    revenue=_money(values.get("revenue")),
                    product=_text(values.get("product"))[:160],
                    account_no=_text(values.get("account_no"))[:40],
                )

                if "deposit_product" in columns.values():
                    dp = _text(values.get("deposit_product")).lower()
                    entry.deposit_product = DEPOSIT_PRODUCTS.get(dp, "")
                    if dp and not entry.deposit_product:
                        warnings.append(
                            f"{sheet} row {n}: product {dp!r} is neither CASA nor FD.")

                if "expected_date" in columns.values():
                    raw_date = values.get("expected_date")
                    entry.expected_date = _when(raw_date)
                    if raw_date is not None and entry.expected_date is None:
                        warnings.append(
                            f"{sheet} row {n}: {_text(raw_date)!r} is not a date "
                            f"— left blank for {customer}.")

                stage_raw = _text(values.get("_broad_stage_raw")).lower()
                if stage_raw:
                    mapped = STAGE_MAP.get(stage_raw)
                    if mapped:
                        entry.broad_stage, entry.stage = mapped
                    else:
                        warnings.append(
                            f"{sheet} row {n}: stage {stage_raw!r} not recognised "
                            f"— left blank for {customer}.")

                created_rows.append(entry)
                made += 1

        self.stdout.write(self.style.MIGRATE_HEADING("\nWhat this read"))
        by_kind = {}
        for e in created_rows:
            by_kind[e.get_kind_display()] = by_kind.get(e.get_kind_display(), 0) + 1
        for label, count in sorted(by_kind.items()):
            self.stdout.write(f"  {label:<20} {count:>4}")
        self.stdout.write(f"  {'rows without a customer':<20} {skipped:>4} (skipped)")

        if warnings:
            self.stdout.write(self.style.WARNING(
                f"\n{len(warnings)} thing(s) needing a human eye:"))
            for w in warnings[:40]:
                self.stdout.write(f"  {w}")
            if len(warnings) > 40:
                self.stdout.write(f"  … and {len(warnings) - 40} more")

        if not o["apply"]:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN — nothing written. {made} row(s) would be created. "
                f"Re-run with --apply."))
            return

        with transaction.atomic():
            if o["replace"]:
                gone = P.objects.filter(
                    kind__in={e.kind for e in created_rows},
                    created_by__isnull=True,          # only ever imported rows
                ).delete()[0]
                self.stdout.write(f"\nRemoved {gone} previously imported row(s).")
            P.objects.bulk_create(created_rows, batch_size=200)

        self.stdout.write(self.style.SUCCESS(f"\nCreated {made} row(s)."))
