"""Who may do what on the design board.

Follows the convention the rest of this codebase already uses (see
``apps.service_desk.rbac``, ``apps.referrals.rbac`` and
``core.permissions.InGroup``): authorisation is Django **Group membership
checked by name**, not a bespoke permission table.

Three positions, and only three:

* **Requester** — anyone signed in. Raises a brief, sees their own and their
  department's, edits one before a designer picks it up, approves or sends it
  back for rework, cancels their own. Deliberately everybody: the requests that
  go missing today are the ones nobody can see, and narrowing who may raise one
  narrows visibility, not volume.
* **Designer** (``marketing_designer``) — sees the whole board, starts and
  submits the briefs allocated to them. Cannot assign work, including to
  themselves, and cannot approve.
* **Admin** (``marketing_admin``) — the department's administrator. Everything
  a designer can do, plus assigning and reassigning designers, cancelling
  anybody's brief, reopening an archived one, and the department reports.

Superusers are admins. ``business_performance`` is **not** implied here — this
is Marketing's board, not Strategy's.

The one rule worth stating twice: **a designer never approves their own work.**
``workflow.approve`` refuses it even for an admin who happens to be the
assigned designer, because a department signing off its own output is exactly
the gap this board is meant to close.
"""

ADMIN_GROUP = "marketing_admin"
DESIGNER_GROUP = "marketing_designer"

ADMIN_GROUPS = {ADMIN_GROUP}
#: Anybody who sees the whole board rather than just their own briefs.
BOARD_GROUPS = ADMIN_GROUPS | {DESIGNER_GROUP}


def _in(user, groups) -> bool:
    if not user or not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=groups).exists()


def is_admin(user) -> bool:
    """May assign designers, reassign, cancel anything, reopen, see reports."""
    return _in(user, ADMIN_GROUPS)


def is_designer(user) -> bool:
    """Is on the design team — sees the whole board."""
    return _in(user, BOARD_GROUPS)


def can_see_board(user) -> bool:
    """May see every brief, not only their own."""
    return is_designer(user)


def can_assign(user) -> bool:
    """Only the department admin allocates work. See the module docstring."""
    return is_admin(user)


def department_of(user) -> str:
    """The signed-in user's department, from the HR roster.

    There is no department on the Django user in this codebase — the roster
    (``employee_table``) is the only source, matched on email, exactly as
    ``apps.referrals`` does for its dropdown. Degrades to "" rather than
    raising: a roster that is unavailable must narrow what somebody can see,
    never break the page.
    """
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        return ""
    try:
        from apps.gceo_dashboard.models import EmployeeTable

        row = (EmployeeTable.objects
               .filter(email__iexact=email)
               .exclude(department__isnull=True).exclude(department="")
               .values_list("department", flat=True)
               .first())
        return (row or "").strip()
    except Exception:
        return ""


def _same_department(a, b) -> bool:
    """Compare two department names through the canonical speller.

    ``employee_table.department`` is free text with 57 spellings for far fewer
    real departments, so a raw string compare would deny a colleague access to
    their own department's brief over a trailing "DEPT". See
    ``core.departments`` for what it will and will not merge.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    try:
        from core.departments import compare_key

        return compare_key(a) == compare_key(b)
    except Exception:
        return a.lower() == b.lower()


def can_view(user, brief) -> bool:
    """The design team sees everything; everyone else sees what they are part of.

    "Part of" is deliberately wider than "raised by me": a colleague covering
    for someone on leave has to be able to find their department's brief, and
    the alternative is that they raise a duplicate of it.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if can_see_board(user):
        return True
    if brief.raised_by_id and brief.raised_by_id == user.id:
        return True
    if brief.assigned_designer_id and brief.assigned_designer_id == user.id:
        return True
    return _same_department(department_of(user), brief.department)


def can_edit_brief(user, brief) -> bool:
    """Change the wording, item, dates or priority.

    The requester may edit until a designer has started — after that, editing
    the brief under someone mid-way through the work is how a design gets made
    twice. From then on it is the admin's call.
    """
    if is_admin(user):
        return True
    if brief.is_closed:
        return False
    is_requester = brief.raised_by_id and brief.raised_by_id == user.id
    return bool(is_requester) and brief.status in {
        brief.STATUS_NEW, brief.STATUS_ASSIGNED}


def can_work(user, brief) -> bool:
    """Start or submit. The assigned designer, or an admin standing in."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if brief.assigned_designer_id and brief.assigned_designer_id == user.id:
        return True
    return is_admin(user)


def can_judge(user, brief) -> bool:
    """Approve, or send back for rework.

    Whoever raised it, or the department admin on their behalf — because a
    requester who has left, or is on leave, must not be able to strand a brief
    in review forever. An admin doing it is recorded as the actor either way.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if brief.raised_by_id and brief.raised_by_id == user.id:
        return True
    return is_admin(user)


def can_cancel(user, brief) -> bool:
    """Withdraw a brief. The requester, or an admin."""
    if is_admin(user):
        return True
    return bool(brief.raised_by_id and brief.raised_by_id == user.id)


def role_of(user) -> str:
    """The coarse label the frontend switches its screens on."""
    if is_admin(user):
        return "admin"
    if is_designer(user):
        return "designer"
    return "requester"
