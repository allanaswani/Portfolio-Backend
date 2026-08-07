"""Referral API — capture, role-scoped listing, allocation and status updates.

Authorisation mirrors ``apps.mortgages``: group-name RBAC via helpers in
``apps.referrals.rbac``. Three audiences share these endpoints:

* **Supervisors** (``telesales_supervisor`` + superusers) see every referral and are
  the only ones who may allocate/reassign.
* **Agents** (``telesales_agent``) see the referrals allocated to them and may move
  their own referrals through contacted → converted / rejected.
* **Capturers** (any other authenticated staffer) see only referrals they submitted.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from .models import Referral
from .rbac import AGENT_GROUP, is_allocatable, is_supervisor
from .serializers import ReferralSerializer, TelesalesAgentSerializer

User = get_user_model()

_BASE_QS = Referral.objects.select_related("created_by", "assigned_to", "allocated_by")


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
    permission_classes = [IsAuthenticated]
    serializer_class = ReferralSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "assigned_to", "is_possible_duplicate", "staff_verified"]
    search_fields = [
        "referral_ref", "customer_name", "national_id", "phone",
        "pf_number", "sales_code", "email",
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
    permission_classes = [IsAuthenticated]
    serializer_class = ReferralSerializer

    def get_queryset(self):
        return _scoped(self.request.user)


@extend_schema(tags=["Referrals"])
class ReferralAllocateView(APIView):
    """Allocate or reassign a referral to a telesales agent. Supervisor-only.

    Body: ``{"assigned_to": <user id>}``. Sets ``assigned_to``, stamps
    ``allocated_by``/``allocated_at``, and advances an ``unallocated`` referral to
    ``allocated`` (a reassignment keeps whatever working status it already has).
    """

    permission_classes = [IsAuthenticated]

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
                {"assigned_to": "User is not a telesales team member."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        referral.assigned_to = agent
        referral.allocated_by = request.user
        referral.allocated_at = timezone.now()
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

    permission_classes = [IsAuthenticated]

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
        return Response(ReferralSerializer(referral).data)


@extend_schema(tags=["Referrals"])
class TelesalesAgentsView(APIView):
    """List telesales agents for the allocation dropdown. Supervisor-only."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_supervisor(request.user):
            return Response(
                {"detail": "Only telesales supervisors may view the agent roster."},
                status=status.HTTP_403_FORBIDDEN,
            )
        agents = (
            User.objects.filter(is_active=True, groups__name=AGENT_GROUP)
            .distinct()
            .order_by("first_name", "username")
        )
        return Response(TelesalesAgentSerializer(agents, many=True).data)


@extend_schema(tags=["Referrals"])
class ReferralStatsView(APIView):
    """Pipeline KPIs (counts by status), scoped to what the caller may see."""

    permission_classes = [IsAuthenticated]

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
