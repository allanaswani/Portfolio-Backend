"""Design board endpoints.

Every write goes through ``workflow``, never through a serialiser's ``save()``
of a status field. That is what guarantees a timeline entry for each
transition — see ``workflow`` and ``models`` for why that matters here.

The one endpoint worth reading before the others is ``BoardView``: it is what
the office screen polls, so it answers in a fixed number of queries no matter
how many briefs are open, and it never paginates. A wall display that stops at
page one is a wall display that lies about the pipeline.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import (
    Avg, Case, Count, F, IntegerField, Q, Sum, Value, When,
)
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import rbac, workflow
from .models import BriefEvent, DesignBrief
from .serializers import (
    ApproveSerializer, AssignSerializer, BriefEventSerializer,
    DesignBriefCreateSerializer, DesignBriefDetailSerializer,
    DesignBriefListSerializer, DesignBriefUpdateSerializer, NoteSerializer,
    PersonSerializer, ReasonSerializer,
)

User = get_user_model()
TAG = ["Design Briefs"]


class BriefPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 500


class IsMarketingAdmin(IsAuthenticated):
    message = "Only the marketing department admin can do this."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and rbac.is_admin(request.user)


def _base_queryset():
    return (DesignBrief.objects
            .select_related("raised_by", "assigned_designer", "assigned_by",
                            "approved_by"))


def _by_release(descending=False):
    """Soonest release date first, undated briefs last.

    ``release_date__isnull`` is not a valid ``order_by`` term — Django only
    accepts it in a filter — so nulls are placed with ``nulls_last`` on an
    expression. Undated last in both directions on purpose: a brief with no
    deadline is not the most urgent thing on the board, which is where a plain
    ascending sort puts it.
    """
    field = F("release_date")
    return field.desc(nulls_last=True) if descending else field.asc(nulls_last=True)


def _priority_rank():
    """Severity order for sorting.

    The stored values are words, so a plain ``-priority`` sorts them
    alphabetically — urgent, normal, low, high — which is not an order anybody
    asked for. Built fresh each call rather than held in a module constant,
    because a resolved expression is not safe to reuse across querysets.
    """
    return Case(
        When(priority=DesignBrief.PRIORITY_URGENT, then=Value(0)),
        When(priority=DesignBrief.PRIORITY_HIGH, then=Value(1)),
        When(priority=DesignBrief.PRIORITY_NORMAL, then=Value(2)),
        When(priority=DesignBrief.PRIORITY_LOW, then=Value(3)),
        default=Value(2),
        output_field=IntegerField(),
    )


def _visible(request):
    """Briefs this user may list.

    The design team sees the whole board. Everyone else sees what they raised,
    what is assigned to them, and their own department's.

    Note the department clause uses a plain case-insensitive match, while
    ``rbac.can_view`` compares through ``core.departments.compare_key``. The
    canonical comparison cannot be expressed in SQL, so the list is very
    slightly narrower than the detail check — which is the safe direction: a
    brief that is listed is always one the user may open.
    """
    qs = _base_queryset()
    user = request.user
    if rbac.can_see_board(user):
        return qs
    scope = Q(raised_by=user) | Q(assigned_designer=user)
    dept = rbac.department_of(user)
    if dept:
        scope |= Q(department__iexact=dept)
    return qs.filter(scope)


def _apply_filters(qs, params):
    """Shared between the list and the board so one filter cannot drift."""
    view = (params.get("view") or "open").strip().lower()
    if view == "open":
        qs = qs.open()
    elif view in {"closed", "archived"}:
        qs = qs.closed()
    # "all" falls through deliberately — the archive screen needs both.

    if s := (params.get("status") or "").strip():
        qs = qs.filter(status__in=[p for p in s.split(",") if p])
    if d := (params.get("department") or "").strip():
        qs = qs.filter(department__iexact=d)
    if t := (params.get("item_type") or "").strip():
        qs = qs.filter(item_type=t)
    if p := (params.get("priority") or "").strip():
        qs = qs.filter(priority=p)
    if designer := (params.get("designer") or "").strip():
        if designer == "unassigned":
            qs = qs.filter(assigned_designer__isnull=True)
        elif designer.isdigit():
            qs = qs.filter(assigned_designer_id=int(designer))
    if (params.get("overdue") or "").strip().lower() in {"1", "true", "yes"}:
        qs = qs.filter(release_date__lt=timezone.localdate()).exclude(
            status__in=DesignBrief.CLOSED_STATUSES)
    if (params.get("reworked") or "").strip().lower() in {"1", "true", "yes"}:
        qs = qs.filter(rework_count__gt=0)
    if q := (params.get("q") or "").strip():
        qs = qs.filter(
            Q(reference__icontains=q) | Q(design_item__icontains=q)
            | Q(brief__icontains=q) | Q(department__icontains=q)
            | Q(addressed_to__icontains=q) | Q(raised_by_name__icontains=q))
    return qs


def _get_or_none(request, reference):
    """Resolve a brief and check visibility in one place.

    A brief somebody may not see returns 404 rather than 403, for the reason
    ``apps.service_desk`` gives: a 403 confirms the reference exists, which is
    enough to probe for other departments' work.
    """
    brief = (_base_queryset()
             .prefetch_related("events__actor")
             .filter(reference=reference).first())
    if brief is None or not rbac.can_view(request.user, brief):
        return None
    return brief


@extend_schema(tags=TAG)
class BriefListCreateView(generics.ListCreateAPIView):
    """The queue, and raising a new brief.

    Anyone signed in may raise one. See ``rbac`` for why that is deliberately
    everybody.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = BriefPagination

    def get_serializer_class(self):
        if self.request.method == "POST":
            return DesignBriefCreateSerializer
        return DesignBriefListSerializer

    def get_queryset(self):
        qs = _apply_filters(_visible(self.request), self.request.query_params)
        if (self.request.query_params.get("mine") or "").lower() in {"1", "true", "yes"}:
            user = self.request.user
            qs = qs.filter(Q(assigned_designer=user) | Q(raised_by=user))
        ordering = (self.request.query_params.get("ordering") or "").strip()
        if ordering in {"release_date", "-release_date"}:
            return qs.order_by(_by_release(ordering.startswith("-")))
        if ordering in {"priority", "-priority"}:
            return (qs.annotate(_prio=_priority_rank())
                    .order_by("-_prio" if ordering.startswith("-") else "_prio"))
        if ordering in {"created_at", "-created_at", "status", "-status"}:
            return qs.order_by(ordering)
        return qs

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        brief = workflow.create(raised_by=request.user, **ser.validated_data)
        out = DesignBriefDetailSerializer(brief, context={"request": request})
        return Response(out.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAG)
