"""Accounts for a partner institution reach only the module they were given.

Postbank's team sign in to this system to capture referrals (Nov 2026). Most
endpoints here only ask "is this somebody signed in?", because until now every
account belonged to a member of the bank's staff - the AI assistant alone reads
figures from across the bank. A partner's account must not inherit that.

So the check sits where every API request is authenticated
(:mod:`core.authentication`): a member of a group in :data:`PARTNER_PATHS` is
refused with 403 on any path outside the ones listed for that group. Sign-in,
the second factor, sign-out, the profile the frontend reads the person's roles
from, the branch/segment lists the referral form offers, and the page-view
tracker stay open, so the person can still sign in and use their module.

A superuser is never confined. Paths are matched on ``request.path_info``, the
path the URL patterns themselves are matched on.
"""

from rest_framework.exceptions import PermissionDenied

#: What every confined account still needs to sign in and find its way.
_ALWAYS_OPEN = (
    "/auth/api/token/",
    "/auth/logout/",
    "/auth/generate-otp/",
    "/auth/verify-otp/",
    "/auth/change_password/",
    "/auth/api/password_reset/",
    "/auth/user-meta/",
    "/portfolio/userprofile/",
    "/api/v1/analytics/activity/track/",
)

#: Partner group → the API paths its members may reach.
PARTNER_PATHS = {
    "postbank_referrer": ("/referrals/",),
}


def check(request, user):
    """Raise 403 when ``user`` is a partner account outside its own paths."""
    if user is None or not getattr(user, "is_authenticated", False):
        return
    if getattr(user, "is_superuser", False):
        return
    names = set(user.groups.values_list("name", flat=True)) & set(PARTNER_PATHS)
    if not names:
        return
    path = getattr(request, "path_info", "") or getattr(request, "path", "")
    allowed = _ALWAYS_OPEN + tuple(p for n in names for p in PARTNER_PATHS[n])
    if any(path.startswith(prefix) for prefix in allowed):
        return
    raise PermissionDenied("This account opens the Referrals module only.")
