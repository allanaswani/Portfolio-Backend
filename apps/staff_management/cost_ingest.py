"""Getting the SAP cost extract in, from Trino or from the file.

Two routes on purpose:

* **Trino** — ``manage.py load_sap_costs``, running the Finance team's own
  query against ``delta.gold_db.sap_cost_data``. This is the one that should
  run on a schedule.
* **A file** — the Administration screen, for a correction or for when the lake
  is not reachable. The notebook itself works from a compiled Excel, so the
  same columns arrive either way.

Both go through :func:`rows_to_postings`, so a figure cannot depend on which
route brought it in.

The snapshot rule
─────────────────
Each SAP extract is a **full replacement for its date**, not an increment. That
is why the Finance query ends with ``WHERE d.dt = m.max_dt`` and why a load
deletes that snapshot before writing it. Appending instead would double every
posting the next time the same extract arrived.
"""

from __future__ import annotations

import datetime
import re

#: The Finance team's extraction query, verbatim from
#: ``trino_cost_extraction_query.txt`` apart from the trailing semicolon, which
#: the Trino client does not accept.
#:
#: Two things in it are worth not "tidying":
#:
#: * the date comes out of the SOURCE FILE NAME, which carries it as either
#:   dd-mm-yyyy or dd-mm-yy - hence the two ``date_parse`` attempts under a
#:   COALESCE;
#: * the final ``WHERE d.dt = m.max_dt`` takes only the newest extract, because
#:   each one is a full snapshot.
TRINO_QUERY = """
with data as (
select
    dp.BUKRS as company_code,
    dp.BELNR as document_number,
    dp.BUZEI as item_number,
    dp.BSCHL as posting_key,
    dp.KOART as cost_element_category,
    dp.SHKZG as debit_credit_indicator,
    dp.MWSKZ as tax_code,
    dp.QSSKZ as withholding_tax_code,
    dp.QSSHB as withholding_tax_base_amount,
    dp.WRBTR as fcy_amount,
    dp.PSWSL as payment_currency,
    dp.DMBTR as lcy_amount,
    dp.GJAHR as fiscal_year,
    dp.KZBTR as currency_amount,
    dp.ZUONR as assignment_number,
    dp.SGTXT as item_description,
    dp.VORGN as origin,
    dp.KOSTL as cost_center,
    dp.HKONT as gl_account_number,
    dp.LIFNR as vendor_number,
    dp.HZUON as reference_document_number,
    dp.ZFBDT as due_date,
    dp.ZTERM as terms_of_payment,
    REPLACE(dp.source_file_name,'.xls','') as source_file,
    COALESCE(
        CAST(date_parse(regexp_extract(REPLACE(dp.source_file_name, '.xls', ''),
             '(\\d{2}-\\d{2}-\\d{4})'), '%d-%m-%Y') AS DATE),
        CAST(date_parse(regexp_extract(REPLACE(dp.source_file_name, '.xls', ''),
             '(\\d{2}-\\d{2}-\\d{2})'), '%d-%m-%y') AS DATE)
    ) AS dt
from delta.gold_db.sap_cost_data as dp
),
max_date AS (SELECT MAX(dt) AS max_dt FROM data)
SELECT d.* FROM data d CROSS JOIN max_date m WHERE d.dt = m.max_dt
"""

#: What the query returns, and what a filled template has to carry. The upload
#: accepts a subset: anything absent is left blank rather than refused, because
#: a correction file rarely carries all twenty-four columns.
COLUMNS = [
    "company_code", "document_number", "item_number", "posting_key",
    "cost_element_category", "debit_credit_indicator", "tax_code",
    "withholding_tax_code", "withholding_tax_base_amount", "fcy_amount",
    "payment_currency", "lcy_amount", "fiscal_year", "assignment_number",
    "item_description", "origin", "cost_center", "gl_account_number",
    "vendor_number", "reference_document_number", "due_date",
    "terms_of_payment", "source_file", "dt",
]

