"""Who may do what on the service desk.

Follows the convention the rest of this codebase already uses (see
``apps.referrals.rbac`` and ``core.permissions.InGroup``): authorisation is
Django **Group membership checked by name**, not a bespoke permission table.

Three positions, and only three:

* **Requester** — anyone signed in. Raises tickets, sees their own, comments on
  them, confirms or reopens a resolution. This is deliberately everybody: the
  queries going unhandled today are the ones nobody can see, and narrowing who
  may raise one narrows visibility, not volume.
* **Handler** (``service_desk_agent``) — works the queue. Sees every ticket,
  takes ownership, responds, resolves. Cannot close a ticket as confirmed on
  the requester's behalf.
* **Manager** (``service_desk_manager``) — the Strategy & Business Performance
  lead. Everything a handler can do, plus assigning other people, reassigning,
  editing categories and SLAs, cancelling, and the reports.

Superusers are managers. ``business_performance`` — the Strategy director role
that already exists — is treated as a manager too, because this desk is that
department's, and making them ask for a second group to see their own queue
would be an administrative step with no security meaning.
"""

MANAGER_GROUP = "service_desk_manager"
AGENT_GROUP = "service_desk_agent"

#: Roles that already mean "runs Strategy & Business Performance".
IMPLIED_MANAGER_GROUPS = {"business_performance"}

MANAGER_GROUPS = {MANAGER_GROUP} | IMPLIED_MANAGER_GROUPS
HANDLER_GROUPS = MANAGER_GROUPS | {AGENT_GROUP}


def _in(user, groups) -> bool:
    if not user or not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=groups).exists()


def is_manager(user) -> bool:
    """May assign to others, reassign, cancel, and edit the desk's settings."""
    return _in(user, MANAGER_GROUPS)


def is_handler(user) -> bool:
    """May see and work the whole queue."""
    return _in(user, HANDLER_GROUPS)


def can_view(user, ticket) -> bool:
    """A handler sees everything; everyone else sees only their own."""
    if not user or not user.is_authenticated:
        return False
    if is_handler(user):
        return True
    if ticket.raised_by_id and ticket.raised_by_id == user.id:
        return True
    email = (user.email or "").strip().lower()
    return bool(email and (ticket.requester_email or "").strip().lower() == email)


def can_comment(user, ticket) -> bool:
    return can_view(user, ticket)


def can_resolve(user, ticket) -> bool:
    """Only the desk resolves. A requester withdrawing their own query is a
    cancellation, which is a different thing and recorded as one."""
    return is_handler(user)


def can_confirm(user, ticket) -> bool:
    """Only the person who asked can agree that they got an answer.

    This is the whole point of the module, and the first version had a hole in
    it: a manager could confirm any ticket logged on somebody's behalf. Since
    the desk logs those itself, the same person resolved a query and was then
    asked "do you agree?" about their own work — precisely the situation being
    complained about, now with a button.

    So the rule is stated as a prohibition first: **whoever resolved it can
    never confirm it.** No exception, no role, no circumstance.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    # The prohibition, before anything that might grant.
    if ticket.resolved_by_id and ticket.resolved_by_id == user.id:
        return False

    if ticket.raised_by_id and ticket.raised_by_id == user.id:
        return True
    email = (user.email or "").strip().lower()
    if email and (ticket.requester_email or "").strip().lower() == email:
        return True

    # A query phoned in by somebody with no account has nobody to sign it off,
    # so a desk manager may — but only one who did not answer it, which the
    # prohibition above has already guaranteed. Four eyes, not one.
    return bool(is_manager(user) and not ticket.raised_by_id)


def can_assign(user, ticket=None) -> bool:
    """Who may set the handler.

    The desk, and **the person who raised it**. Requesters here know which of
    the Strategy team owns the report or the scorecard they are asking about,
    and making them wait for somebody to route it adds a queue that exists only
    to move a name from one field to another.
    """
    if is_handler(user):
        return True
    return bool(ticket is not None and user and getattr(user, "is_authenticated", False)
                and can_view(user, ticket))


def can_assign_to_others(user, ticket=None) -> bool:
    """Naming somebody other than yourself.

    A manager may do it anywhere. A requester may do it on their own ticket —
    that is the whole point of letting them choose who handles it. A handler
    may only take a ticket, not push it onto a colleague.
    """
    if is_manager(user):
        return True
    if ticket is None or not user or not getattr(user, "is_authenticated", False):
        return False
    if ticket.raised_by_id and ticket.raised_by_id == user.id:
        return True
    email = (user.email or "").strip().lower()
    return bool(email and (ticket.requester_email or "").strip().lower() == email)


def can_cancel(user, ticket) -> bool:
    """A requester may withdraw their own query; a manager may cancel any."""
    if is_manager(user):
        return True
    return bool(ticket.raised_by_id and user and ticket.raised_by_id == user.id)


def can_configure(user) -> bool:
    return is_manager(user)
