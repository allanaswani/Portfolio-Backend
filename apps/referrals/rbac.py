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

**Access is given, not assumed (Nov 2026).** The module used to open for every
signed-in account. It now opens only for a superuser or a member of one of
:data:`ACCESS_GROUPS`, which an administrator ticks on the Users screen:

* ``referrals_user`` - a member of staff who captures referrals and works the ones
  allocated to them. Allocating a referral to somebody adds them to it, because
  the supervisor has just given them work in the module.
* ``postbank_referrer`` - a Postbank team member. Postbank is a partner, not the
  bank: a member captures Postbank referrals and sees only their own, and the
  account reaches nothing outside this module (see :mod:`core.partner_access`).
  A Postbank member is never offered as an assignee, since that would hand a
  customer's details to another institution.

Migration 0007 seeds the two groups and gives ``referrals_user`` to everyone who had
already captured or been allocated a referral, so nobody using it lost it.
"""

#: Group whose members may allocate/reassign referrals and view the whole pipeline.
SUPERVISOR_GROUP = "telesales_supervisor"
#: Group whose members receive allocations and see only their own queue.
AGENT_GROUP = "telesales_agent"

#: Staff who capture referrals and work the ones allocated to them.
USER_GROUP = "referrals_user"
#: Postbank's team - a partner institution; capture only, own referrals only.
POSTBANK_GROUP = "postbank_referrer"

#: Groups that grant the "see everything / allocate" privilege.
PRIVILEGED_GROUPS = {SUPERVISOR_GROUP}
#: Groups that open the module at all.
ACCESS_GROUPS = {SUPERVISOR_GROUP, AGENT_GROUP, USER_GROUP, POSTBANK_GROUP}


def has_access(user) -> bool:
    """True when ``user`` may use the Referrals module at all."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=ACCESS_GROUPS).exists()


def is_postbank(user) -> bool:
    """True for a Postbank team member (never for a superuser)."""
    if not user or not user.is_authenticated or user.is_superuser:
        return False
    return user.groups.filter(name=POSTBANK_GROUP).exists()


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
    if not (user and user.is_authenticated and user.is_active):
        return False
    # A partner's account never receives the bank's customers to work.
    return not is_postbank(user)