class BriefDetailView(APIView):
    """One brief, by reference — which is what people paste at each other."""

    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(DesignBriefDetailSerializer(
            brief, context={"request": request}).data)

    def patch(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        if not rbac.can_edit_brief(request.user, brief):
            return Response(
                {"detail": "This brief can no longer be edited by you — a "
                           "designer has started on it. Ask the department "
                           "admin, or add a note."},
                status=403)
        ser = DesignBriefUpdateSerializer(brief, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        changed = [f for f, v in ser.validated_data.items()
                   if getattr(brief, f) != v]
        ser.save()
        workflow.record_edit(brief, actor=request.user, changed=changed)
        brief.refresh_from_db()
        return Response(DesignBriefDetailSerializer(
            brief, context={"request": request}).data)


class _TransitionView(APIView):
    """Shared plumbing for the state-change endpoints.

    Each subclass says who may press it and what it calls. The uniform
    ``TransitionError`` to 400 translation lives here so that an invalid step
    always comes back with the same shape and a readable message.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = None

    def check(self, user, brief):  # pragma: no cover - overridden
        raise NotImplementedError

    def act(self, brief, user, data):  # pragma: no cover - overridden
        raise NotImplementedError

    def post(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        ok, message = self.check(request.user, brief)
        if not ok:
            return Response({"detail": message}, status=403)
        data = {}
        if self.serializer_class is not None:
            ser = self.serializer_class(data=request.data)
            ser.is_valid(raise_exception=True)
            data = ser.validated_data
        try:
            self.act(brief, request.user, data)
        except workflow.TransitionError as exc:
            return Response({"detail": str(exc)}, status=400)
        brief.refresh_from_db()
        return Response(DesignBriefDetailSerializer(
            brief, context={"request": request}).data)


@extend_schema(tags=TAG)
class BriefAssignView(_TransitionView):
    """Allocate a designer. The department admin only — see ``rbac``."""

    serializer_class = AssignSerializer

    def check(self, user, brief):
        if not rbac.can_assign(user):
            return False, ("Only the marketing department admin assigns "
                           "designers.")
        return True, ""

    def act(self, brief, user, data):
        designer = User.objects.filter(pk=data["designer"]).first()
        workflow.assign(brief, designer, actor=user, note=data.get("note", ""))


@extend_schema(tags=TAG)
class BriefStartView(_TransitionView):
    def check(self, user, brief):
        if not rbac.can_work(user, brief):
            return False, "This brief is not assigned to you."
        return True, ""

    def act(self, brief, user, data):
        workflow.start(brief, actor=user)


@extend_schema(tags=TAG)
class BriefSubmitView(_TransitionView):
    serializer_class = NoteSerializer

    def check(self, user, brief):
        if not rbac.can_work(user, brief):
            return False, "This brief is not assigned to you."
        return True, ""

    def act(self, brief, user, data):
        workflow.submit(brief, actor=user, note=data.get("note", ""))


@extend_schema(tags=TAG)
class BriefReworkView(_TransitionView):
    """Send it back. Only whoever raised it, or the admin — and with a reason."""

    serializer_class = ReasonSerializer

    def check(self, user, brief):
        if not rbac.can_judge(user, brief):
            return False, ("Only the person who raised this brief, or the "
                           "department admin, can send it back.")
        return True, ""

    def act(self, brief, user, data):
        workflow.request_rework(brief, actor=user, reason=data["reason"])


@extend_schema(tags=TAG)
class BriefApproveView(_TransitionView):
    """Accept it. Closes and archives the brief."""

    serializer_class = ApproveSerializer

    def check(self, user, brief):
        if not rbac.can_judge(user, brief):
            return False, ("Only the person who raised this brief, or the "
                           "department admin, can approve it.")
        return True, ""

    def act(self, brief, user, data):
        workflow.approve(brief, actor=user,
                         satisfaction=data.get("satisfaction"),
                         note=data.get("note", ""))


@extend_schema(tags=TAG)
class BriefCancelView(_TransitionView):
    serializer_class = ReasonSerializer

    def check(self, user, brief):
        if not rbac.can_cancel(user, brief):
            return False, "Only the requester or the department admin can cancel."
        return True, ""

    def act(self, brief, user, data):
        workflow.cancel(brief, actor=user, reason=data["reason"])


@extend_schema(tags=TAG)
class BriefReopenView(_TransitionView):
    """Bring an archived brief back. Admin only, and with a reason."""

    serializer_class = ReasonSerializer

    def check(self, user, brief):
        if not rbac.is_admin(user):
            return False, "Only the department admin can reopen an archived brief."
        return True, ""

    def act(self, brief, user, data):
        workflow.reopen(brief, actor=user, reason=data["reason"])


@extend_schema(tags=TAG)
class BriefNoteView(_TransitionView):
    serializer_class = NoteSerializer

    def check(self, user, brief):
        return True, ""  # visibility was already checked by _get_or_none

    def act(self, brief, user, data):
        workflow.add_note(brief, actor=user, note=data["note"])


@extend_schema(tags=TAG)
class DesignerListView(APIView):
    """The designers a brief can be allocated to — the assign dropdown.

    Members of ``marketing_designer``. Superusers are not listed: being able to
    do everything is not the same as being someone whose name belongs on the
    board as a designer.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = Group.objects.filter(name=rbac.DESIGNER_GROUP).first()
        if group is None:
            return Response([])
        users = (group.user_set.filter(is_active=True)
                 .order_by("first_name", "last_name", "username"))
        return Response(PersonSerializer(users, many=True).data)


@extend_schema(tags=TAG)
class DepartmentListView(APIView):
    """Department names for the capture form's dropdown.

    Read from the HR roster, exactly as ``apps.referrals`` does, and never
    errors the form: an unavailable roster leaves the dropdown empty and the
    field is free text anyway.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        names = set()
        try:
            from apps.gceo_dashboard.models import EmployeeTable

            rows = (EmployeeTable.objects
                    .exclude(department__isnull=True).exclude(department="")
                    .values_list("department", flat=True).distinct())
            names = {d.strip() for d in rows if d and d.strip()}
        except Exception:
            names = set()
        # Whatever has actually been used on the board belongs in the list too,
        # including departments the roster spells differently or not at all.
        used = (DesignBrief.objects.exclude(department="")
                .values_list("department", flat=True).distinct())
        names |= {d.strip() for d in used if d and d.strip()}
        return Response(sorted(names))


@extend_schema(tags=TAG)
class MetaView(APIView):
    """The choice lists and the caller's own role, so the UI has one source.

    Hard-coding these in the frontend is how a status ends up spelled two ways.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "statuses": [{"value": v, "label": l} for v, l in DesignBrief.STATUS],
            "closed_statuses": sorted(DesignBrief.CLOSED_STATUSES),
            "priorities": [{"value": v, "label": l} for v, l in DesignBrief.PRIORITY],
            "item_types": [{"value": v, "label": l} for v, l in DesignBrief.ITEM_TYPES],
            "role": rbac.role_of(request.user),
            "can_assign": rbac.can_assign(request.user),
            "sees_whole_board": rbac.can_see_board(request.user),
            "my_department": rbac.department_of(request.user),
        })


