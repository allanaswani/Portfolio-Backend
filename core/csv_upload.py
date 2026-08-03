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


def decode_csv_bytes(raw_data):
    """Decode uploaded CSV bytes to text, tolerating stray high bytes.

    chardet returns ``"ascii"`` (or ``None``) for a file that is ASCII apart from
    a handful of stray high bytes — most often a ``0xA0`` non-breaking space or a
    smart quote pasted in from Excel. Strictly decoding such a file as ASCII then
    raises ``'ascii' codec can't decode byte 0xA0`` and fails the whole upload.
    We widen ASCII/None to cp1252 (a Windows superset of ASCII that also maps
    nbsp and smart quotes) and always decode with ``errors="replace"`` so a single
    bad byte can never abort the import.
    """
    detected = chardet.detect(raw_data)["encoding"]
    if not detected or detected.lower() == "ascii":
        detected = "cp1252"
    return raw_data.decode(detected, errors="replace")


class AmendingCsvUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    model = None
    serializer_class = None
    result_filename = "upload_results"
    # Concrete columns the missing-columns gate should NOT demand of the CSV
    # (the auto pk, server-managed timestamps, derived columns, …).
    excluded_columns = ("id", "house_type", "project_name")

    # ── reusable amendment helpers ──────────────────────────────────────────────
    @staticmethod
    def derive_parenthesised(value):
        """Return the LAST parenthesised group of ``value``, else ``value`` itself."""
        value = value or ""
        matches = re.findall(r"\(([^)]+)\)", value)
        return matches[-1] if matches else value

    @staticmethod
    def derive_hyphenated(value):
        """Return the LAST parenthesised group of ``value``, else ``value`` itself."""
        value = value or ""
        matches = value.rfind('-')
        return value[:matches].strip() if matches != -1 else value.strip()

    @staticmethod
    def parse_date(raw, fmt, out_fmt=None):
        """Parse ``raw`` and return ``out_fmt`` (or isoformat), else None.

        ``fmt`` is the caller's primary format and is tried first (a str, or an
        iterable of formats). A handful of common shapes are then tried as
        fallbacks so a date in a slightly different layout (ISO, hyphenated,
        2-digit year) is not silently dropped to NULL. Null dates downstream have
        crashed report scripts — e.g. ``NaTType does not support isocalendar`` in
        the bancassurance report when ``starting_date`` came back NULL.
        """
        raw = (raw or "").strip()
        if not raw:
            return None
        primary = [fmt] if isinstance(fmt, str) else list(fmt)
        fallbacks = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d",
                     "%d.%m.%Y", "%d/%m/%y", "%m/%d/%Y"]
        seen = set()
        for candidate in primary + fallbacks:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                dt = datetime.strptime(raw, candidate)
            except ValueError:
                continue
            return dt.strftime(out_fmt) if out_fmt else dt.isoformat()
        return None

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

    @staticmethod
    def normalize_header(name):
        """Canonicalise a CSV header so trivial formatting differences don't read
        as a *missing* column: strip a UTF-8 BOM / zero-width chars, surrounding
        quotes and whitespace, lower-case, and collapse inner whitespace to
        underscores. So "Sum Insured", " sum_insured ", "SUM_INSURED" and a
        BOM-prefixed "﻿sum_insured" all match the model field ``sum_insured``."""
        if name is None:
            return ""
        s = str(name).replace("﻿", "").replace("​", "")
        s = s.strip().strip('"').strip("'").strip()
        return re.sub(r"\s+", "_", s.lower())

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
            decoded_file = decode_csv_bytes(raw_data).splitlines()
            reader = csv.DictReader(decoded_file)
            raw_fieldnames = reader.fieldnames or []

            # Match headers tolerantly — a stray space, different case or a BOM
            # shouldn't make a column that IS present read as "missing".
            norm_map = {orig: self.normalize_header(orig) for orig in raw_fieldnames}
            fieldnames = list(norm_map.values())

            missing = [c for c in self.required_columns() if c not in fieldnames]
            if missing:
                return Response(
                    {"error": (f"The following columns are missing in the CSV: {missing}. "
                               f"Columns found: {raw_fieldnames}")},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Re-key every row to the canonical (normalized) header names so
            # amend_row / the serializer see the exact model field names.
            rows = [{norm_map.get(k, self.normalize_header(k)): v for k, v in r.items()}
                    for r in reader]
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
