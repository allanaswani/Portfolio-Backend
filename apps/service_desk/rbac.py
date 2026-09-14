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

    This is the whole point of the module. A handler who could confirm their own
    resolution would reproduce, exactly, the situation being complained about.
    """
    if is_manager(user) and not ticket.raised_by_id:
        # A ticket logged on behalf of someone who phoned in has no requester
        # account to sign it off, so the desk lead may — and it is recorded as
        # them, not as the requester.
        return True
    if not user or not user.is_authenticated:
        return False
    if ticket.raised_by_id and ticket.raised_by_id == user.id:
        return True
    email = (user.email or "").strip().lower()
    return bool(email and (ticket.requester_email or "").strip().lower() == email)


def can_assign(user, ticket=None) -> bool:
    """Managers assign anyone; a handler may take a ticket for themselves."""
    return is_handler(user)


def can_assign_to_others(user) -> bool:
    return is_manager(user)


def can_cancel(user, ticket) -> bool:
    """A requester may withdraw their own query; a manager may cancel any."""
    if is_manager(user):
        return True
    return bool(ticket.raised_by_id and user and ticket.raised_by_id == user.id)


def can_configure(user) -> bool:
    return is_manager(user)