@extend_schema(tags=TAG)
class BoardView(APIView):
    """What the office screen polls.

    Three things, in a fixed number of queries and never paginated:

    * ``columns`` — the open briefs grouped by status, in workflow order, which
      is what the wall display draws as a lane each.
    * ``pipelines`` — a lane per designer with their open work, so that walking
      in and looking up answers "what is on my plate today" without anybody
      opening the app. This is the thing the department actually asked for.
    * ``counts`` — the handful of totals along the top.

    ``limit`` caps rows per lane for the display only; the counts are always of
    everything, so a capped lane cannot make the pipeline look shorter than it
    is.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = min(int(request.query_params.get("limit") or 12), 100)
        qs = _apply_filters(_visible(request), request.query_params)
        today = timezone.localdate()

        open_qs = qs.open() if (request.query_params.get("view") or "open") == "open" else qs
        rows = list(open_qs.annotate(_prio=_priority_rank())
                    .order_by(_by_release(), "_prio", "-created_at"))
        ser = DesignBriefListSerializer(rows, many=True, context={"request": request})
        data = ser.data
        by_ref = {d["reference"]: d for d in data}

        # -- columns, in workflow order ---------------------------------------
        order = [DesignBrief.STATUS_NEW, DesignBrief.STATUS_ASSIGNED,
                 DesignBrief.STATUS_IN_PROGRESS, DesignBrief.STATUS_REWORK,
                 DesignBrief.STATUS_SUBMITTED]
        labels = dict(DesignBrief.STATUS)
        columns = []
        for st in order:
            members = [by_ref[r.reference] for r in rows if r.status == st]
            columns.append({
                "status": st,
                "label": labels.get(st, st),
                "total": len(members),
                "briefs": members[:limit],
            })

        # -- a lane per designer ----------------------------------------------
        pipelines = []
        seen = {}
        for r in rows:
            key = r.assigned_designer_id or 0
            seen.setdefault(key, []).append(r)
        for key, members in seen.items():
            first = members[0]
            pipelines.append({
                "designer_id": key or None,
                "designer": (first.assigned_designer.get_full_name()
                             or first.assigned_designer.username)
                            if first.assigned_designer else "Unassigned",
                "initials": DesignBriefListSerializer().get_designer_initials(first),
                "total": len(members),
                "overdue": sum(1 for m in members if m.is_overdue),
                "due_today": sum(1 for m in members if m.days_to_release == 0),
                "in_progress": sum(
                    1 for m in members if m.status == DesignBrief.STATUS_IN_PROGRESS),
                "briefs": [by_ref[m.reference] for m in members[:limit]],
            })
        # Unassigned last; the rest busiest first — the screen reads left to right.
        pipelines.sort(key=lambda p: (p["designer_id"] is None, -p["total"]))

        # -- the totals along the top -----------------------------------------
        counts = {
            "open": len(rows),
            "unassigned": sum(1 for r in rows if r.assigned_designer_id is None),
            "in_progress": sum(
                1 for r in rows if r.status == DesignBrief.STATUS_IN_PROGRESS),
            "awaiting_review": sum(
                1 for r in rows if r.status == DesignBrief.STATUS_SUBMITTED),
            "in_rework": sum(1 for r in rows if r.status == DesignBrief.STATUS_REWORK),
            "overdue": sum(1 for r in rows if r.is_overdue),
            "due_today": sum(1 for r in rows if r.days_to_release == 0),
            "due_this_week": sum(
                1 for r in rows
                if r.days_to_release is not None and 0 <= r.days_to_release <= 7),
            "no_release_date": sum(1 for r in rows if r.release_date is None),
        }

        return Response({
            "as_of": timezone.now(),
            "today": today,
            "counts": counts,
            "columns": columns,
            "pipelines": pipelines,
        })


@extend_schema(tags=TAG)
class MyPipelineView(APIView):
    """The signed-in person's own day — what they are making, and what they raised.

    Separate from the board because the two questions are different: the board
    is the department's, this is yours.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        mine = _base_queryset().open().filter(assigned_designer=user)
        raised = _base_queryset().open().filter(raised_by=user)
        ctx = {"request": request}
        awaiting_me = raised.filter(status=DesignBrief.STATUS_SUBMITTED)
        return Response({
            "as_of": timezone.now(),
            "assigned_to_me": DesignBriefListSerializer(
                mine.order_by(_by_release()), many=True, context=ctx).data,
            "raised_by_me": DesignBriefListSerializer(
                raised.order_by("-created_at"), many=True, context=ctx).data,
            # The nudge that stops briefs dying in review: work finished and
            # waiting on this person to look at it.
            "waiting_on_my_review": DesignBriefListSerializer(
                awaiting_me, many=True, context=ctx).data,
            "counts": {
                "assigned_to_me": mine.count(),
                "overdue_mine": mine.filter(
                    release_date__lt=timezone.localdate()).count(),
                "raised_by_me": raised.count(),
                "waiting_on_my_review": awaiting_me.count(),
            },
        })


