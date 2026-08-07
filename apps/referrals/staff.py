"""Soft validation of a referrer's PF number / sales code against the staff register.

The bank's employee roster is mirrored into ``BranchFinalEmployeeDmcData`` by the
ETL (``staff_pf_number``, ``sales_code``, ``staff_name`` …). We use it to *confirm*
who is making a referral and to autofill their name — but we never hard-block a
referral on it, because that table is ETL-populated and can legitimately be empty
or stale (e.g. before the first load, or for a brand-new joiner).

:func:`verify_staff` therefore returns a three-state result the model stores in
``staff_verified``:

* a matched name + ``True``  → PF/sales code found in the register (verified).
* ``None`` + ``True``        → the register HAS data but this PF/sales code is not
                               in it (genuinely unverified — surface a warning).
* ``None`` + ``False``       → the register is empty/unavailable, so we simply
                               cannot check (do not nag the user).
"""

from django.db.models import Q


def _to_int(value):
    """Best-effort parse of a PF number (stored as an integer in the roster)."""
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def verify_staff(pf_number, sales_code):
    """Look up ``pf_number`` / ``sales_code`` in the employee register.

    Returns ``(matched_name_or_None, register_had_data)``. Any lookup failure
    (missing table, DB error) is swallowed and reported as "cannot verify" so a
    referral is never lost to an infrastructure hiccup.
    """
    try:
        from apps.staff_management.models import BranchFinalEmployeeDmcData as Emp

        roster = Emp.objects.all()
        had_data = roster.exists()
        if not had_data:
            return None, False

        lookup = Q()
        pf = _to_int(pf_number)
        if pf is not None:
            lookup |= Q(staff_pf_number=pf)
        if sales_code:
            lookup |= Q(sales_code=str(sales_code).strip())
        if not lookup:  # neither PF nor sales code supplied — nothing to match on
            return None, had_data

        # Prefer an active employee row when several share a PF/sales code.
        matches = roster.filter(lookup).exclude(staff_name__isnull=True).exclude(staff_name="")
        row = (
            matches.filter(active=1).values_list("staff_name", flat=True).first()
            or matches.values_list("staff_name", flat=True).first()
        )
        return (row or None), had_data
    except Exception:
        # Register unavailable (e.g. datawarehouse mirror not built here) — treat as
        # "cannot verify" rather than failing the referral.
        return None, False
