"""DMC targets API — one endpoint every module's KPI tiles can call.

``GET staff_management/dmc-targets/`` returns the annual target plus its
pro-rated windows for every metric in :mod:`apps.staff_management.targets`, at
whatever scope the caller asks for. Callers that pass no scope get their *own*
one, inferred from their portfolio profile, so an RM's dashboard and a branch
manager's dashboard can share the same hook.

``GET staff_management/dmc-targets/scopes/`` lists the branches, zones, team
leaders and RMs that actually have targets loaded — used to populate pickers and
to sanity-check an ETL load.
"""

from datetime import date

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, extend_schema

from . import targets as tgt

TAG = "Staff Management — DMC Targets"

# Groups allowed to look at any scope. Everyone else is pinned to their own
# branch / sales code, matching how branch_portfolio gates cross-branch reads.
CROSS_SCOPE_GROUPS = {"ceo", "exco", "portfolio_mgt", "tl_portfolio",
                      "staff_mgt", "business_performance"}


def _may_cross_scope(user):
    if user.is_superuser or user.is_staff:
        return True
    return bool(set(user.groups.values_list("name", flat=True)) & CROSS_SCOPE_GROUPS)


def _own_team_leader(user):
    """The caller's own name as it appears in the branch→TL map, or None.

    Checked ONLY for members of the ``tl_portfolio`` group. Branch managers can
    also show up as somebody's team leader, and matching them here would swap a
    BM's branch plan for a multi-branch one — so the group gate is what keeps
    this from mis-scoping people.
    """
    if not user.groups.filter(name="tl_portfolio").exists():
        return None
    name = (user.get_full_name() or "").strip()
    if not name:
        return None
    return name if tgt.tl_branches(name) else None


# The RM Portfolio group. ``lib/roleNavConfig.tsx`` maps ``portfolio_mgt`` to
# /rm-portfolio, and every actual on that dashboard is already fetched by the
# signed-in user's ``profile.sales_code`` (apps/portfolio/views.py). So for
# these users the sales code outranks the branch when picking a default scope —
# otherwise an RM's own deposits get scored against the whole branch's plan,
# which reads as ~2% achievement on a branch with a dozen RMs.
RM_GROUP = "portfolio_mgt"


def _own_scopes(user):
    """Every scope this caller personally owns, best default first.

    Returned as ``[(scope, value), ...]``:

    * ``team_leader`` when the branch→TL map knows them (``tl_portfolio`` only),
    * ``rm`` before ``branch`` for RM Portfolio users — see :data:`RM_GROUP`,
    * ``branch`` then ``rm`` for everyone else, which is the order the legacy
      views used (they fell back to ``profile.branch`` whenever no explicit
      filter was supplied), so branch managers keep the scope they had.

    The list — not just the first entry — is what an explicit ``?scope=`` is
    checked against, so a user may always ask for a scope they genuinely own
    even when it is not their default.
    """
    from apps.portfolio.models import Profile

    out = []
    tl = _own_team_leader(user)
    if tl:
        out.append(("team_leader", tl))

    profile = Profile.objects.filter(user_id=user.id).first()
    branch = (getattr(profile, "branch", "") or "").strip()
    sales_code = (getattr(profile, "sales_code", "") or "").strip()

    if sales_code and user.groups.filter(name=RM_GROUP).exists():
        out.append(("rm", sales_code))
    if branch:
        out.append(("branch", branch))
    if sales_code:
        out.append(("rm", sales_code))

    seen, unique = set(), []
    for scope, value in out:
        key = (scope, str(value).lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append((scope, value))
    return unique or [("bank", "")]


def _own_scope(user):
    """The caller's default scope — the first of :func:`_own_scopes`."""
    return _own_scopes(user)[0]


def _own_value(user, scope):
    """The caller's own value for ``scope``, or ``""`` if they have none.

    This is what lets a page ask for ``?scope=rm`` without knowing the sales
    code: the RM dashboard knows *which* scope it is showing, the backend knows
    *whose*.
    """
    for own_scope, own_value in _own_scopes(user):
        if own_scope == scope:
            return str(own_value)
    return ""


@extend_schema(
    tags=[TAG],
    parameters=[
        OpenApiParameter("scope", str, description="bank | zone | branch | team_leader | rm"),
        OpenApiParameter("value", str, description="Branch name or code, zone, team leader, or sales code"),
        OpenApiParameter("year", int, description="Planning cycle (defaults to the current year)"),
    ],
)
class DmcTargetsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        p = request.query_params
        scope = (p.get("scope") or "").strip().lower()
        value = (p.get("value") or "").strip()

        if not scope:
            scope, value = _own_scope(request.user)
        else:
            # "My own <scope>" — the caller names the scope, we fill in whose.
            # Without this an RM page asking for ?scope=rm would have to know
            # its own sales code, and would otherwise resolve to no rows.
            if not value and scope in ("rm", "branch", "team_leader"):
                value = _own_value(request.user, scope)
            if not _may_cross_scope(request.user):
                # A user without cross-scope rights may still ask explicitly —
                # but only for a scope they already own.
                owned = {(s, str(v).lower()) for s, v in _own_scopes(request.user)}
                if (scope, value.lower()) not in owned:
                    scope, value = _own_scope(request.user)

        year = p.get("year")
        try:
            year = int(year) if year else date.today().year
        except (TypeError, ValueError):
            year = date.today().year

        try:
            data = tgt.rollup(scope, value, year=year)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(data)


@extend_schema(tags=[TAG])
class DmcTargetScopesView(APIView):
    """Which scopes actually carry targets — also the quickest ETL health check."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        models = tgt._models()
        branch, staff = models["branch"], models["staff"]

        def distinct(model, field):
            qs = tgt._active(model.objects.all(), model)
            return sorted({
                str(v).strip() for v in qs.values_list(field, flat=True)
                if v not in (None, "")
            })

        return Response({
            "branches":     distinct(branch, "staff_branch"),
            "zones":        distinct(branch, "staff_zone"),
            "team_leaders": distinct(staff, "team_leader"),
            "rms":          distinct(staff, "sales_code"),
            "metrics":      list(tgt.META.values()),
            "row_counts": {
                branch._meta.db_table: tgt._active(branch.objects.all(), branch).count(),
                staff._meta.db_table:  tgt._active(staff.objects.all(), staff).count(),
            },
        })