@extend_schema(tags=TAG)
class SummaryView(APIView):
    """Department figures. Admin only.

    Deliberately includes the archive: the point of not deleting a closed brief
    is being able to say what the department produced last quarter, and how
    often it had to be made twice.
    """

    permission_classes = [IsMarketingAdmin]

    def get(self, request):
        qs = _apply_filters(DesignBrief.objects.all(), request.query_params)
        totals = qs.aggregate(
            briefs=Count("id"),
            reworked=Count("id", filter=Q(rework_count__gt=0)),
            rework_events=Sum("rework_count"),
            avg_satisfaction=Avg("satisfaction"),
            approved=Count("id", filter=Q(status=DesignBrief.STATUS_APPROVED)),
            cancelled=Count("id", filter=Q(status=DesignBrief.STATUS_CANCELLED)),
        )
        by_designer = list(
            qs.values("assigned_designer", "assigned_designer__first_name",
                      "assigned_designer__last_name",
                      "assigned_designer__username")
            .annotate(briefs=Count("id"),
                      approved=Count("id", filter=Q(status=DesignBrief.STATUS_APPROVED)),
                      reworked=Count("id", filter=Q(rework_count__gt=0)),
                      avg_satisfaction=Avg("satisfaction"))
            .order_by("-briefs"))
        for row in by_designer:
            name = " ".join(filter(None, [
                row.pop("assigned_designer__first_name", "") or "",
                row.pop("assigned_designer__last_name", "") or ""])).strip()
            row["designer"] = name or row.pop(
                "assigned_designer__username", None) or "Unassigned"
            row.pop("assigned_designer__username", None)
        by_department = list(
            qs.values("department")
            .annotate(briefs=Count("id"),
                      reworked=Count("id", filter=Q(rework_count__gt=0)))
            .order_by("-briefs"))
        by_type = list(
            qs.values("item_type").annotate(briefs=Count("id")).order_by("-briefs"))
        return Response({
            "as_of": timezone.now(),
            "totals": totals,
            "by_designer": by_designer,
            "by_department": by_department,
            "by_item_type": by_type,
        })


@extend_schema(tags=TAG)
class BriefTimelineView(generics.ListAPIView):
    """A brief's steps on their own, for anything that wants just the history."""

    permission_classes = [IsAuthenticated]
    serializer_class = BriefEventSerializer

    def get_queryset(self):
        brief = _get_or_none(self.request, self.kwargs["reference"])
        if brief is None:
            return BriefEvent.objects.none()
        return brief.events.select_related("actor")