#: Columns a row cannot be read without. Everything else is optional.
REQUIRED = ("lcy_amount", "gl_account_number")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value):
    """A money or count figure, or None. Thousands separators and a trailing
    minus (SAP writes some credits as ``1,234.00-``) are both handled."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    if text.endswith("-"):
        text = "-" + text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _integer(value):
    number = _number(value)
    return int(number) if number is not None else None


def _digits(value):
    return "".join(ch for ch in _text(value) if ch.isdigit())


def _date_from_yyyymmdd(value):
    """``20260931`` style, which is how SAP writes the assignment number.

    Returns None for ``00000000``, for a blank, and for an impossible date -
    the notebook's ``errors='coerce'``. A posting with no usable date is
    reported rather than dropped silently, because it is money that exists.
    """
    digits = _digits(value)
    if len(digits) != 8 or digits == "00000000":
        return None
    try:
        return datetime.date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    except ValueError:
        return None


def entry_date_for(assignment_number, reference_document_number):
    """The notebook's ``get_date``: the assignment number, else the reference.

    Neither is reliably populated on its own, which is why it falls through.
    """
    return (_date_from_yyyymmdd(assignment_number)
            or _date_from_yyyymmdd(reference_document_number))


def amount_for(lcy_amount, debit_credit_indicator):
    """``lcy_amount``, NEGATED on a credit.

    The notebook's ``get_actual_amount``: SAP's SHKZG is ``H`` for a credit and
    ``S`` for a debit, and the extract gives the magnitude either way. Without
    the sign, a credit ADDS to a cost instead of reducing it and every total is
    out by twice the credits.
    """
    value = _number(lcy_amount)
    if value is None:
        return None
    return -value if _text(debit_credit_indicator).upper() == "H" else value


def _snapshot_from(value, source_file=""):
    """The extract's date: the query's ``dt``, or read off the file name.

    The file name carries it as dd-mm-yyyy or dd-mm-yy, which is the same pair
    the Trino query tries - so an upload and a Trino load date a snapshot the
    same way.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = _text(value)
    for shape in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text[:10], shape).date()
        except ValueError:
            continue
    found = re.search(r"(\d{2}-\d{2}-\d{4})", _text(source_file))
    if found:
        return datetime.datetime.strptime(found.group(1), "%d-%m-%Y").date()
    found = re.search(r"(\d{2}-\d{2}-\d{2})", _text(source_file))
    if found:
        return datetime.datetime.strptime(found.group(1), "%d-%m-%y").date()
    return None


def rows_to_postings(rows, loaded_by="", snapshot_date=None):
    """Turn extract rows into unsaved ``SapCostPosting`` objects.

    → ``(postings, report)``. Nothing is written; the caller decides.

    ``report`` counts what was skipped and why, because a load that quietly
    dropped a tenth of the postings would understate every department and look
    exactly like a quiet month.
    """
    from .models import SapCostPosting

    postings = []
    report = {
        "read": 0, "skipped_no_amount": 0, "skipped_no_gl": 0,
        "without_a_date": 0, "snapshot_dates": set(),
    }

    for raw in rows:
        row = {str(key).strip().lower(): value for key, value in raw.items()}
        report["read"] += 1

        gl = _digits(row.get("gl_account_number"))
        if not gl:
            report["skipped_no_gl"] += 1
            continue
        amount = amount_for(row.get("lcy_amount"),
                            row.get("debit_credit_indicator"))
        if amount is None:
            report["skipped_no_amount"] += 1
            continue

        entry = entry_date_for(row.get("assignment_number"),
                               row.get("reference_document_number"))
        if entry is None:
            report["without_a_date"] += 1

        snapshot = snapshot_date or _snapshot_from(
            row.get("dt"), row.get("source_file"))
        if snapshot is not None:
            report["snapshot_dates"].add(snapshot)

        postings.append(SapCostPosting(
            company_code=_integer(row.get("company_code")),
            document_number=_text(row.get("document_number"))[:30],
            item_number=_text(row.get("item_number"))[:10],
            fiscal_year=_integer(row.get("fiscal_year")),
            posting_key=_text(row.get("posting_key"))[:10],
            cost_element_category=_text(row.get("cost_element_category"))[:10],
            debit_credit_indicator=_text(row.get("debit_credit_indicator"))[:2],
            cost_centre=_integer(row.get("cost_center")
                                 or row.get("cost_centre")),
            gl_account_number=gl[:30],
            vendor_number=_text(row.get("vendor_number"))[:30],
            item_description=_text(row.get("item_description")),
            origin=_text(row.get("origin"))[:20],
            lcy_amount=_number(row.get("lcy_amount")),
            fcy_amount=_number(row.get("fcy_amount")),
            payment_currency=_text(row.get("payment_currency"))[:10],
            withholding_tax_base_amount=_number(
                row.get("withholding_tax_base_amount")),
            tax_code=_text(row.get("tax_code"))[:10],
            withholding_tax_code=_text(row.get("withholding_tax_code"))[:10],
            amount=amount,
            assignment_number=_text(row.get("assignment_number"))[:30],
            reference_document_number=_text(
                row.get("reference_document_number"))[:30],
            due_date=_text(row.get("due_date"))[:30],
            terms_of_payment=_text(row.get("terms_of_payment"))[:20],
            entry_date=entry,
            entry_month=entry.strftime("%Y-%m") if entry else "",
            source_file=_text(row.get("source_file"))[:255],
            snapshot_date=snapshot,
            loaded_by=loaded_by[:150],
        ))

    report["snapshot_dates"] = sorted(
        d.isoformat() for d in report["snapshot_dates"])
    report["kept"] = len(postings)
    return postings, report


