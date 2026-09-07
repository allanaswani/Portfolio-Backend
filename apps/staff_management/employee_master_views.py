"""Employee master upload — the HR staff workbook (``employee_table``).

Port of the old backend's ``staff_management.views.UploadAndProcessEmployeeData``,
still mounted at the same path: ``employee-data/upload-csv/``.

WHAT THE OLD ENDPOINT ACTUALLY DID
----------------------------------
It saved the upload into ``../etls/temp_files`` and ran
``initiate_update_employee_information.sh``, which is a thin wrapper around the
data team's ``cleaning_and_updating_staff_information.py`` (``datawarehouse-etls``).
That script is the real contract, and this module is a port of it. The shell-out
itself cannot survive the move: this backend runs in a container with neither the
``etls`` tree nor the host's python3.6, so a verbatim port of the *view* would
answer "Failed to execute processing script" on every upload. (The
queue-a-request-file pattern in ``core/script_trigger`` is for the report
scripts, which email their own output; this button has to report how many rows
landed, so it does the load itself.)

THE FILE HR UPLOADS
-------------------
An Excel workbook with up to three sheets, each carrying the same header row:

* ``full_list``   — the whole company. Only people **not already in**
  ``employee_table`` are INSERTED from it. Nobody is updated from this sheet and
  nobody is ever deleted, which is why re-uploading last month's file is safe.
* ``exits``       — people who have left.
* ``promotions``  — people who moved role.

``exits`` and ``promotions`` are combined and UPDATE ten columns on the existing
row: ``exit``, ``staff_exit_date``, ``promotion``, ``promotion_date``,
``service_code``, ``department``, ``unit``, ``org_unit``, ``grade``,
``job_title``. A lone CSV is read as a single ``full_list`` sheet.

Headers are HR's own, not the database's — ``staffid``, ``idno``, ``date of
employement`` (sic), ``service yrs``, ``org unit``, ``effective date`` — and
several columns are DERIVED rather than read: ``age`` and ``service_years`` are
recomputed from the dates, ``exit`` / ``promotion`` / ``new`` are flags off those
dates, ``grade`` is normalised to two digits, and ``division`` is forced to match
``department`` for HFBI and HFDI. All of that is ported from the script, so a
file that loaded before loads the same way.

The script also maintains ``hfdi_employee_data`` from the HFDI rows of the same
workbook (insert the new ones, mark the exits inactive); that runs here too.

Two production quirks the host script never had to think about are handled:

* ``employee_table.id`` may have no sequence or identity default (see
  [[prod-schema-drift]]) — Postgres then substitutes NULL and only INSERTs fail.
  The view checks once and supplies the id itself when there is no default.
* the router reads unmanaged models from ``datawarehouse`` and writes them to
  ``default``. Those are one physical database on production, but "insert the
  people who are not already there" reads and writes in a single pass, which is
  only correct if both halves see the same table — so both are pinned.
"""

import re
from datetime import date, datetime, timezone as dt_timezone

from django.conf import settings
from django.db import connections, router, transaction
from django.db.models import Max
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
import pandas as pd

from apps.gceo_dashboard.models import EmployeeTable
from apps.hfdi.models import HfdiEmployeeData
from core.permissions import DataManagementPermissions

TAG = ["Staff Management — Employee Master"]

# ── The workbook, exactly as the ETL script expects it ────────────────────────
SHEET_FULL_LIST = "full_list"
SHEET_EXITS = "exits"
SHEET_PROMOTIONS = "promotions"
SHEETS = (SHEET_FULL_LIST, SHEET_EXITS, SHEET_PROMOTIONS)

# HR's own header row (lower-cased and stripped, which is all the script does).
# "date of employement" is misspelled in the source file — kept, or the column
# would stop matching.
WORKBOOK_COLUMNS = [
    "staffid", "name", "idno", "email", "date of birth", "age", "gender",
    "date of employement", "service code", "service yrs", "division",
    "department", "unit", "org unit", "grade", "job title", "staff_exit_date",
    "effective date",
]

# Header -> model field. "new job title" is the alternative spelling the script
# also accepts on the promotions sheet.
COLUMN_MAPPING = {
    "staffid": "staff_id",
    "idno": "national_id",
    "date of birth": "date_of_birth",
    "date of employement": "date_of_employment",
    "service code": "service_code",
    "service yrs": "service_years",
    "org unit": "org_unit",
    "job title": "job_title",
    "new job title": "job_title",
    "effective date": "promotion_date",
}

