"""
Canonical role registry — single source of truth for HF Group RBAC.

The LEGACY system (hf_group_project-master) expressed every role as a Django
``auth.Group``. There is NO custom user model and NO profile-based role flag —
authorisation was done purely with ``request.user.groups.filter(name=...)``.

To migrate users *without losing their defined roles*, the new backend keeps
those exact group names as the authoritative source of truth, and ALSO exposes a
coarser, forward-looking role tier (admin/manager/officer/customer) used by the
new ``api/v1/*`` feature endpoints. Both live side by side: the legacy group is
never thrown away, and the new tier is derived from it.

Whenever this mapping changes, only this file needs to change.
"""

# ---------------------------------------------------------------------------
# Legacy roles — the exact auth_group.name values used by the old project.
# Verified by grepping `groups.filter(name=...)` across every old app.
# ---------------------------------------------------------------------------
LEGACY_ROLES = (
    "ceo",
    "exco",
    "portfolio_mgt",
    "tl_portfolio",
    "branch_portfolio",
    "collection_mgt",
    "tl_collection",
    "rights_issue",
    "TLrights_issue",
    "hfdi_admin",
)

# Human-readable descriptions (used by seed_roles output / admin).
LEGACY_ROLE_DESCRIPTIONS = {
    "ceo": "Group CEO — full read access across all segments and branches.",
    "exco": "Executive committee — full read access across all segments.",
    "portfolio_mgt": "Portfolio management — manages the portfolio reallocation book.",
    "tl_portfolio": "Team leader, portfolio — segment-level portfolio oversight.",
    "branch_portfolio": "Branch portfolio — branch-level relationship managers.",
    "collection_mgt": "Collections management — manages the collections book.",
    "tl_collection": "Team leader, collections — segment-level collections oversight.",
    "rights_issue": "Rights issue — front-line rights issue users.",
    "TLrights_issue": "Team leader, rights issue — rights issue oversight.",
    "hfdi_admin": "HFDI administrator — HFDI module administration.",
}

# ---------------------------------------------------------------------------
# New forward-looking role tiers (used by core.permissions for api/v1/*).
# ---------------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_OFFICER = "officer"
ROLE_CUSTOMER = "customer"

ROLE_TIERS = (ROLE_ADMIN, ROLE_MANAGER, ROLE_OFFICER, ROLE_CUSTOMER)

# Tier precedence — higher index == more privilege. Used to pick the strongest
# tier when a user belongs to several legacy groups.
_TIER_RANK = {
    ROLE_CUSTOMER: 0,
    ROLE_OFFICER: 1,
    ROLE_MANAGER: 2,
    ROLE_ADMIN: 3,
}

# ---------------------------------------------------------------------------
# New-feature roles. These are NOT in the legacy backend but ARE expected by the
# current frontend (lib/roleNavConfig.tsx / types Permissions enum) for modules
# built in the new backend. Registering them means admins can assign them and
# the frontend nav lights up. They start with zero members after migration.
# ---------------------------------------------------------------------------
NEW_ROLES = (
    "staff_mgt",
    "exco_initiatives",
    "exco_initiatives_admin",
    "hfdi_officer",
)

NEW_ROLE_DESCRIPTIONS = {
    "staff_mgt": "Staff management / administration module.",
    "exco_initiatives": "EXCO initiatives — regular user.",
    "exco_initiatives_admin": "EXCO initiatives — administrator.",
    "hfdi_officer": "HFDI module — officer (read-only dashboard).",
}

# Every role the system knows about (legacy + new).
ALL_ROLES = LEGACY_ROLES + NEW_ROLES
ALL_ROLE_DESCRIPTIONS = {**LEGACY_ROLE_DESCRIPTIONS, **NEW_ROLE_DESCRIPTIONS}

# ---------------------------------------------------------------------------
# Group name -> new tier.  Documented and intentionally conservative:
# executives/admins map to admin, *_mgt and team leaders to manager, and
# front-line groups to officer. Tune here only.
# ---------------------------------------------------------------------------
ROLE_TO_TIER = {
    # legacy
    "ceo": ROLE_ADMIN,
    "exco": ROLE_ADMIN,
    "hfdi_admin": ROLE_ADMIN,
    "portfolio_mgt": ROLE_MANAGER,
    "collection_mgt": ROLE_MANAGER,
    "tl_portfolio": ROLE_MANAGER,
    "tl_collection": ROLE_MANAGER,
    "TLrights_issue": ROLE_MANAGER,
    "branch_portfolio": ROLE_OFFICER,
    "rights_issue": ROLE_OFFICER,
    # new
    "exco_initiatives_admin": ROLE_ADMIN,
    "staff_mgt": ROLE_MANAGER,
    "exco_initiatives": ROLE_OFFICER,
    "hfdi_officer": ROLE_OFFICER,
}

# Backward-compatible alias (older imports referenced this name).
LEGACY_ROLE_TO_TIER = ROLE_TO_TIER


def tier_for_groups(group_names) -> str:
    """
    Return the strongest new-tier role implied by a collection of legacy group
    names. Falls back to ``officer`` (the old default for every authenticated
    portfolio RM) when no known legacy group is present.
    """
    best = None
    best_rank = -1
    for name in group_names:
        tier = ROLE_TO_TIER.get(name)
        if tier is None:
            continue
        rank = _TIER_RANK[tier]
        if rank > best_rank:
            best, best_rank = tier, rank
    return best or ROLE_OFFICER
