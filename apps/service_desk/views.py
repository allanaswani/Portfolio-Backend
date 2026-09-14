"""Service desk endpoints.

Every write goes through ``workflow``, never through a serializer's ``save()``.
That is what guarantees a timeline entry and an email for each transition — a
PATCH that could set ``status`` directly would be a step nobody recorded, which
is the failure this module exists to prevent.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import rbac, reports, workflow
from .models import (
    DeskSettings, Holiday, Ticket, TicketCategory, TicketComment, TicketEvent,
)
from .serializers import (
    DeskSettingsSerializer, HolidaySerializer, TicketCategorySerializer,
    TicketCommentSerializer, TicketCreateSerializer, TicketDetailSerializer,
    TicketListSerializer,
)

TAG = ["Service Desk"]


class DeskPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 500


class IsManager(IsAuthenticated):
    message = "Only the service desk managers can change this."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and rbac.is_manager(request.user)


def _get_ticket_or_403(request, reference):
    """Resolve a ticket and check visibility in one place.

    A ticket somebody may not see returns 404, not 403: 403 confirms that a
    reference exists, which is enough to probe for other people's queries.
    """
    ticket = (Ticket.objects
              .select_related("category", "raised_by", "assigned_to")
              .prefetch_related("events__actor", "comments__author")
              .filter(reference=reference).first())
    if ticket is None or not rbac.can_view(request.user, ticket):
        return None
    return ticket


@extend_schema(tags=TAG)
class TicketListCreateView(generics.ListCreateAPIView):
    """The queue, scoped to what the viewer may see."""

    permission_classes = [IsAuthenticated]
    pagination_class = DeskPagination

    def get_serializer_class(self):
        return TicketCreateSerializer if self.request.method == "POST" else TicketListSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = (Ticket.objects.for_user(self.request.user)
              .select_related("category", "raised_by", "assigned_to")
              .annotate(comment_count=Count("comments", distinct=True)))

        scope = params.get("scope") or ""
        if scope == "mine":
            qs = qs.filter(assigned_to=self.request.user)
        elif scope == "raised":
            qs = qs.filter(raised_by=self.request.user)
        elif scope == "unassigned":
            qs = qs.filter(assigned_to__isnull=True)

        status_param = params.get("status") or ""
        if status_param == "open":
            qs = qs.filter(status__in=reports.OPEN_STATUSES)
        elif status_param:
            qs = qs.filter(status__in=[s for s in status_param.split(",") if s])

        if params.get("category"):
            qs = qs.filter(category__slug=params["category"])
        if params.get("priority"):
            qs = qs.filter(priority=params["priority"])
        if params.get("assigned_to"):
            qs = qs.filter(assigned_to__username__iexact=params["assigned_to"])

        if params.get("overdue") in ("1", "true", "True"):
            qs = qs.filter(resolution_due_at__lt=timezone.now(),
                           status__in=reports.OPEN_STATUSES)

        search = (params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(reference__icontains=search)
                | Q(subject__icontains=search)
                | Q(body__icontains=search)
                | Q(on_behalf_of__icontains=search)
                | Q(raised_by__username__icontains=search)
            )

        ordering = params.get("ordering") or "-created_at"
        allowed = {
            "-created_at", "created_at", "resolution_due_at", "-resolution_due_at",
            "priority", "-priority", "status", "-status",
        }
        return qs.order_by(ordering if ordering in allowed else "-created_at")

    def create(self, request, *args, **kwargs):
        form = TicketCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data

        # Logging on somebody's behalf is a handler's job — otherwise anyone
        # could raise a ticket in a colleague's name and receive their mail.
        if data.get("on_behalf_of") and not rbac.is_handler(request.user):
            raise serializers.ValidationError({
                "on_behalf_of": "Only the desk can log a query for somebody else.",
            })

        ticket = workflow.create(
            subject=data["subject"], body=data.get("body", ""),
            category=data.get("category"),
            priority=data.get("priority", Ticket.PRIORITY_NORMAL),
            raised_by=None if data.get("on_behalf_of") else request.user,
            on_behalf_of=data.get("on_behalf_of", ""),
            requester_email=data.get("requester_email", ""),
            requester_department=data.get("requester_department", ""),
            requester_branch=data.get("requester_branch", ""),
            actor=request.user,
        )
        return Response(
            TicketDetailSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_201_CREATED)


@extend_schema(tags=TAG)
class TicketDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        ticket = _get_ticket_or_403(request, reference)
        if ticket is None:
            return Response({"detail": "No such ticket."}, status=404)
        return Response(TicketDetailSerializer(ticket, context={"request": request}).data)


class _TicketAction(APIView):
    """Shared plumbing: fetch, authorise, act, return the fresh ticket."""

    permission_classes = [IsAuthenticated]
    #: Overridden per action.
    def allowed(self, user, ticket):
        return rbac.can_view(user, ticket)

    def act(self, request, ticket):  # pragma: no cover - abstract
        raise NotImplementedError

    def post(self, request, reference):
        ticket = _get_ticket_or_403(request, reference)
        if ticket is None:
            return Response({"detail": "No such ticket."}, status=404)
        if not self.allowed(request.user, ticket):
            return Response({"detail": self.denial(ticket)}, status=403)
        result = self.act(request, ticket)
        if isinstance(result, Response):
            return result
        ticket.refresh_from_db()
        return Response(TicketDetailSerializer(ticket, context={"request": request}).data)

    def denial(self, ticket):
        return "You cannot do that on this ticket."


@extend_schema(tags=TAG)
class TicketCommentView(_TicketAction):
    def allowed(self, user, ticket):
        return rbac.can_comment(user, ticket)

    def act(self, request, ticket):
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"body": "Write something first."}, status=400)
        internal = bool(request.data.get("is_internal")) and rbac.is_handler(request.user)
        workflow.comment(ticket, request.user, body, is_internal=internal)
        return None


@extend_schema(tags=TAG)
class TicketStatusView(_TicketAction):
    def allowed(self, user, ticket):
        return rbac.is_handler(user)

    def denial(self, ticket):
        return "Only the desk can move a ticket through its working statuses."

    def act(self, request, ticket):
        wanted = (request.data.get("status") or "").strip()
        allowed = {Ticket.STATUS_ASSIGNED, Ticket.STATUS_IN_PROGRESS, Ticket.STATUS_ON_HOLD}
        if wanted not in allowed:
            return Response(
                {"status": f"Must be one of: {', '.join(sorted(allowed))}. "
                           f"Resolving, closing and reopening have their own actions, "
                           f"because each of them tells somebody something."},
                status=400)
        workflow.set_status(ticket, wanted, actor=request.user,
                            note=(request.data.get("note") or "").strip())
        return None


@extend_schema(tags=TAG)
class TicketAssignView(_TicketAction):
    def allowed(self, user, ticket):
        return rbac.can_assign(user, ticket)

    def denial(self, ticket):
        return "Only the desk can take or hand over a ticket."

    def act(self, request, ticket):
        username = (request.data.get("username") or "").strip()
        if not username:
            target = request.user  # "take it"
        elif not rbac.can_assign_to_others(request.user):
            return Response(
                {"username": "Only a desk manager can assign a ticket to "
                             "somebody else. You can take it yourself."},
                status=403)
        else:
            target = get_user_model().objects.filter(
                username__iexact=username, is_active=True).first()
            if target is None:
                return Response({"username": "No active user with that username."},
                                status=400)
            if not rbac.is_handler(target):
                return Response(
                    {"username": f"{username} does not work the service desk, so "
                                 f"they would never see it."},
                    status=400)
        workflow.assign(ticket, target, actor=request.user,
                        note=(request.data.get("note") or "").strip())
        return None


@extend_schema(tags=TAG)
class TicketResolveView(_TicketAction):
    def allowed(self, user, ticket):
        return rbac.can_resolve(user, ticket)

    def denial(self, ticket):
        return "Only the desk resolves a ticket. To withdraw your own, cancel it."

    def act(self, request, ticket):
        note = (request.data.get("note") or "").strip()
        if not note:
            return Response(
                {"note": "Say what was done. The requester is about to be asked "
                         "to confirm this, and 'Resolved' on its own is not "
                         "something anybody can agree or disagree with."},
                status=400)
        workflow.resolve(ticket, actor=request.user, note=note)
        return None


@extend_schema(tags=TAG)
class TicketConfirmView(_TicketAction):
    def allowed(self, user, ticket):
        return rbac.can_confirm(user, ticket)

    def denial(self, ticket):
        return ("Only the person who raised this can confirm it was answered. "
                "That is deliberate.")

    def act(self, request, ticket):
        if ticket.status != Ticket.STATUS_RESOLVED:
            return Response({"detail": "This ticket is not awaiting confirmation."},
                            status=400)
        workflow.confirm(ticket, actor=request.user,
                         satisfaction=request.data.get("satisfaction"),
                         note=(request.data.get("note") or "").strip())
        return None


@extend_schema(tags=TAG)
class TicketReopenView(_TicketAction):
    def act(self, request, ticket):
        if not ticket.can_reopen():
            return Response(
                {"detail": f"This closed more than "
                           f"{DeskSettings.get().reopen_window_days} days ago. "
                           f"Raise a new ticket and reference {ticket.reference}."},
                status=400)
        workflow.reopen(ticket, actor=request.user,
                        note=(request.data.get("note") or "").strip())
        return None


@extend_schema(tags=TAG)
class TicketCancelView(_TicketAction):
    def allowed(self, user, ticket):
        return rbac.can_cancel(user, ticket)

    def denial(self, ticket):
        return "Only the person who raised this, or a desk manager, can cancel it."

    def act(self, request, ticket):
        workflow.cancel(ticket, actor=request.user,
                        note=(request.data.get("note") or "").strip())
        return None


# ── Reference data ───────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class CategoryListCreateView(generics.ListCreateAPIView):
    serializer_class = TicketCategorySerializer
    pagination_class = None

    def get_permissions(self):
        # Anyone raising a ticket needs the list; only a manager may change it.
        return [IsManager()] if self.request.method == "POST" else [IsAuthenticated()]

    def get_queryset(self):
        qs = TicketCategory.objects.annotate(ticket_count=Count("tickets"))
        if not rbac.is_manager(self.request.user):
            qs = qs.filter(is_active=True)
        return qs


@extend_schema(tags=TAG)
class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsManager]
    serializer_class = TicketCategorySerializer
    queryset = TicketCategory.objects.all()

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if category.tickets.exists():
            return Response(
                {"detail": "Tickets were raised under this category. Deactivate it "
                           "instead — deleting it would take their promise and "
                           "their reporting line with it."},
                status=400)
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=TAG)
class HolidayListCreateView(generics.ListCreateAPIView):
    serializer_class = HolidaySerializer
    pagination_class = None
    queryset = Holiday.objects.all()

    def get_permissions(self):
        return [IsManager()] if self.request.method == "POST" else [IsAuthenticated()]


@extend_schema(tags=TAG)
class HolidayDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsManager]
    serializer_class = HolidaySerializer
    queryset = Holiday.objects.all()


@extend_schema(tags=TAG)
class DeskSettingsView(APIView):
    def get_permissions(self):
        return [IsManager()] if self.request.method in ("PUT", "PATCH") else [IsAuthenticated()]

    def get(self, request):
        return Response(DeskSettingsSerializer(DeskSettings.get()).data)

    def patch(self, request):
        form = DeskSettingsSerializer(DeskSettings.get(), data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        form.save()
        return Response(form.data)


@extend_schema(tags=TAG)
class HandlerListView(APIView):
    """Who can be assigned a ticket — for the manager's assign dropdown."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not rbac.is_handler(request.user):
            return Response({"handlers": []})
        people = (get_user_model().objects.filter(is_active=True)
                  .filter(Q(groups__name__in=rbac.HANDLER_GROUPS) | Q(is_superuser=True))
                  .distinct().order_by("first_name", "username"))
        open_counts = dict(
            Ticket.objects.filter(status__in=reports.OPEN_STATUSES,
                                  assigned_to__isnull=False)
            .values_list("assigned_to_id").annotate(n=Count("id"))
        )
        return Response({"handlers": [
            {
                "id": p.id,
                "username": p.username,
                "name": p.get_full_name() or p.username,
                "email": p.email or "",
                "open_tickets": open_counts.get(p.id, 0),
            }
            for p in people
        ]})