# Columns the INSERT writes, in the script's order.
INSERT_COLUMNS = [
    "staff_id", "name", "national_id", "email", "date_of_birth", "age", "gender",
    "date_of_employment", "service_code", "service_years", "division", "department",
    "unit", "org_unit", "grade", "job_title", "exit", "promotion", "new",
    "staff_exit_date", "promotion_date", "hfdi_erp_id",
]

# Columns the exits/promotions UPDATE touches — and only these.
UPDATE_COLUMNS = [
    "exit", "staff_exit_date", "promotion", "promotion_date",
    "service_code", "department", "unit", "org_unit", "grade", "job_title",
]

# Department -> division override (the script's own two-entry map).
DEPARTMENT_TO_DIVISION = {"HFBI": "HFBI", "HFDI": "HFDI"}

DIVISION_RENAME = {"HFBI": "HFCB Insurance", "HFDI": "HFCB Properties", "HFC": "HFCB Limited", "HF Group": "HFCB Group"}

# Grade normalisation, then zero-padded to two characters.
GRADE_MAPPING = {"O2": "02", "UNC": "01", "O3": "03", "Tempor": "01", "O1": "01"}

HFDI_DEPARTMENT = "HFDI"
PROPERTIES_DIVISION = "HFCB Properties"

DATE_FIELDS = ["date_of_birth", "date_of_employment", "staff_exit_date", "promotion_date"]

# Every field the cleaner guarantees on a row, so a sheet missing an optional
# column loads with that column blank instead of raising.
GUARANTEED_FIELDS = [
    "staff_id", "national_id", "date_of_birth", "date_of_employment",
    "service_code", "service_years", "org_unit", "job_title", "promotion_date",
    "email", "age", "gender", "division", "department", "unit", "grade",
    "staff_exit_date",
]


def normalize_sheet_name(name):
    """"Full List", "full_list" and " FULL-LIST " are one sheet."""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def normalize_header(name):
    """Lower-case and collapse whitespace, then apply the script's rename map."""
    text = str(name or "").replace("﻿", "").replace("​", "")
    text = " ".join(text.strip().strip('"').strip("'").lower().split())
    return COLUMN_MAPPING.get(text, text.replace(" ", "_"))


