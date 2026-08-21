"""Soft validation of a referrer's PF number / sales code against the staff register.

Two rosters exist and they do not overlap:

* ``BranchFinalEmployeeDmcData`` — the *sales/branch* DMC table. It is the only
  one carrying ``sales_code``, but it holds ~800 sales-facing staff, so a Head
  Office referrer (Strategy, Finance, IT …) is simply not in it.
* ``EmployeeTable`` (``employee_table``) — the full HR roster, ~1,270 staff,
  keyed by ``staff_id`` (the PF number). No sales code.

The original implementation checked only the DMC table, so every non-sales
referrer came back "Unverified" even though their PF number is perfectly valid.
We now check the DMC table first (it can match on either PF or sales code) and
fall back to the HR roster on PF number.

We still never hard-block a referral on this: both tables are ETL-populated and
can legitimately be empty or stale (before the first load, or for a new joiner).

:func:`verify_staff` returns a three-state result the model stores in
``staff_verified``:

* a matched name + ``True``  → PF/sales code found in a register (verified).
* ``None`` + ``True``        → a register HAS data but this PF/sales code is not
                               in either (genuinely unverified — warn).
* ``None`` + ``False``       → both registers are empty/unavailable, so we cannot
                               check (do not nag the user).
"""

from django.db.models import Q


def _to_int(value):
    """Best-effort parse of a PF number (stored numerically in both rosters)."""
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _check_dmc(pf, sales_code):
    """Sales/branch DMC roster — matches on PF number OR sales code.

    Returns ``(name_or_None, had_data)``.
    """
    from apps.staff_management.models import BranchFinalEmployeeDmcData as Emp

    roster = Emp.objects.all()
    if not roster.exists():
        return None, False

    lookup = Q()
    if pf is not None:
        lookup |= Q(staff_pf_number=pf)
    if sales_code:
        lookup |= Q(sales_code__iexact=str(sales_code).strip())
    if not lookup:  # neither PF nor sales code supplied — nothing to match on
        return None, True

    matches = roster.filter(lookup).exclude(staff_name__isnull=True).exclude(staff_name="")
    # Prefer an active employee row when several share a PF/sales code.
    name = (
        matches.filter(active=1).values_list("staff_name", flat=True).first()
        or matches.values_list("staff_name", flat=True).first()
    )
    return (name or None), True


def _check_hr(pf):
    """Full HR roster (``employee_table``) — PF number only, no sales code there.

    Returns ``(name_or_None, had_data)``.
    """
    from apps.gceo_dashboard.models import EmployeeTable

    roster = EmployeeTable.objects.all()
    if not roster.exists():
        return None, False
    if pf is None:
        return None, True

    # staff_id is a numeric column, so 3868 and 3868.00000 are the same row.
    name = (
        roster.filter(staff_id=pf)
        .exclude(name__isnull=True).exclude(name="")
        .values_list("name", flat=True)
        .first()
    )
    return (name or None), True


def verify_staff(pf_number, sales_code):
    """Look up ``pf_number`` / ``sales_code`` across both staff registers.

    Returns ``(matched_name_or_None, any_register_had_data)``. Each lookup failure
    (missing table, DB error) is swallowed independently, so one unavailable
    roster never stops the other from verifying — and a referral is never lost to
    an infrastructure hiccup.
    """
    pf = _to_int(pf_number)
    had_any_data = False

    for check, args in ((_check_dmc, (pf, sales_code)), (_check_hr, (pf,))):
        try:
            name, had_data = check(*args)
        except Exception:
            # Register unavailable (e.g. warehouse mirror not built here) — skip it.
            continue
        had_any_data = had_any_data or had_data
        if name:
            return name, True

    return None, had_any_data
