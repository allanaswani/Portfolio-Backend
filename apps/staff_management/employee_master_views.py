"""Employee master upload — the full HR roster (``employee_table``).

This is the port of the old backend's
``staff_management.views.UploadAndProcessEmployeeData``, still mounted at the
same path: ``employee-data/upload-csv/``.

WHY IT LOADS THE FILE INSTEAD OF SHELLING OUT
---------------------------------------------
The original view did three things: clear ``../etls/temp_files``, drop the
uploaded file there, then ``bash ../etls/initiate_update_employee_information.sh
<file>`` and hand the script's stdout back to the browser. That worked because
the old backend ran ON the ETL host. This backend runs in a container that has
neither the ``etls`` tree nor the data team's python3.6 (see
``core/script_trigger`` and [[container-deploy]]), so a verbatim port would
return ``Failed to execute processing script`` on every upload — a dead button.

The script's job was to load the file into ``employee_table``. That is what this
view does directly, in the same database, with the semantics the old loader had:

* **Upsert on ``staff_id``** — re-uploading the same file updates in place; it
  never duplicates a person and never deletes anyone who is absent from the file.
* **A blank cell leaves the stored value alone.** HR routinely uploads a partial
  extract (say only departments and grades filled in). Writing NULL for every
  empty cell would wipe columns nobody intended to touch.
* Dates and numbers arrive in whatever shape Excel exported, so both are parsed
  leniently rather than rejected.

``employee_table`` is a ``managed = False`` warehouse mirror; writing it from the
manual admin endpoint is the same thing the other manual warehouse uploads in
``legacy_views`` do. Two production quirks are handled explicitly:

* the table's ``id`` can have no sequence/identity default (see
  [[prod-schema-drift]] — reads work, inserts 500 with *null value in column
  "id"*). When it has none the view supplies the id itself;
* the table can hold repeat rows for one ``staff_id`` — the most recent row
  (highest id) is the one updated.

The three columns the roster page maintains by hand — ``standard_department``,
``current_role``, ``previous_role`` — do not exist in ``employee_table``. When
the CSV carries them they are written to the managed ``employee_roster_overlay``
companion, so ONE upload maintains the whole page rather than two.
"""

import csv
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

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

from apps.gceo_dashboard.models import EmployeeRosterOverlay, EmployeeTable
from core.csv_upload import decode_csv_bytes
from core.permissions import DataManagementPermissions

TAG = ["Staff Management — Employee Master"]

# ── The template, in the order the download hands it to HR ───────────────────
# Everything except staff_id is optional per row; a blank cell means "leave the
# stored value alone". Keep this list in step with the frontend
# CSVUploadModal TEMPLATES["employee_master_data"] entry.
TEXT_COLUMNS = [
    "name", "national_id", "email", "gender", "service_code",
    "division", "department", "unit", "org_unit", "grade", "job_title",
]
INT_COLUMNS = ["age", "service_years", "hfdi_erp_id", "exit", "promotion", "new"]
DATETIME_COLUMNS = ["date_of_birth", "date_of_employment"]
DATE_COLUMNS = ["staff_exit_date", "promotion_date"]
OVERLAY_COLUMNS = ["standard_department", "current_role", "previous_role"]

TEMPLATE_COLUMNS = (
    ["staff_id"]
    + TEXT_COLUMNS
    + ["date_of_birth", "age", "date_of_employment", "service_years"]
    + ["exit", "staff_exit_date", "promotion", "promotion_date", "new", "hfdi_erp_id"]
    + OVERLAY_COLUMNS
)
# The above interleaves for readability; de-duplicate while keeping first order.
TEMPLATE_COLUMNS = list(dict.fromkeys(TEMPLATE_COLUMNS))

_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y",
    "%d/%m/%y", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%b %d, %Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M",
]

# Header aliases: HR's extract does not always use the model's column names.
_ALIASES = {
    "staff_no": "staff_id", "staff_number": "staff_id", "pf_number": "staff_id",
    "pf_no": "staff_id", "staff_pf_number": "staff_id", "employee_id": "staff_id",
    "employee_number": "staff_id",
    "full_name": "name", "staff_name": "name", "employee_name": "name",
    "id_number": "national_id", "id_no": "national_id",
    "e_mail": "email", "email_address": "email",
    "dob": "date_of_birth", "birth_date": "date_of_birth",
    "employment_date": "date_of_employment", "date_employed": "date_of_employment",
    "years_of_service": "service_years", "service_yrs": "service_years",
    "exit_date": "staff_exit_date", "date_of_exit": "staff_exit_date",
    "exited": "exit", "promoted": "promotion",
    "std_department": "standard_department", "prev_role": "previous_role",
    "hfdi_erp": "hfdi_erp_id",
}


