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

#: "Is there anything newer in the lake?", asked on its own.
#:
#: The ``dt`` expression is a deliberate COPY of the one in TRINO_QUERY rather
#: than a derivation of it. A probe that read the date differently from the
#: load would announce an extract the load could then not find, and the deck
#: would flip between two dates forever. The two move together or not at all.
#:
#: It exists so the CEO deck can ask the lake whether it is behind WITHOUT
#: pulling 44,769 postings to discover that it is not - one scalar, on every
#: check, against a 1.9-million-row table.
LATEST_SNAPSHOT_QUERY = """
SELECT MAX(
    COALESCE(
        CAST(date_parse(regexp_extract(REPLACE(dp.source_file_name, '.xls', ''),
             '(\\d{2}-\\d{2}-\\d{4})'), '%d-%m-%Y') AS DATE),
        CAST(date_parse(regexp_extract(REPLACE(dp.source_file_name, '.xls', ''),
             '(\\d{2}-\\d{2}-\\d{2})'), '%d-%m-%y') AS DATE)
    )
) AS max_dt
FROM delta.gold_db.sap_cost_data AS dp
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


def _connect():
    """A connection to the lake, from the environment.

    Credentials come from the environment, never from this file:
    ``TRINO_HOST``, ``TRINO_PORT``, ``TRINO_USER``, ``TRINO_PASSWORD``.

    Shared by the full pull and by the one-scalar freshness probe, so the deck
    cannot end up probing one lake and loading from another.
    """
    import os
    import urllib3

    import trino
    from trino.auth import BasicAuthentication

    # The lake's certificate is not one this host trusts, so the connection
    # below passes verify=False - deliberate, and unchanged here. urllib3 warns
    # once per REQUEST, and the Trino client polls for results, so a single
    # load printed the same warning a dozen times and buried the figures it
    # was asked for. Silenced for this call only: a global filter would hide
    # the warning for every other HTTPS call in the process, including ones
    # where it would be news.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

    return trino.dbapi.connect(
        host=host,
        port=int(os.environ.get("TRINO_PORT", "8443")),
        user=user,
        auth=BasicAuthentication(user, password),
        catalog=os.environ.get("TRINO_CATALOG", "delta"),
        http_scheme="https",
        verify=False,
    )


def fetch_from_trino():
    """Run the Finance query against the lake → a list of dicts."""
    cursor = _connect().cursor()
    cursor.execute(TRINO_QUERY)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ── Keeping the figures live ─────────────────────────────────────────────────
#
# The CEO deck was reporting operating costs frozen at whatever date somebody
# last ran ``load_sap_costs`` by hand. Nothing in the estate moved it on: the
# command was never added to host cron, and the deck has no way of knowing the
# lake holds newer extracts than the mirror it reads.
#
# What follows closes that, in three parts:
#
# * :func:`latest_lake_snapshot` asks the lake ONE scalar — what is the newest
#   extract date? — cheap enough to ask on a page view.
# * :func:`refresh_from_lake` pulls and loads, but only when that answer is
#   newer than what the mirror holds. A day with no new extract costs one
#   scalar and nothing else.
# * :func:`refresh_if_due` wraps that in a back-off and a lock, so twenty
#   people opening the deck at 09:00 produce one probe between them.
#
# The mirror is kept rather than queried through on every read, because every
# rule that turns a posting into a department figure — the credit sign, the
# date off the assignment number, the three GL exclusions, the cost-centre
# mapping — lives in Postgres beside it, and ``costs/postings/`` has to be able
# to show the documents behind any figure on the screen. What changes is that
# no human step stands between the lake and the deck any more.

#: Don't ask the lake more often than this. A new extract lands at most daily,
#: so a ten-minute floor is already far finer than the data moves.
PROBE_EVERY_SECONDS = 600

#: How many extracts to keep. Each is ~45,000 rows, and once this refreshes
#: itself daily they accumulate at that rate. Only the newest is ever reported
#: on; the older ones serve ``?snapshot=`` and comparing two loads. Set
#: ``COST_SNAPSHOT_KEEP = 0`` to keep every extract for ever.
#:
#: This is a real deletion, and an old extract CANNOT be pulled back from the
#: lake — the Finance query returns only ``max_dt``. Hence a generous default
#: and a setting, rather than a hard-coded 2.
DEFAULT_SNAPSHOT_KEEP = 12

_PROBE_KEY = "sap_costs:last_probe"
_LOCK_KEY = "sap_costs:refreshing"


def latest_lake_snapshot():
    """The newest SAP extract date **in the lake**, or None.

    One row, one column. This is what makes the auto-refresh affordable: the
    answer is almost always "the date you already have", and finding that out
    must not cost a 44,769-row pull.
    """
    cursor = _connect().cursor()
    cursor.execute(LATEST_SNAPSHOT_QUERY)
    row = cursor.fetchone()
    return _snapshot_from(row[0]) if row else None


def prune_old_snapshots(keep=None):
    """Keep the newest ``keep`` extracts, delete the rest.

    → ``(dates_removed, rows_removed)``.

    Only runs on an automatic refresh. A hand load leaves history alone,
    because somebody loading an extract by hand usually wants to compare it
    with the one before.
    """
    from django.conf import settings

    from .models import SapCostPosting

    if keep is None:
        keep = getattr(settings, "COST_SNAPSHOT_KEEP", DEFAULT_SNAPSHOT_KEEP)
    try:
        keep = int(keep or 0)
    except (TypeError, ValueError):
        keep = DEFAULT_SNAPSHOT_KEEP
    if keep <= 0:
        return [], 0

    dates = list(SapCostPosting.objects
                 .exclude(snapshot_date__isnull=True)
                 .values_list("snapshot_date", flat=True)
                 .distinct().order_by("-snapshot_date"))
    stale = dates[keep:]
    if not stale:
        return [], 0
    rows = SapCostPosting.objects.filter(snapshot_date__in=stale).delete()[0]
    return [d.isoformat() for d in stale], rows


def refresh_from_lake(force=False, loaded_by="auto-refresh", keep=None,
                      prune=True):
    """Load the newest extract from the lake **if the mirror is behind it**.

    → a dict saying what happened. It does **not** raise. The caller is usually
    a page view, and a lake that is briefly unreachable has to leave the deck
    showing the figures it already has rather than returning a 500 — a stale
    figure that says it is stale beats no figure at all.
    """
    from . import cost_analysis

    now = datetime.datetime.now(datetime.timezone.utc)
    mirror = cost_analysis.latest_snapshot()
    result = {
        "checked_at": now.isoformat(timespec="seconds"),
        "lake_snapshot": None,
        "mirror_snapshot": mirror.isoformat() if mirror else None,
        "refreshed": False, "read": 0, "written": 0, "replaced": 0,
        "pruned": [], "pruned_rows": 0, "busy": False,
        "detail": "", "error": "",
    }

    try:
        lake = latest_lake_snapshot()
    except RuntimeError as exc:
        # Not configured. A different problem from an unreachable lake, and it
        # has a different fix, so it gets its own answer.
        result["error"] = str(exc)
        result["detail"] = (
            "The lake is not configured on this host, so these figures are "
            "whatever was last loaded by hand.")
        return result
    except Exception as exc:  # noqa: BLE001 - the reason is what matters
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["detail"] = (
            "The lake could not be reached, so these figures are the last "
            "extract that loaded.")
        return result

    result["lake_snapshot"] = lake.isoformat() if lake else None

    if lake is None:
        result["detail"] = (
            "The lake holds no extract whose file name carries a date, so "
            "there is nothing to load. A file named BSEG_2026, with no day "
            "and month, cannot be dated and is invisible to this report by "
            "design.")
        return result

    if mirror is not None and lake <= mirror and not force:
        result["detail"] = (
            f"Already on the newest extract the lake has ({lake}).")
        return result

    try:
        rows = fetch_from_trino()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["detail"] = (
            f"The lake has a newer extract ({lake}) but it could not be "
            f"pulled, so these figures are still the one before it.")
        return result

    if not rows:
        # An empty pull must never wipe the snapshot that is there. The same
        # rule the command enforces.
        result["detail"] = (
            f"The lake's {lake} extract came back empty. Nothing has been "
            f"changed — an empty load must not replace a snapshot that has "
            f"figures in it.")
        return result

    postings, report = rows_to_postings(rows, loaded_by=loaded_by)
    result["read"] = report["read"]
    if not postings:
        result["detail"] = (
            f"Nothing in the lake's {lake} extract could be read "
            f"({report['read']:,} row(s) seen). Nothing has been changed.")
        return result

    saved = save_postings(postings, report)
    if not saved["written"]:
        result["error"] = saved["detail"]
        result["detail"] = saved["detail"]
        return result

    result["refreshed"] = True
    result["written"] = saved["written"]
    result["replaced"] = saved["replaced"]
    result["mirror_snapshot"] = saved["snapshot_date"]
    if prune:
        result["pruned"], result["pruned_rows"] = prune_old_snapshots(keep)
    result["detail"] = (
        f"Pulled the {saved['snapshot_date']} extract from the lake: "
        f"{saved['written']:,} posting(s), replacing {saved['replaced']:,}.")
    return result


def refresh_if_due(min_seconds=None, force=False, loaded_by="auto-refresh"):
    """:func:`refresh_from_lake`, but safe to call from a page view.

    Two guards, because this sits on the CEO deck's read path:

    * a **back-off** — the last probe's answer is cached, so the lake is asked
      at most once every ``COST_LAKE_PROBE_SECONDS`` however many people have
      the deck open;
    * a **lock** — if a pull is already running, everybody else serves the
      mirror as it stands rather than starting a second pull of the same
      extract.

    If the cache itself is not working the lock is skipped rather than treated
    as permanently held. A broken cache must not freeze the figures, which is
    the very failure this function exists to end.
    """
    from django.conf import settings
    from django.core.cache import cache

    from . import cost_analysis

    if min_seconds is None:
        min_seconds = getattr(
            settings, "COST_LAKE_PROBE_SECONDS", PROBE_EVERY_SECONDS)

    if not force:
        try:
            cached = cache.get(_PROBE_KEY)
        except Exception:  # noqa: BLE001
            cached = None
        if isinstance(cached, dict):
            return dict(cached, from_cache=True)

    try:
        got_lock = bool(cache.add(_LOCK_KEY, "1", timeout=1800))
        held = cache.get(_LOCK_KEY) is not None
    except Exception:  # noqa: BLE001
        got_lock, held = True, False

    if not got_lock and held:
        mirror = cost_analysis.latest_snapshot()
        return {
            "checked_at": None, "lake_snapshot": None,
            "mirror_snapshot": mirror.isoformat() if mirror else None,
            "refreshed": False, "read": 0, "written": 0, "replaced": 0,
            "pruned": [], "pruned_rows": 0, "busy": True, "from_cache": False,
            "detail": "A refresh from the lake is already running.",
            "error": "",
        }

    try:
        result = refresh_from_lake(force=force, loaded_by=loaded_by)
    finally:
        try:
            cache.delete(_LOCK_KEY)
        except Exception:  # noqa: BLE001
            pass

    result["from_cache"] = False
    try:
        cache.set(_PROBE_KEY, result, int(min_seconds))
    except Exception:  # noqa: BLE001
        # A cache that will not hold the marker costs another probe, nothing
        # more. It must not cost the refresh.
        pass
    return result
