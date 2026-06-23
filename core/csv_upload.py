"""
Shared CSV uploader with per-column amendments + upsert, ported from the legacy
``hf_group_project`` backend.

Several legacy upload endpoints don't just bulk-create rows — they *amend* certain
columns on the way in (derive a value, parse a human-formatted date, clean
comma-grouped numbers), **upsert** on a business key rather than blindly inserting,
and return a ZIP of ``successful_records.csv`` / ``failed_records.csv`` (the contract
the frontend's ``downloadUploadResults`` helper consumes). ``BaseCsvUploadView``
(JSON, bulk *create*) loses all of that, so those endpoints subclass this instead.

Subclasses set ``model`` / ``serializer_class`` / ``result_filename`` and override the
hooks they need:

* ``amend_row(row)``      — mutate a row dict in place before validation.
* ``build_serializer(row)`` — return the serializer (override for instance upserts).
* ``save_valid(row, serializer)`` — persist a validated row; return ``None`` on success
  or an error payload to mark the row failed.
* ``before_rows(rows)``  — a bulk pre-step over all parsed rows (e.g. delete-by-year).

Faithfulness note: the legacy delete-by-year uploaders did ``next(reader)`` to read the
year, which silently dropped the first data row. ``before_rows`` receives the full row
list, so the port keeps the delete-by-year semantics WITHOUT losing the first row.
"""
import csv
import io
import re
import zipfile
from datetime import datetime

import chardet
from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class AmendingCsvUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    model = None
    serializer_class = None
    result_filename = "upload_results"
    # Concrete columns the missing-columns gate should NOT demand of the CSV
    # (the auto pk, server-managed timestamps, derived columns, …).
    excluded_columns = ("id",)

    # ── reusable amendment helpers ──────────────────────────────────────────────
    @staticmethod
    def derive_parenthesised(value):
        """Return the LAST parenthesised group of ``value``, else ``value`` itself."""
        value = value or ""
        matches = re.findall(r"\(([^)]+)\)", value)
        return matches[-1] if matches else value

    @staticmethod
    def parse_date(raw, fmt, out_fmt=None):
        """Parse ``raw`` with ``fmt``; return ``out_fmt`` string (or isoformat), else None."""
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            return None
        return dt.strftime(out_fmt) if out_fmt else dt.isoformat()

    @staticmethod
    def clean_number(raw, *, dash_to_zero=False, default=None):
        val = (raw or "").strip().replace(",", "")
        if dash_to_zero and val == "-":
            val = "0"
        if not val:
            return default
        return val

    @staticmethod
    def to_float(raw, default=0.0):
        try:
            val = str(raw).strip().replace(",", "")
            return float(val) if val else default
        except (TypeError, ValueError):
            return default

    # ── hooks ───────────────────────────────────────────────────────────────────
    def required_columns(self):
        # Editable concrete columns the CSV must carry — auto/non-editable columns
        # (auto_now timestamps, etc.) and the subclass's ``excluded_columns`` are dropped.
        excluded = set(self.excluded_columns)
        return [
            f.name for f in self.model._meta.concrete_fields
            if f.editable and f.name not in excluded
        ]

    def before_rows(self, rows):
        """Bulk pre-step over all parsed rows (default no-op)."""

    def amend_row(self, row):
        """Mutate ``row`` in place before validation (default no-op)."""

    def build_serializer(self, row):
        return self.serializer_class(data=row)

    def save_valid(self, row, serializer):
        serializer.save()
        return None

    # ── request handling ────────────────────────────────────────────────────────
    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        if not file_obj.name.endswith(".csv"):
            return Response({"error": "File must be a CSV"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            raw_data = file_obj.read()
            encoding = chardet.detect(raw_data)["encoding"] or "utf-8"
            decoded_file = raw_data.decode(encoding).splitlines()
            reader = csv.DictReader(decoded_file)
            fieldnames = reader.fieldnames or []

            missing = [c for c in self.required_columns() if c not in fieldnames]
            if missing:
                return Response(
                    {"error": f"The following columns are missing in the CSV: {missing}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            rows = list(reader)
            self.before_rows(rows)

            success_buffer, fail_buffer = io.StringIO(), io.StringIO()
            success_writer = csv.DictWriter(success_buffer, fieldnames=fieldnames, extrasaction="ignore")
            fail_writer = csv.DictWriter(fail_buffer, fieldnames=list(fieldnames) + ["error"], extrasaction="ignore")
            success_writer.writeheader()
            fail_writer.writeheader()

            for row in rows:
                try:
                    self.amend_row(row)
                    serializer = self.build_serializer(row)
                    if not serializer.is_valid():
                        row["error"] = serializer.errors
                        fail_writer.writerow(row)
                        continue
                    error = self.save_valid(row, serializer)
                    if error is not None:
                        row["error"] = error
                        fail_writer.writerow(row)
                        continue
                    success_writer.writerow(row)
                except Exception as exc:  # noqa: BLE001 — per-row failure: keep importing the rest
                    row["error"] = str(exc)
                    fail_writer.writerow(row)

            response = HttpResponse(content_type="application/zip")
            current_date = datetime.now().strftime("%Y%m%d")
            response["Content-Disposition"] = (
                f'attachment; filename="{self.result_filename}_{current_date}.zip"'
            )
            with zipfile.ZipFile(response, "w") as zf:
                success_buffer.seek(0)
                fail_buffer.seek(0)
                zf.writestr("successful_records.csv", success_buffer.getvalue())
                zf.writestr("failed_records.csv", fail_buffer.getvalue())
            return response
        except Exception as exc:  # noqa: BLE001 — legacy contract: surface any parse error
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
