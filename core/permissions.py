"""
Centralised RBAC permission classes.

Old backend had NO role-based enforcement — all endpoints required only IsAuthenticated.
New backend introduces explicit role enforcement while preserving backward compatibility
for old-frontend-facing endpoints (where IsAuthenticated is still the effective gate).

Role source: request.user.profile.segment + request.user.is_staff + request.user.is_superuser
New RBAC roles for new-feature APIs are stored as User groups or profile fields.
"""

from rest_framework.permissions import BasePermission, IsAuthenticated


class IsAuthenticatedAndActive(BasePermission):
    """Drop-in replacement for IsAuthenticated that also checks is_active."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
        )


class IsAdminUser(BasePermission):
    """Superuser or Django staff."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsAdminOrReadOnly(BasePermission):
    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

    def has_permission(self, request, view):
        if request.method in self.SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_staff)


class IsSuperUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


# ---------------------------------------------------------------------------
# New-feature RBAC — applied only to api/v1/* endpoints
# ---------------------------------------------------------------------------

from core.roles import (  # noqa: E402  (re-exported for backward compatibility)
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_OFFICER,
    tier_for_groups,
)


def get_user_role(user):
    """
    Derive the user's new-tier HF role WITHOUT discarding legacy group roles.

    Precedence:
      1. Django superuser            → admin
      2. Django staff                → manager
      3. Explicit new-tier groups    → admin / manager / customer
      4. Legacy groups (ceo/exco/…)  → mapped via core.roles.tier_for_groups
      5. Default                     → officer (old default for every RM)

    Step 4 is the migration-safety fix: a legacy ``ceo``/``exco`` user is NOT
    silently downgraded to officer. Their auth_group membership is preserved
    verbatim AND honoured here.
    """
    if user.is_superuser:
        return ROLE_ADMIN
    if user.is_staff:
        return ROLE_MANAGER
    groups = set(user.groups.values_list("name", flat=True))
    # Explicit new-tier group membership wins over the legacy mapping.
    if ROLE_ADMIN in groups:
        return ROLE_ADMIN
    if ROLE_MANAGER in groups:
        return ROLE_MANAGER
    if ROLE_CUSTOMER in groups:
        return ROLE_CUSTOMER
    # Legacy groups (the migrated source of truth) drive the tier.
    return tier_for_groups(groups)


class HFBasePermission(BasePermission):
    """
    Base class for all new-feature permission checks.
    Subclasses set `allowed_roles` to restrict access.
    """

    allowed_roles: list[str] = [ROLE_ADMIN, ROLE_MANAGER, ROLE_OFFICER, ROLE_CUSTOMER]

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_active):
            return False
        role = get_user_role(request.user)
        return role in self.allowed_roles


class AdminOnly(HFBasePermission):
    allowed_roles = [ROLE_ADMIN]


class AdminOrManager(HFBasePermission):
    allowed_roles = [ROLE_ADMIN, ROLE_MANAGER]


class AdminManagerOrOfficer(HFBasePermission):
    allowed_roles = [ROLE_ADMIN, ROLE_MANAGER, ROLE_OFFICER]


class AllRoles(HFBasePermission):
    allowed_roles = [ROLE_ADMIN, ROLE_MANAGER, ROLE_OFFICER, ROLE_CUSTOMER]


class RBACQueryFilter:
    """
    Applied BEFORE any ORM query in the agent and analytics layers.
    Prevents customers from seeing cross-customer data at the queryset level.
    """

    @staticmethod
    def get_user_branch(user_id: int) -> str | None:
        from apps.portfolio.models import Profile
        try:
            return Profile.objects.get(user_id=user_id).branch
        except Profile.DoesNotExist:
            return None

    @staticmethod
    def get_user_sales_code(user_id: int) -> str | None:
        from apps.portfolio.models import Profile
        try:
            return Profile.objects.get(user_id=user_id).sales_code
        except Profile.DoesNotExist:
            return None

    ROLE_FILTERS = {
        ROLE_ADMIN: lambda model, qs, uid: qs,
        ROLE_MANAGER: lambda model, qs, uid: (
            qs.filter(branch=RBACQueryFilter.get_user_branch(uid))
            if hasattr(model, "branch") else qs
        ),
        ROLE_OFFICER: lambda model, qs, uid: (
            qs.filter(sales_code=RBACQueryFilter.get_user_sales_code(uid))
            if hasattr(model, "sales_code") else qs
        ),
        ROLE_CUSTOMER: lambda model, qs, uid: (
            qs.filter(cust_id=uid) if hasattr(model, "cust_id") else qs.none()
        ),
    }

    @classmethod
    def apply(cls, model, user):
        from rest_framework.exceptions import PermissionDenied
        role = get_user_role(user)
        qs = model.objects.all()
        filter_fn = cls.ROLE_FILTERS.get(role)
        if not filter_fn:
            raise PermissionDenied("Unknown role")
        return filter_fn(model, qs, user.id)


# ---------------------------------------------------------------------------
# Legacy group-name permissions — verbatim parity with hf_group_project-master.
# The old project gated endpoints with `request.user.groups.filter(name=...)`.
# These classes reproduce that exact behaviour so migrated users keep working
# against any endpoint ported from the old backend.
# ---------------------------------------------------------------------------

def InGroup(*group_names):
    """
    Build a DRF permission class that grants access if the authenticated user
    belongs to ANY of the given legacy groups (or is a superuser).

    Usage:  permission_classes = [InGroup("ceo", "exco")]
    """
    names = set(group_names)

    class _InGroup(BasePermission):
        allowed_groups = names

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated and user.is_active):
                return False
            if user.is_superuser:
                return True
            return user.groups.filter(name__in=names).exists()

    _InGroup.__name__ = "InGroup_" + "_".join(sorted(names)) if names else "InGroup"
    return _InGroup


# Named singletons for the most common legacy gates (mirror old view classes).
CeoPermissions = InGroup("ceo")
ExcoPermissions = InGroup("exco")
PortfolioMgtPermissions = InGroup("portfolio_mgt")
TlPortfolioPermissions = InGroup("tl_portfolio")
BranchPortfolioPermissions = InGroup("branch_portfolio")
CollectionMgtPermissions = InGroup("collection_mgt")
TlCollectionPermissions = InGroup("tl_collection")
RightsIssuePermissions = InGroup("rights_issue")
TlRightsIssuePermissions = InGroup("TLrights_issue")
HfdiAdminPermissions = InGroup("hfdi_admin")
