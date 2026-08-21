"""Role boundaries for the Referral module.

Referrals reuse the codebase's existing RBAC convention: authorisation is decided
by **Django Group membership checked by name** (the same approach as
``apps.mortgages`` — see ``_lead_privileged`` / ``_scoped_leads`` there), not a
bespoke permission table. Two groups are introduced for telesales:

* ``telesales_supervisor`` — the manager who allocates referrals to agents and can
  see every referral in the pipeline.
* ``telesales_agent`` — a front-line telesales rep who only ever sees the referrals
  allocated to them (plus anything they captured themselves).

Superusers are always treated as supervisors. Anyone else (e.g. a branch staffer
who keys in a referral) is a *capturer*: they can create referrals and see only the
ones they submitted.

The two groups are created by data migration ``0002_seed_telesales_groups`` so the
names resolve even on a fresh database.
"""

#: Group whose members may allocate/reassign referrals and view the whole pipeline.
SUPERVISOR_GROUP = "telesales_supervisor"
#: Group whose members receive allocations and see only their own queue.
AGENT_GROUP = "telesales_agent"

#: Groups that grant the "see everything / allocate" privilege.
PRIVILEGED_GROUPS = {SUPERVISOR_GROUP}


def is_supervisor(user) -> bool:
    """True when ``user`` may see every referral and allocate them.

    Superusers qualify unconditionally; everyone else must belong to a group in
    :data:`PRIVILEGED_GROUPS`.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=PRIVILEGED_GROUPS).exists()


def is_allocatable(user) -> bool:
    """True when a referral may be assigned to ``user``.

    Referrals were originally allocatable only to the two telesales groups, but
    the business works them through relationship managers and branch sales staff
    as well, who hold none of those groups. Restricting the roster to telesales
    made those people unpickable, so any **active** account may now receive an
    allocation and the supervisor decides who is appropriate.

    Note this is a visibility grant: an assignee can read the referral's customer
    details, so only a supervisor may perform the allocation (see
    :func:`is_supervisor`).
    """
    return bool(user and user.is_authenticated and user.is_active)
