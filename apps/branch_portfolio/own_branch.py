"""Which branch a branch manager's account belongs to when its profile has none.

A blank profile branch is refused rather than served the whole bank, which is right,
but the page showed that refusal as zeros, and the rosters already say where the person
works. Only the account's own address is used, never ``Profile.sales_code``, because
that can hold another person's code. Only a ``branch_portfolio`` account gets this, so
nobody gains a branch view they did not have. Nothing is saved.
"""

from django.db import transaction

BRANCH_ROLE = "branch_portfolio"


def _addresses(user):
    found = {str(getattr(user, "email", "") or "").strip().lower().split("@")[0],
             str(getattr(user, "username", "") or "").strip().lower()}
    return found - {""}


def _sources():
    """(model, its address field, the field naming the branch), most specific first."""
    from apps.staff_management.models import (BranchEmployeeDmcData,
                                              BranchFinalEmployeeDmcData,
                                              StaffEmployeeData)

    return ((BranchFinalEmployeeDmcData, "staff_email", "staff_branch"),
            (BranchEmployeeDmcData, "staff_email", "staff_branch"),
            (StaffEmployeeData, "staff_email", "staff_unit"))


def roster_branch(user):
    """The one branch the rosters give this account, or "".

    Exactly one, and exactly a branch: two answers from a roster, or a unit that is
    not one of the bank's branches, place nobody.
    """
    from apps.observability.management.commands.send_usage_report import _a_branch

    if not user.groups.filter(name=BRANCH_ROLE).exists():
        return ""
    for model, address, branch in _sources():
        names = set()
        try:
            with transaction.atomic():
                for local in _addresses(user):
                    rows = model.objects.filter(
                        **{f"{address}__istartswith": f"{local}@"})
                    names |= {_a_branch(v) or "?"
                              for v in rows.values_list(branch, flat=True)}
        except Exception:  # noqa: BLE001 - a missing roster costs this one source
            continue
        if len(names) == 1 and "?" not in names:
            return names.pop()
        if names:
            return ""
    return ""