def save_postings(postings, report):
    """Write one snapshot, replacing whatever was there for that date.

    A load REPLACES its snapshot rather than adding to it, because each SAP
    extract is a full copy. Appending would double every posting the next time
    the same extract arrived.

    Refuses a mixed load: postings from two different extract dates in one file
    means somebody concatenated two extracts, and replacing "the" snapshot
    would then delete half of what was just read.
    """
    from django.db import transaction

    from .models import SapCostPosting

    dates = {p.snapshot_date for p in postings if p.snapshot_date}
    if not dates:
        return {"written": 0, "replaced": 0,
                "detail": "None of those rows carry an extract date, so there "
                          "is no snapshot to write them as."}
    if len(dates) > 1:
        return {"written": 0, "replaced": 0,
                "detail": f"Those rows span {len(dates)} extract dates "
                          f"({', '.join(sorted(d.isoformat() for d in dates))}). "
                          f"Each extract is a full snapshot, so load them one "
                          f"at a time."}

    snapshot = dates.pop()
    with transaction.atomic():
        replaced = SapCostPosting.objects.filter(
            snapshot_date=snapshot).delete()[0]
        SapCostPosting.objects.bulk_create(postings, batch_size=2000)
    return {
        "written": len(postings),
        "replaced": replaced,
        "snapshot_date": snapshot.isoformat(),
        "detail": (f"Wrote {len(postings):,} posting(s) for {snapshot}, "
                   f"replacing {replaced:,} that were there before."),
    }


def read_workbook(stream):
    """Read a filled extract from .xlsx → a list of dicts.

    Header row found by looking for the columns rather than assuming row 1:
    the compiled file the notebook reads has its header where it has it, and a
    file that starts with a title row is the normal case rather than the
    exception.
    """
    from openpyxl import load_workbook

    book = load_workbook(stream, data_only=True, read_only=True)
    sheet = book[book.sheetnames[0]]

    header, rows = None, []
    for values in sheet.iter_rows(values_only=True):
        labels = [str(cell).strip().lower() if cell is not None else ""
                  for cell in values]
        if header is None:
            if any(label in labels for label in REQUIRED):
                header = labels
            continue
        if not any(cell is not None and str(cell).strip() for cell in values):
            continue
        rows.append({name: values[index]
                     for index, name in enumerate(header)
                     if name and index < len(values)})
    if header is None:
        raise ValueError(
            "That file has no header row naming lcy_amount and "
            "gl_account_number. The extract's own columns are expected - the "
            "same ones the Trino query returns.")
    return rows


def fetch_from_trino():
    """Run the Finance query against the lake → a list of dicts.

    Credentials come from the environment, never from this file:
    ``TRINO_HOST``, ``TRINO_PORT``, ``TRINO_USER``, ``TRINO_PASSWORD``.
    """
    import os

    import trino
    from trino.auth import BasicAuthentication

    host = os.environ.get("TRINO_HOST")
    if not host:
        raise RuntimeError(
            "TRINO_HOST is not set, so the lake cannot be reached. Set the "
            "TRINO_* variables in the environment file, or load the extract "
            "through the Administration screen instead.")

    user = os.environ.get("TRINO_USER", "")
    password = os.environ.get("TRINO_PASSWORD", "")
    if not user or not password:
        raise RuntimeError(
            "TRINO_USER or TRINO_PASSWORD is not set, so the lake cannot be "
            "reached. Both go in the environment file alongside TRINO_HOST.")

    # docker --env-file does NOT strip quotes: TRINO_PASSWORD="secret" passes
    # the quote characters as part of the password, and Trino answers 401. The
    # same goes for a trailing space. Stripped here rather than left to produce
    # an authentication error nobody can tell from a wrong password.
    for name, value in (("TRINO_USER", user), ("TRINO_PASSWORD", password)):
        if value != value.strip() or value[:1] in ("'", '"'):
            print(f"  note: {name} had surrounding quotes or whitespace in the "
                  f"environment; using the trimmed value. docker --env-file "
                  f"takes quotes literally, so they do not belong there.")
    user = user.strip().strip("'\"")
    password = password.strip().strip("'\"")

    connection = trino.dbapi.connect(
        host=host,
        port=int(os.environ.get("TRINO_PORT", "8443")),
        user=user,
        auth=BasicAuthentication(user, password),
        catalog=os.environ.get("TRINO_CATALOG", "delta"),
        http_scheme="https",
        verify=False,
    )
    cursor = connection.cursor()
    cursor.execute(TRINO_QUERY)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
