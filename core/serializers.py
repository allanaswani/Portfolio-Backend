"""Serializer pieces for reading the warehouse.

The warehouse is filled by ETLs from a core banking system, and core banking
systems write sentinel dates — ``9999-12-31`` for a facility with no maturity,
``0001-01-01`` for one that never started. Those are legitimate values in the
source and they load into PostgreSQL without complaint.

They then kill a page. DRF's ``DateTimeField`` checks whether a value is
ambiguous under the active timezone, which does ``dt.astimezone(utc)``; for
``9999-12-31`` in Africa/Nairobi that is three hours past the end of what a
Python ``datetime`` can hold:

    OverflowError: date value out of range

One row out of a customer's loan book took down the whole endpoint —
``/portfolio/customers/<id>/detail_loans`` returned 500 rather than the other
loans it could perfectly well have served.

So: report the value as it is, and never fail the response over it. A sentinel
date is data the reader may want to see ("no maturity" is meaningful); blanking
it would hide a real value, and raising loses every other row on the page.
"""

from django.db import models
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

#: What an unconvertible date raises. DRF versions differ: older ones let the
#: OverflowError out of enforce_timezone, newer ones catch it and fail with a
#: ValidationError code="overflow". Production and this checkout disagreed, so
#: both are caught — a serializer's to_representation has no legitimate reason
#: to raise a validation error anyway, since nothing is being validated.
UNREPRESENTABLE = (OverflowError, ValueError, OSError, ValidationError)


class SafeDateTimeField(serializers.DateTimeField):
    """A datetime that survives a value Python cannot convert to UTC."""

    def to_representation(self, value):
        try:
            return super().to_representation(value)
        except UNREPRESENTABLE:
            # ISO format needs no timezone arithmetic, so it works where the
            # conversion does not. The reader sees 9999-12-31, which is the
            # truth about the row.
            try:
                return value.isoformat()
            except Exception:  # noqa: BLE001 — not a date at all; say nothing
                return None


class SafeDateField(serializers.DateField):
    def to_representation(self, value):
        try:
            return super().to_representation(value)
        except UNREPRESENTABLE:
            try:
                return value.isoformat()
            except Exception:  # noqa: BLE001
                return None


class WarehouseModelSerializer(serializers.ModelSerializer):
    """``ModelSerializer`` for a table the ETLs own.

    Identical to the standard one except that an out-of-range date is reported
    rather than thrown. Use it for any serializer over an unmanaged model: the
    application does not choose what those tables contain, so it has to cope
    with what arrives.
    """

    serializer_field_mapping = {
        **serializers.ModelSerializer.serializer_field_mapping,
        models.DateTimeField: SafeDateTimeField,
        models.DateField: SafeDateField,
    }