def normalize_header(name):
    """"Date Of Employment", " date_of_employment " and a BOM'd header all match."""
    if name is None:
        return ""
    text = str(name).replace("﻿", "").replace("​", "")
    text = text.strip().strip('"').strip("'").strip().lower()
    text = "_".join(text.split())
    return _ALIASES.get(text, text)


def canon_staff_id(value):
    """``4022``, ``4022.0`` and ``4022.00000`` are all the same person → "4022"."""
    if value is None:
        return ""
    text = str(value).strip().replace(",", "")
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def parse_int(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    # "Yes"/"No" show up in the exit / promotion columns.
    lowered = text.lower()
    if lowered in ("yes", "y", "true"):
        return 1
    if lowered in ("no", "n", "false"):
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def parse_date(value):
    text = str(value or "").strip()
    if not text or text.lower() in ("nan", "nat", "none", "null", "-"):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def employee_db():
    """The one alias every employee_table statement in this view uses.

    The router sends unmanaged models to ``datawarehouse`` for reads and returns
    ``None`` for writes (which falls through to ``default``). On production both
    aliases point at the SAME physical database, so that split is invisible —
    but a read-then-write upsert that reads one alias and writes the other is
    only accidentally correct. Pinning both to the write alias makes the upsert
    read back exactly what it wrote, wherever the two aliases point.
    """
    return router.db_for_write(EmployeeTable) or "default"


def _id_is_database_generated():
    """Does ``employee_table.id`` fill itself in, or must we supply it?

    Postgres substitutes NULL when a NOT NULL pk has neither a ``nextval``
    default nor an identity, and BigAutoField deliberately omits id from the
    INSERT — the exact shape of the hfdi target 500 (see [[prod-schema-drift]]).
    """
    table = EmployeeTable._meta.db_table
    try:
        with connections[employee_db()].cursor() as cur:
            cur.execute(
                """
                SELECT (column_default IS NOT NULL)
                       OR (COALESCE(is_identity, 'NO') = 'YES')
                FROM   information_schema.columns
                WHERE  table_name = %s AND column_name = 'id'
                """,
                [table],
            )
            row = cur.fetchone()
    except Exception:
        return True  # can't tell — let the database try
    return True if row is None else bool(row[0])


@extend_schema(tags=TAG)
class UploadAndProcessEmployeeData(APIView):
    """Bulk upsert the HR employee master from a CSV (multipart field ``file``).

    Response: ``{created, updated, unchanged, skipped, overlay_created,
    overlay_updated, errors[:50], error_count}``.
    """

    permission_classes = [IsAuthenticated, DataManagementPermissions]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "No file uploaded. Send a CSV in the 'file' field."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not upload.name.lower().endswith(".csv"):
            return Response({"error": "File must be a CSV."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            text = decode_csv_bytes(upload.read())
        except Exception as exc:  # noqa: BLE001 — surface the decode failure
            return Response({"error": f"Could not read the file: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(text.splitlines())
        raw_headers = reader.fieldnames or []
        if not raw_headers:
            return Response({"error": "CSV has no header row."}, status=status.HTTP_400_BAD_REQUEST)

        header_map = {raw: normalize_header(raw) for raw in raw_headers}
        if "staff_id" not in header_map.values():
            return Response(
                {"error": f"The CSV must carry a staff_id column. Columns found: {raw_headers}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        who = getattr(request.user, "username", "") or getattr(request.user, "email", "") or ""
        db_generates_id = _id_is_database_generated()
        next_id = None
        if not db_generates_id:
            next_id = (EmployeeTable.objects.using(employee_db())
                       .aggregate(m=Max("id"))["m"] or 0) + 1

        created = updated = unchanged = skipped = 0
        overlay_created = overlay_updated = 0
        errors, error_count = [], 0

        line_no = 1  # the header
        for raw_row in reader:
            line_no += 1
            row = {header_map.get(k, normalize_header(k)): v for k, v in raw_row.items()}
            staff_id = canon_staff_id(row.get("staff_id"))
            if not staff_id:
                skipped += 1
                continue

            try:
                with transaction.atomic(using=employee_db()):
                    outcome, next_id = self._upsert_employee(row, staff_id, next_id, db_generates_id)
                    if outcome == "created":
                        created += 1
                    elif outcome == "updated":
                        updated += 1
                    else:
                        unchanged += 1

                    ov = self._upsert_overlay(row, staff_id, who)
                    if ov == "created":
                        overlay_created += 1
                    elif ov == "updated":
                        overlay_updated += 1
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the import
                error_count += 1
                if len(errors) < 50:
                    errors.append({"row": line_no, "staff_id": staff_id, "error": str(exc)[:300]})

        if created + updated + unchanged + skipped + error_count == 0:
            return Response({"error": "CSV has no data rows."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "created": created,
                "updated": updated,
                "unchanged": unchanged,
                "skipped": skipped,
                "overlay_created": overlay_created,
                "overlay_updated": overlay_updated,
                "errors": errors,
                "error_count": error_count,
            },
            status=status.HTTP_200_OK,
        )

    # ── row → employee_table ─────────────────────────────────────────────────
    def _employee_values(self, row):
        """Only the columns the row actually supplies a value for."""
        values = {}
        for col in TEXT_COLUMNS:
            if col in row:
                text = (row.get(col) or "").strip()
                if text:
                    values[col] = text
        for col in INT_COLUMNS:
            if col in row:
                parsed = parse_int(row.get(col))
                if parsed is not None:
                    values[col] = parsed
        for col in DATETIME_COLUMNS:
            if col in row:
                parsed = parse_date(row.get(col))
                if parsed is not None:
                    # date_of_birth / date_of_employment are calendar dates stored
                    # in a timestamp column. Anchoring them to UTC midnight keeps
                    # the day intact on read-back; local (EAT) midnight would be
                    # stored as 21:00 the PREVIOUS day and read back a day early.
                    if settings.USE_TZ and timezone.is_naive(parsed):
                        parsed = parsed.replace(tzinfo=dt_timezone.utc)
                    values[col] = parsed
        for col in DATE_COLUMNS:
            if col in row:
                parsed = parse_date(row.get(col))
                if parsed is not None:
                    values[col] = parsed.date()
        return values

    def _upsert_employee(self, row, staff_id, next_id, db_generates_id):
        values = self._employee_values(row)

        # staff_id is a numeric in the warehouse; match on the number, not the text.
        try:
            key = Decimal(staff_id)
        except (InvalidOperation, ValueError):
            raise ValueError(f"staff_id {staff_id!r} is not a number")

        # The table can carry repeat rows for one person — update the latest.
        alias = employee_db()
        existing = (EmployeeTable.objects.using(alias)
                    .filter(staff_id=key).order_by("-id").first())
        if existing is None:
            fields = dict(values, staff_id=key, updated_at=timezone.now())
            if not db_generates_id:
                fields["id"] = next_id
                next_id += 1
            EmployeeTable(**fields).save(using=alias, force_insert=True)
            return "created", next_id

        changed = [f for f, v in values.items() if getattr(existing, f) != v]
        if not changed:
            return "unchanged", next_id
        for field in changed:
            setattr(existing, field, values[field])
        existing.updated_at = timezone.now()
        existing.save(using=alias, update_fields=changed + ["updated_at"])
        return "updated", next_id

    # ── row → employee_roster_overlay ────────────────────────────────────────
    def _upsert_overlay(self, row, staff_id, who):
        defaults = {}
        for col in OVERLAY_COLUMNS:
            text = (row.get(col) or "").strip()
            if text:
                defaults[col] = text
        if not defaults:
            return None
        defaults["updated_by"] = who
        _, was_created = EmployeeRosterOverlay.objects.update_or_create(
            staff_id=staff_id, defaults=defaults,
        )
        return "created" if was_created else "updated"


@extend_schema(tags=TAG)
class EmployeeMasterTemplateView(APIView):
    """The exact column list the upload accepts, so the template can never drift
    from the loader (the frontend keeps a copy for its offline validation)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "columns": TEMPLATE_COLUMNS,
            "required": ["staff_id"],
            "overlay_columns": OVERLAY_COLUMNS,
            "note": "staff_id keys the upsert. A blank cell leaves the stored "
                    "value unchanged; nobody absent from the file is deleted.",
        })