def canon_staff_id(value):
    """``4022``, ``4022.0`` and ``4022.00000`` are all the same person -> 4022."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in ("nan", "none", "null"):
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def employee_db():
    """The one alias every ``employee_table`` statement here uses.

    The router reads unmanaged models from ``datawarehouse`` and returns ``None``
    for their writes, which falls through to ``default``. On production both
    aliases are the same database, so the split is invisible — but "insert the
    people who are not already there" reads and writes in one pass, and that is
    only correct if both halves see the same table.
    """
    return router.db_for_write(EmployeeTable) or "default"


def _id_is_database_generated():
    """Does ``employee_table.id`` fill itself in, or must we supply it?

    Postgres substitutes NULL when a NOT NULL pk has neither a ``nextval``
    default nor an identity, and BigAutoField deliberately omits id from the
    INSERT — the shape of the hfdi target 500 (see [[prod-schema-drift]]).
    """
    try:
        with connections[employee_db()].cursor() as cur:
            cur.execute(
                """
                SELECT (column_default IS NOT NULL)
                       OR (COALESCE(is_identity, 'NO') = 'YES')
                FROM   information_schema.columns
                WHERE  table_name = %s AND column_name = 'id'
                """,
                [EmployeeTable._meta.db_table],
            )
            row = cur.fetchone()
    except Exception:
        return True  # can't tell — let the database try
    return True if row is None else bool(row[0])


# ── Reading the workbook ──────────────────────────────────────────────────────

def read_sheets(upload):
    """``{sheet_name: DataFrame}`` from an .xlsx/.xls workbook, or a lone .csv.

    A CSV has no sheets, so it is read as a single ``full_list`` — which is what
    a one-tab file means. ``grade`` is read as text, or "02" arrives as the
    number 2.
    """
    import pandas as pd  # heavy; only needed on an actual upload

    name = (getattr(upload, "name", "") or "").lower()
    try:
        upload.seek(0)
    except Exception:
        pass
    if name.endswith(".csv"):
        return {SHEET_FULL_LIST: pd.read_csv(upload, dtype={"grade": "str"})}
    sheets = pd.read_excel(upload, sheet_name=None, engine="openpyxl",
                           dtype={"grade": "str"})
    return {normalize_sheet_name(k): v for k, v in sheets.items()}


def clean_staff_list(frame):
    """The script's ``clean_staff_list``, for one sheet.

    Returns a list of row dicts keyed by model field name, every derived column
    already computed.
    """
    import numpy as np
    import pandas as pd

    frame = frame.copy()
    frame.columns = [normalize_header(c) for c in frame.columns]

    # A row with no name is a spacer or total line in HR's sheet, not a person.
    if "name" not in frame.columns:
        raise ValueError("the sheet has no 'name' column")
    frame = frame[~frame["name"].isna()].copy()

    # A missing optional column is added empty rather than raising: the script
    # would KeyError and abandon the whole file, which tells the uploader nothing.
    for field in GUARANTEED_FIELDS:
        if field not in frame.columns:
            frame[field] = None

    # Division follows the department for the two entities that are their own
    # division, then every division takes its rebranded HFCB name. The rename
    # has to happen here: _sync_hfdi selects on the new name, and HR's sheet
    # still carries the old one.
    frame["division"] = frame.apply(
        lambda row: DEPARTMENT_TO_DIVISION.get(str(row["department"]).strip(), row["division"]),
        axis=1,
    )
    frame["division"] = frame["division"].map(
        lambda value: DIVISION_RENAME.get(str(value).strip(), value)
    )

    frame["grade"] = frame["grade"].map(_normalize_grade)

    for field in DATE_FIELDS:
        frame[field] = pd.to_datetime(frame[field], errors="coerce")

    # age and service_years are RECOMPUTED — the sheet's own values are ignored,
    # exactly as the script does, so the roster cannot drift from the dates.
    now = pd.Timestamp.now()
    frame["age"] = (now - frame["date_of_birth"]).dt.days // 365
    frame["service_years"] = (now - frame["date_of_employment"]).dt.days // 365

    frame["national_id"] = (
        pd.to_numeric(frame["national_id"], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .astype("Int64").astype("object")
    )

    frame["hfdi_erp_id"] = 0
    frame["exit"] = frame["staff_exit_date"].notna().astype(int)
    frame["promotion"] = frame["promotion_date"].notna().astype(int)
    frame["new"] = (
        frame["date_of_employment"].notna()
        & (frame["date_of_employment"].dt.year == now.year)
    ).astype(int)

    rows = []
    for record in frame.to_dict("records"):
        row = {key: _py(value) for key, value in record.items()}
        row["staff_id"] = canon_staff_id(row.get("staff_id"))
        rows.append(row)
    return rows


def _normalize_grade(value):
    """``O2`` -> ``02``, ``5`` -> ``05`` — the script's map, then two digits."""
    import pandas as pd

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return None
    return GRADE_MAPPING.get(text, text).zfill(2)


def _py(value):
    """A pandas scalar -> a plain Python value the ORM will accept."""
    import pandas as pd

    if value is None or value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):  # a numpy scalar
        value = value.item()
    if isinstance(value, str):
        return value.strip() or None
    return value


def _as_datetime(value):
    """A date-only value going into a timestamp column.

    Anchored to UTC midnight so the calendar day survives the round trip; local
    (EAT) midnight would be stored as 21:00 the PREVIOUS day and read back a day
    early.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        return None
    if settings.USE_TZ and timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


# ── hfdi_employee_data ────────────────────────────────────────────────────────

def clean_division_staff_list(rows, division):
    """The script's ``clean_division_staff_list`` — one division's rows,
    reshaped into the ``hfdi_employee_data`` columns."""
    wanted = (division or "").strip().lower()
    today = date.today()
    out = []
    for row in rows:
        if str(row.get("division") or "").strip().lower() != wanted:
            continue
        employment_date = _as_date(row.get("date_of_employment"))
        exit_date = _as_date(row.get("staff_exit_date"))
        staff_id = row.get("staff_id")
        out.append({
            "staff_pf_number": staff_id,
            "lead_officer_id": 0,
            "staff_name": _proper_case(row.get("name")),
            "staff_unit": row.get("unit"),
            "staff_role": row.get("job_title"),
            "sales_code": None if staff_id is None else str(staff_id),
            "primary_project": "",
            "team_leader": "",
            "employment_date": employment_date,
            "start_date": _hfdi_start_date(employment_date, today),
            "exit_date": exit_date,
            "active": 0 if exit_date else 1,
            "staff_exit": 1 if exit_date else 0,
            "target_sales": 0,
            "target_collections": 0,
            "input_user": "Strategy Employee Update",
        })
    return out


def _proper_case(name):
    """" (the script's own cleanup)."""
    if not name:
        return None
    return " ".join(str(name).split()).title()


