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


def _own_scope(user):
    """The caller's default scope: their branch if they have one, else their
    sales code, else the bank. Mirrors the legacy views, which fell back to
    ``profile.branch`` whenever no explicit filter was supplied."""
    from apps.portfolio.models import Profile
    profile = Profile.objects.filter(user_id=user.id).first()
    if profile:
        if profile.branch:
            return "branch", profile.branch
        if profile.sales_code:
            return "rm", profile.sales_code
    return "bank", ""


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
        elif not _may_cross_scope(request.user):
            # A user without cross-scope rights may still ask explicitly — but
            # only for the scope they already own.
            own_scope, own_value = _own_scope(request.user)
            if (scope, value.lower()) != (own_scope, str(own_value).lower()):
                scope, value = own_scope, own_value

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
