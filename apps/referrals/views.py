"""Referral API — capture, role-scoped listing, allocation and status updates.

Authorisation mirrors ``apps.mortgages``: group-name RBAC via helpers in
``apps.referrals.rbac``. Three audiences share these endpoints:

* **Supervisors** (``telesales_supervisor`` + superusers) see every referral and are
  the only ones who may allocate/reassign.
* **Agents** (``telesales_agent``) see the referrals allocated to them and may move
  their own referrals through contacted → converted / rejected.
* **Capturers** (``referrals_user``, ``postbank_referrer``) see only referrals they
  submitted, plus any allocated to them.

Nobody else reaches these endpoints: access is a role an administrator gives
(see :func:`apps.referrals.rbac.has_access`), not something every login has.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from .models import Referral
from .rbac import USER_GROUP, has_access, is_allocatable, is_postbank, is_supervisor
from .serializers import ReferralSerializer, TelesalesAgentSerializer

User = get_user_model()

_BASE_QS = Referral.objects.select_related("created_by", "assigned_to", "allocated_by")


class HasReferralsAccess(BasePermission):
    """The Referrals role, given on the Users screen (or a superuser)."""

    message = ("Referrals has not been given to your account. Ask an "
               "administrator to add the Referrals role on the Users screen.")

    def has_permission(self, request, view):
        return has_access(request.user)


ACCESS = [IsAuthenticated, HasReferralsAccess]


def _scoped(user):
    """Referrals visible to ``user`` under the module's role boundaries.

    Supervisors see all; everyone else sees referrals they captured OR that are
    allocated to them (an agent who also captures sees both).
    """
    if is_supervisor(user):
        return _BASE_QS
    return _BASE_QS.filter(Q(created_by=user) | Q(assigned_to=user))


@extend_schema(tags=["Referrals"])
class ReferralListCreateView(generics.ListCreateAPIView):
    permission_classes = ACCESS
    serializer_class = ReferralSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        "status", "assigned_to", "is_possible_duplicate", "staff_verified",
        "branch", "segment", "department",
    ]
    search_fields = [
        "referral_ref", "customer_name", "national_id", "phone",
        "pf_number", "sales_code", "email", "branch", "segment", "department",
    ]
    ordering_fields = ["created_at", "allocated_at", "status", "customer_name"]

    def get_queryset(self):
        return _scoped(self.request.user)

    def perform_create(self, serializer):
        # The authenticated user who keys the referral in is captured automatically;
        # PF number remains the referrer's field of record (they may differ).
        serializer.save(created_by=self.request.user)


@extend_schema(tags=["Referrals"])
class ReferralDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Read/update a referral; delete is superuser-only.

    DELETE was previously available to anyone the referral was scoped to, which
    let a capturer erase their own submission. Removing a referral is an admin
    act (clearing test rows, GDPR-style erasure), so it is restricted to
    superusers. simple_history keeps the audit trail either way.
    """

    permission_classes = ACCESS
    serializer_class = ReferralSerializer

    def get_queryset(self):
        return _scoped(self.request.user)

    def destroy(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            return Response(
                {"detail": "Only a superuser may delete a referral."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Superusers see everything via _scoped, so the object lookup is unchanged.
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=["Referrals"])
class ReferralAllocateView(APIView):
    """Allocate or reassign a referral to a telesales agent. Supervisor-only.

    Body: ``{"assigned_to": <user id>}``. Sets ``assigned_to``, stamps
    ``allocated_by``/``allocated_at``, and advances an ``unallocated`` referral to
    ``allocated`` (a reassignment keeps whatever working status it already has).
    """

    permission_classes = ACCESS

    def post(self, request, pk):
        if not is_supervisor(request.user):
            return Response(
                {"detail": "Only telesales supervisors may allocate referrals."},
                status=status.HTTP_403_FORBIDDEN,
            )
        referral = generics.get_object_or_404(Referral, pk=pk)

        agent_id = request.data.get("assigned_to")
        if not agent_id:
            return Response(
                {"assigned_to": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        agent = User.objects.filter(pk=agent_id).first()
        if not agent:
            return Response(
                {"assigned_to": "No such user."}, status=status.HTTP_400_BAD_REQUEST
            )
        if not is_allocatable(agent):
            return Response(
                {"assigned_to": "This account cannot be given referrals "
                                "(inactive, or a Postbank account)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Allocating is giving this person work in the module, so it gives them
        # the module too, if they did not have it.
        if not has_access(agent):
            from django.contrib.auth.models import Group

            agent.groups.add(Group.objects.get_or_create(name=USER_GROUP)[0])

        referral.assigned_to = agent
        referral.allocated_by = request.user
        referral.allocated_at = timezone.now()
        # Credit the referral to the code the assignee works under, captured now
        # so it survives any later change to their Profile.
        referral.assigned_sales_code = (getattr(getattr(agent, "profile", None), "sales_code", "") or "").strip()
        if referral.status == Referral.STATUS_UNALLOCATED:
            referral.status = Referral.STATUS_ALLOCATED
        referral.save()
        return Response(ReferralSerializer(referral).data)


@extend_schema(tags=["Referrals"])
class ReferralStatusView(APIView):
    """Advance a referral's working status. Assigned agent or a supervisor only.

    Body: ``{"status": "contacted" | "converted" | "rejected", "notes": "..."}``.
    Stamps ``contacted_at`` / ``converted_at`` the first time those states are set
    (``converted_at`` also drives the retention clock for converted referrals).
    """

    permission_classes = ACCESS

    def post(self, request, pk):
        referral = generics.get_object_or_404(Referral, pk=pk)

        is_owner_agent = referral.assigned_to_id == request.user.id
        if not (is_supervisor(request.user) or is_owner_agent):
            return Response(
                {"detail": "You may only update referrals allocated to you."},
                status=status.HTTP_403_FORBIDDEN,
            )

        new_status = request.data.get("status")
        if new_status not in Referral.AGENT_SETTABLE_STATUSES:
            return Response(
                {"status": f"Must be one of {sorted(Referral.AGENT_SETTABLE_STATUSES)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        referral.status = new_status
        now = timezone.now()
        if new_status == Referral.STATUS_CONTACTED and not referral.contacted_at:
            referral.contacted_at = now
        if new_status == Referral.STATUS_CONVERTED and not referral.converted_at:
            referral.converted_at = now
        notes = request.data.get("notes")
        if notes is not None:
            referral.notes = notes
        referral.save()

        # A rejected referral is discarded rather than parked: the pipeline should
        # only ever show live work. The status and notes are saved first so the
        # simple_history row records WHY it went, and the deletion itself is
        # history-tracked too, so nothing is lost for audit.
        if new_status == Referral.STATUS_REJECTED:
            data = ReferralSerializer(referral).data
            referral.delete()
            return Response({**data, "deleted": True})

        return Response(ReferralSerializer(referral).data)


@extend_schema(tags=["Referrals"])
class TelesalesAgentsView(APIView):
    """Roster for the allocation dropdown. Supervisor-only.

    Referrals are worked by relationship managers and branch sales staff as well
    as the telesales team, but this used to return only ``telesales_agent``
    members — so an RM could never be picked. It now returns every active
    account, each carrying the sales code, branch and segment from their Profile
    so the supervisor can tell two people with similar names apart and see which
    sales code the referral will be credited to.
    """

    permission_classes = ACCESS

    def get(self, request):
        if not is_supervisor(request.user):
            return Response(
                {"detail": "Only telesales supervisors may view the allocation roster."},
                status=status.HTTP_403_FORBIDDEN,
            )
        from .rbac import POSTBANK_GROUP

        users = (
            User.objects.filter(is_active=True)
            .exclude(groups__name=POSTBANK_GROUP)
            .select_related("profile")
            .prefetch_related("groups")
            .order_by("first_name", "last_name", "username")
        )
        return Response(TelesalesAgentSerializer(users, many=True).data)


@extend_schema(tags=["Referrals"])
class ReferralDepartmentsView(APIView):
    """Distinct department names from the HR roster (``employee_table``), for the
    referral capture Department dropdown. Read-only; never errors the form."""

    permission_classes = ACCESS

    def get(self, request):
        try:
            from apps.gceo_dashboard.models import EmployeeTable

            depts = (
                EmployeeTable.objects
                .exclude(department__isnull=True).exclude(department="")
                .values_list("department", flat=True)
                .distinct()
            )
            return Response(sorted({d.strip() for d in depts if d and d.strip()}))
        except Exception:
            # HR roster unavailable — return empty so the dropdown just has no options.
            return Response([])


@extend_schema(tags=["Referrals"])
class ReferralStatsView(APIView):
    """Pipeline KPIs (counts by status), scoped to what the caller may see."""

    permission_classes = ACCESS

    def get(self, request):
        qs = _scoped(request.user)
        by_status = dict(
            qs.values_list("status").annotate(n=Count("id")).values_list("status", "n")
        )
        return Response({
            "total": qs.count(),
            "unallocated": by_status.get(Referral.STATUS_UNALLOCATED, 0),
            "allocated": by_status.get(Referral.STATUS_ALLOCATED, 0),
            "contacted": by_status.get(Referral.STATUS_CONTACTED, 0),
            "converted": by_status.get(Referral.STATUS_CONVERTED, 0),
            "rejected": by_status.get(Referral.STATUS_REJECTED, 0),
            "expired": by_status.get(Referral.STATUS_EXPIRED, 0),
            "possible_duplicates": qs.filter(is_possible_duplicate=True).count(),
        })


@extend_schema(tags=["Referrals"])
class ReferralMonthlyReportView(APIView):
    """The monthly Referrals report workbook. Supervisor-only.

    ``?month=YYYY-MM`` (default: last month). The same workbook the
    ``send_referrals_report`` mail carries, for any month, on demand.
    """

    permission_classes = ACCESS

    def get(self, request):
        import re

        from django.http import HttpResponse

        from apps.observability.report_xlsx import XLSX_MIME

        from . import report

        if not is_supervisor(request.user):
            return Response(
                {"detail": "Only telesales supervisors may download the referrals report."},
                status=status.HTTP_403_FORBIDDEN,
            )
        raw = (request.query_params.get("month") or "").strip()
        if raw:
            match = re.fullmatch(r"(\d{4})-(\d{2})", raw)
            if not match or not 1 <= int(match.group(2)) <= 12:
                return Response({"month": "Use YYYY-MM, e.g. 2026-10."},
                                status=status.HTTP_400_BAD_REQUEST)
            year, month = int(match.group(1)), int(match.group(2))
        else:
            year, month = report.previous_month()
        response = HttpResponse(report.workbook(year, month), content_type=XLSX_MIME)
        response["Content-Disposition"] = (
            f'attachment; filename="{report.filename(year, month)}"')
        return response