def _hfdi_start_date(employment_date, today):
    """1 January for anyone employed before this year, else the 1st of the
    month after they joined — where their sales year starts."""
    if employment_date is None:
        return None
    if employment_date.year < today.year:
        return date(today.year, 1, 1)
    # The month after the hire month: a partial first month is not a sales month.
    year, month = employment_date.year, employment_date.month + 1
    if month == 13:
        year, month = year + 1, 1
    return date(year, month, 1)


@extend_schema(tags=TAG)
class UploadAndProcessEmployeeData(APIView):
    """Load the HR staff workbook (multipart field ``file``).

    Response: ``{sheets, inserted, already_present, updated, not_found, hfdi,
    errors[:50], error_count}``.
    """

    permission_classes = [IsAuthenticated, DataManagementPermissions]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"error": "No file uploaded. Send the staff workbook in the 'file' field."},
                status=status.HTTP_400_BAD_REQUEST)
        if not upload.name.lower().endswith((".xlsx", ".xls", ".csv")):
            return Response(
                {"error": "File must be an .xlsx workbook (or a single-sheet .csv)."},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            sheets = read_sheets(upload)
        except Exception as exc:  # noqa: BLE001 — surface the parse failure
            return Response({"error": f"Could not read the file: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)

        recognised = {name: frame for name, frame in sheets.items() if name in SHEETS}
        if not recognised:
            return Response(
                {"error": f"No usable sheet. Expected one of {list(SHEETS)}; "
                          f"found {list(sheets)}."},
                status=status.HTTP_400_BAD_REQUEST)

        errors, error_count = [], 0
        cleaned = {}
        for name, frame in recognised.items():
            try:
                cleaned[name] = clean_staff_list(frame)
            except Exception as exc:  # noqa: BLE001 — one bad sheet, not the file
                error_count += 1
                errors.append({"sheet": name, "error": str(exc)[:300]})

        if not cleaned:
            return Response({"error": errors[0]["error"] if errors else "Nothing to load."},
                            status=status.HTTP_400_BAD_REQUEST)

        alias = employee_db()
        inserted, already_present, insert_errors = self._insert_new(
            cleaned.get(SHEET_FULL_LIST, []), alias)
        updated, not_found, update_errors = self._update_exits_and_promotions(
            cleaned.get(SHEET_EXITS, []) + cleaned.get(SHEET_PROMOTIONS, []), alias)

        for problem in insert_errors + update_errors:
            error_count += 1
            if len(errors) < 50:
                errors.append(problem)

        hfdi = self._sync_hfdi(cleaned)

        return Response(
            {
                "sheets": {"used": sorted(cleaned),
                           "ignored": sorted(set(sheets) - set(cleaned))},
                "inserted": inserted,
                "already_present": already_present,
                "updated": updated,
                "not_found": not_found,
                "hfdi": hfdi,
                "errors": errors[:50],
                "error_count": error_count,
            },
            status=status.HTTP_200_OK,
        )

    # ── full_list -> insert the people who are not already on the roster ─────
    def _insert_new(self, rows, alias):
        rows = [r for r in rows if r.get("staff_id") is not None]
        if not rows:
            return 0, 0, []

        # staff_id is decimal(990,5) on the warehouse mirror, so the roster
        # comes back as Decimal('4028.00000') -> str '4028.0'. int() rejects
        # that; canon_staff_id is the one place that knows the shape.
        existing = {
            canon_staff_id(v) for v in EmployeeTable.objects.using(alias)
            .exclude(staff_id=None).values_list("staff_id", flat=True)
        }
        existing.discard(None)

        db_generates_id = _id_is_database_generated()
        next_id = None
        if not db_generates_id:
            next_id = (EmployeeTable.objects.using(alias)
                       .aggregate(m=Max("id"))["m"] or 0) + 1

        inserted = already_present = 0
        errors = []
        seen = set()
        for row in rows:
            staff_id = row["staff_id"]
            if staff_id in existing or staff_id in seen:
                already_present += 1
                continue
            seen.add(staff_id)
            try:
                fields = self._employee_fields(row)
                # The script blanks promotion_date on the full_list insert — a
                # promotion is recorded from the promotions sheet, not here.
                fields["promotion_date"] = None
                fields["promotion"] = 0
                fields["updated_at"] = timezone.now()
                if not db_generates_id:
                    fields["id"] = next_id
                    next_id += 1
                with transaction.atomic(using=alias):
                    EmployeeTable(**fields).save(using=alias, force_insert=True)
                inserted += 1
            except Exception as exc:  # noqa: BLE001 — keep loading the rest
                if len(errors) < 50:
                    errors.append({"sheet": SHEET_FULL_LIST, "staff_id": staff_id,
                                   "error": str(exc)[:300]})
        return inserted, already_present, errors

    @staticmethod
    def _employee_fields(row):
        fields = {}
        for column in INSERT_COLUMNS:
            value = row.get(column)
            if column in ("date_of_birth", "date_of_employment"):
                value = _as_datetime(value)
            elif column in ("staff_exit_date", "promotion_date"):
                value = _as_date(value)
            elif column in ("staff_id", "age", "service_years", "exit",
                            "promotion", "new", "hfdi_erp_id"):
                value = None if value is None else int(value)
            elif value is not None and not isinstance(value, str):
                value = str(value)
            fields[column] = value
        return fields

    # ── exits + promotions -> update the ten columns, nothing else ───────────
    def _update_exits_and_promotions(self, rows, alias):
        rows = [r for r in rows if r.get("staff_id") is not None]
        if not rows:
            return 0, 0, []

        # One row per person: the flags take the max (present in either sheet
        # wins) and everything else takes the first non-null.
        merged = {}
        for row in rows:
            target = merged.setdefault(row["staff_id"], {})
            for column in UPDATE_COLUMNS:
                value = row.get(column)
                if column in ("exit", "promotion"):
                    target[column] = max(int(target.get(column) or 0), int(value or 0))
                elif target.get(column) is None and value is not None:
                    target[column] = value

        updated = not_found = 0
        errors = []
        for staff_id, values in merged.items():
            try:
                fields = {}
                for column in UPDATE_COLUMNS:
                    value = values.get(column)
                    if column in ("staff_exit_date", "promotion_date"):
                        value = _as_date(value)
                    elif column in ("exit", "promotion"):
                        value = int(value or 0)
                    elif value is not None and not isinstance(value, str):
                        value = str(value)
                    fields[column] = value
                fields["updated_at"] = timezone.now()
                with transaction.atomic(using=alias):
                    count = (EmployeeTable.objects.using(alias)
                             .filter(staff_id=staff_id).update(**fields))
                if count:
                    updated += count
                else:
                    not_found += 1
            except Exception as exc:  # noqa: BLE001
                if len(errors) < 50:
                    errors.append({"sheet": "exits/promotions", "staff_id": staff_id,
                                   "error": str(exc)[:300]})
        return updated, not_found, errors

    # ── the same workbook also maintains hfdi_employee_data ──────────────────
    def _sync_hfdi(self, cleaned):
        all_rows = [row for rows in cleaned.values() for row in rows]
        candidates = [c for c in clean_division_staff_list(all_rows, PROPERTIES_DIVISION)
                      if c["staff_pf_number"] is not None]

        existing = set(HfdiEmployeeData.objects.values_list("staff_pf_number", flat=True))
        inserted = 0
        seen = set()
        for row in candidates:
            pf = row["staff_pf_number"]
            if pf in existing or pf in seen:
                continue
            seen.add(pf)
            HfdiEmployeeData.objects.create(**row)
            inserted += 1

        # An exit marks the HFDI record inactive; only the exits sheet does this.
        exits = clean_division_staff_list(cleaned.get(SHEET_EXITS, []), PROPERTIES_DIVISION)
        updated = 0
        for row in exits:
            if row["staff_pf_number"] is None:
                continue
            updated += HfdiEmployeeData.objects.filter(
                staff_pf_number=row["staff_pf_number"]
            ).update(staff_exit=row["staff_exit"], exit_date=row["exit_date"],
                     active=row["active"])
        return {"inserted": inserted, "exits_updated": updated}


@extend_schema(tags=TAG)
class EmployeeMasterTemplateView(APIView):
    """The workbook shape the upload expects, so the template can never drift
    from the loader (the frontend keeps a copy for its offline header check)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "columns": WORKBOOK_COLUMNS,
            "sheets": list(SHEETS),
            "required": ["staffid", "name"],
            "derived": ["age", "service_years", "exit", "promotion", "new",
                        "grade (padded to 2 digits)", "division (HFBI/HFDI)"],
            "note": "One .xlsx with a full_list sheet (inserts people not yet on "
                    "the roster) and optional exits / promotions sheets (which "
                    "update exit, promotion, service code, department, unit, org "
                    "unit, grade and job title). Nobody is ever deleted. A single "
                    "CSV is read as a lone full_list sheet.",
        })