# ── Reporting ────────────────────────────────────────────────────────────────

def _days(request, default=30):
    try:
        return max(1, min(365, int(request.query_params.get("days", default))))
    except (TypeError, ValueError):
        return default


@extend_schema(tags=TAG)
class MyDeskView(APIView):
    """The counts behind the sidebar badges, for any signed-in user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        mine = Ticket.objects.filter(raised_by=user)
        out = {
            "is_handler": rbac.is_handler(user),
            "is_manager": rbac.is_manager(user),
            "raised_open": mine.filter(status__in=reports.OPEN_STATUSES).count(),
            "awaiting_my_confirmation": mine.filter(
                status=Ticket.STATUS_RESOLVED).count(),
        }
        if rbac.is_handler(user):
            queue = Ticket.objects.filter(status__in=reports.OPEN_STATUSES)
            out.update({
                "assigned_to_me": queue.filter(assigned_to=user).count(),
                "unassigned": queue.filter(assigned_to__isnull=True).count(),
                "overdue": queue.filter(resolution_due_at__lt=timezone.now()).count(),
                "queue_open": queue.count(),
            })
        return Response(out)


@extend_schema(tags=TAG)
class ReportsView(APIView):
    """Everything the dashboard draws. Managers and handlers only — it is a
    view of other people's queries."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not rbac.is_handler(request.user):
            return Response({"detail": "The service desk reports are for the desk."},
                            status=403)
        days = _days(request)
        return Response({
            "overview": reports.overview(days=days),
            "by_category": reports.by_category(days=days),
            "by_handler": reports.by_handler(days=days),
            "trend": reports.trend(days=days),
            "ageing": reports.ageing(),
        })
