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
    Avg, Case, Count, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Sum,
    Value, When,
)
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import images, rbac, workflow
from .models import (
    BriefComment, BriefDeliverable, BriefEvent, BriefProof, DesignBrief,
)
from .serializers import (
    ApproveSerializer, AssignSerializer, BriefCommentSerializer,
    BriefDeliverableSerializer, BriefEventSerializer, BriefProofSerializer,
    DeliverablesSerializer, MarkupSerializer, ProofUploadSerializer,
    ResolveSerializer,
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
    """Everything a board row needs, in a fixed number of queries.

    The latest proof comes through a subquery rather than a prefetch: a
    prefetch cannot be limited per parent, so it would pull every version of
    every brief's artwork to display one thumbnail each.
    """
    newest = (BriefProof.objects
              .filter(brief=OuterRef("pk")).order_by("-version"))
    return (DesignBrief.objects
            .select_related("raised_by", "assigned_designer", "assigned_by",
                            "approved_by")
            .annotate(
                latest_proof_id=Subquery(newest.values("id")[:1]),
                latest_proof_version=Subquery(newest.values("version")[:1]),
                deliverables_total_n=Count("deliverables", distinct=True),
                deliverables_done_n=Count(
                    "deliverables", filter=Q(deliverables__done=True),
                    distinct=True),
            ))


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
             .prefetch_related(
                 "events__actor", "deliverables__done_by",
                 Prefetch("proofs", queryset=BriefProof.objects
                          .select_related("uploaded_by").order_by("-version")),
                 Prefetch("comments", queryset=BriefComment.objects
                          .select_related("author", "proof")
                          .order_by("created_at", "id")),
             )
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
        # Explicit, not inherited from Meta: an unordered queryset makes page
        # boundaries arbitrary, and DRF warns about exactly this.
        return qs.order_by("-created_at", "-id")

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
            return False, ("Only the person who raised this brief, somebody "
                           "in the department it was raised for, or the "
                           "marketing admin can send it back.")
        return True, ""

    def act(self, brief, user, data):
        workflow.request_rework(brief, actor=user, reason=data["reason"])


@extend_schema(tags=TAG)
class BriefApproveView(_TransitionView):
    """Accept it. Closes and archives the brief."""

    serializer_class = ApproveSerializer

    def check(self, user, brief):
        if not rbac.can_judge(user, brief):
            return False, ("Only the person who raised this brief, somebody "
                           "in the department it was raised for, or the "
                           "marketing admin can approve it.")
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
            return False, ("Only the requester, their department, or the "
                           "marketing admin can cancel a brief.")
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
        # The wall display paginates across slides rather than clipping, so it
        # asks for everything; 500 is a sanity ceiling, not a design choice.
        try:
            limit = min(max(int(request.query_params.get("limit") or 12), 1), 500)
        except (TypeError, ValueError):
            limit = 12
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

        # -- Work in progress against a limit ---------------------------------
        # The wall display has to stay readable as the team grows, and a count
        # on its own does not say whether it is too much. Kanban's working rule
        # is a WIP limit of team size x 1.5, rounded up, so that is what is
        # reported - derived, not configured, so there is no setting to go
        # stale. It describes the IN PROGRESS column only: work that is waiting
        # on a requester is not the designers' load.
        #
        # Counted from the group rather than from who happens to have work, so
        # a designer with an empty plate still counts toward the team's
        # capacity instead of tightening the limit by being idle.
        try:
            designers = (Group.objects
                         .filter(name=rbac.DESIGNER_GROUP)
                         .values_list("user__id", flat=True)
                         .exclude(user__isnull=True)
                         .distinct().count())
        except Exception:  # noqa: BLE001 - never break the board over a count
            designers = 0
        designers = designers or len({r.assigned_designer_id for r in rows
                                      if r.assigned_designer_id})
        wip = {
            "designers": designers,
            "in_progress": counts["in_progress"],
            # ceil(n * 1.5) without importing math for one line.
            "limit": (designers * 3 + 1) // 2 if designers else 0,
        }
        wip["over"] = bool(wip["limit"]) and wip["in_progress"] > wip["limit"]

        return Response({
            "as_of": timezone.now(),
            "today": today,
            "counts": counts,
            "wip": wip,
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


# ── Artwork ──────────────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class BriefProofView(APIView):
    """The versions of the artwork on one brief, and adding another.

    Uploading is the designer's action, so it is gated like ``start`` and
    ``submit``. ``submit=true`` uploads and hands over in one step, because
    uploading and then forgetting to submit is how a finished design sits
    unseen for three days.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        proofs = brief.proofs.select_related("uploaded_by").order_by("-version")
        return Response(BriefProofSerializer(proofs, many=True).data)

    def post(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        if not rbac.can_work(request.user, brief):
            return Response(
                {"detail": "Only the designer this brief is assigned to, or "
                           "the marketing admin, can upload artwork."},
                status=403)

        ser = ProofUploadSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        prepared = {
            "preview": b"", "thumbnail": b"", "width": 0, "height": 0,
            "original_name": "", "original_bytes": 0,
        }
        upload = data.get("file")
        if upload is not None:
            try:
                prepared = images.prepare(upload.read(), getattr(upload, "name", ""))
            except images.ProofImageError as exc:
                # The message is written for whoever is uploading.
                return Response({"file": [str(exc)]}, status=400)

        try:
            proof = workflow.add_proof(
                brief, prepared=prepared, uploaded_by=request.user,
                note=data.get("note", ""), source_url=data.get("source_url", ""),
                submit_for_review=bool(data.get("submit")))
        except workflow.TransitionError as exc:
            return Response({"detail": str(exc)}, status=400)

        brief = _get_or_none(request, reference)
        return Response(
            DesignBriefDetailSerializer(brief, context={"request": request}).data,
            status=status.HTTP_201_CREATED)


class _ProofImageView(APIView):
    """Serve one stored image.

    Its own endpoint rather than a data: URI in the JSON, so the browser caches
    it and a fifty-row board stays a few kilobytes instead of several megabytes.
    Visibility is checked against the brief, so a proof cannot be read by
    guessing ids.
    """

    permission_classes = [IsAuthenticated]
    field = "thumbnail"

    def get(self, request, pk):
        proof = BriefProof.objects.select_related("brief").filter(pk=pk).first()
        if proof is None or not rbac.can_view(request.user, proof.brief):
            return Response({"detail": "Not found."}, status=404)
        blob = bytes(getattr(proof, self.field) or b"")
        if not blob:
            return Response({"detail": "No image on this version."}, status=404)
        ctype = getattr(proof, self.field + "_content_type", "image/jpeg")
        res = HttpResponse(blob, content_type=ctype)
        # A version is immutable once written, so it can be cached hard.
        # Private: it is somebody's unreleased artwork, not a public asset.
        res["Cache-Control"] = "private, max-age=86400"
        res["ETag"] = '"{}-{}-{}"'.format(proof.pk, self.field, len(blob))
        return res


@extend_schema(tags=TAG)
class ProofThumbView(_ProofImageView):
    field = "thumbnail"


@extend_schema(tags=TAG)
class ProofPreviewView(_ProofImageView):
    field = "preview"


# ── Conversation ─────────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class BriefCommentView(APIView):
    """Feedback on the brief, or on one version of the artwork.

    Anybody who can see the brief can comment. Narrowing this would push the
    conversation back into WhatsApp, which is the thing the board is replacing.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        rows = (brief.comments.select_related("author", "proof")
                .order_by("created_at", "id"))
        return Response(BriefCommentSerializer(rows, many=True).data)

    def post(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)

        ser = MarkupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        proof = None
        if data.get("proof"):
            proof = brief.proofs.filter(pk=data["proof"]).first()
            if proof is None:
                return Response({"proof": ["No such version on this brief."]},
                                status=400)
        try:
            comment = workflow.add_comment(
                brief, author=request.user, body=data["body"], proof=proof,
                x=data.get("x"), y=data.get("y"),
                w=data.get("w"), h=data.get("h"))
        except workflow.TransitionError as exc:
            return Response({"body": [str(exc)]}, status=400)
        return Response(BriefCommentSerializer(comment).data,
                        status=status.HTTP_201_CREATED)


@extend_schema(tags=TAG)
class CommentResolveView(APIView):
    """Tick a piece of feedback off, or reopen it.

    Anybody who can see the brief may resolve a comment. Restricting it to the
    author would leave markup from somebody on leave open forever, and the list
    of open marks is the thing a designer works down.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, reference, pk):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        comment = brief.comments.filter(pk=pk).first()
        if comment is None:
            return Response({"detail": "Not found."}, status=404)
        ser = ResolveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        workflow.resolve_comment(comment, actor=request.user,
                                 resolved=ser.validated_data["resolved"])
        return Response(BriefCommentSerializer(comment).data)


# ── Deliverables ─────────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class BriefDeliverableView(APIView):
    """The checklist of what the brief has to produce.

    PUT replaces the list and carries ticks across by label, so adding a line
    does not silently un-tick finished work.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(BriefDeliverableSerializer(
            brief.deliverables.select_related("done_by"), many=True).data)

    def put(self, request, reference):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        # Who the work is for decides what it has to include; the designer
        # ticks items off but does not rewrite the list.
        if not (rbac.can_judge(request.user, brief) or rbac.is_admin(request.user)):
            return Response(
                {"detail": "The requester, their department or the marketing "
                           "admin sets the deliverables."}, status=403)
        ser = DeliverablesSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            workflow.set_deliverables(brief, ser.validated_data["labels"],
                                      actor=request.user)
        except workflow.TransitionError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(BriefDeliverableSerializer(
            brief.deliverables.select_related("done_by"), many=True).data)


@extend_schema(tags=TAG)
class DeliverableTickView(APIView):
    """Tick or un-tick one item. The designer's day-to-day action."""

    permission_classes = [IsAuthenticated]

    def post(self, request, reference, pk):
        brief = _get_or_none(request, reference)
        if brief is None:
            return Response({"detail": "Not found."}, status=404)
        item = brief.deliverables.filter(pk=pk).first()
        if item is None:
            return Response({"detail": "Not found."}, status=404)
        if not (rbac.can_work(request.user, brief)
                or rbac.can_judge(request.user, brief)):
            return Response({"detail": "Not yours to tick."}, status=403)
        done = request.data.get("done", True)
        workflow.tick_deliverable(
            item, actor=request.user,
            done=str(done).lower() not in {"false", "0", "no"})
        return Response(BriefDeliverableSerializer(item).data)


# ── Calendar ─────────────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class CalendarView(APIView):
    """Release dates for one month, as a campaign calendar.

    Marketing works to a calendar, not a queue: the thing worth seeing is the
    week where six items all land. Closed briefs are included so the month
    reads as what happened, not only as what is left.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        raw = (request.query_params.get("month") or "").strip()
        try:
            parts = raw.split("-")
            year, month = int(parts[0]), int(parts[1])
            if not (1 <= month <= 12 and 2000 <= year <= 2100):
                raise ValueError("out of range")
        except Exception:
            year, month = today.year, today.month

        start = today.replace(year=year, month=month, day=1)
        end = (start.replace(year=year + 1, month=1, day=1) if month == 12
               else start.replace(month=month + 1, day=1))

        qs = (_visible(request)
              .filter(release_date__gte=start, release_date__lt=end)
              .order_by(_by_release()))
        rows = DesignBriefListSerializer(
            qs, many=True, context={"request": request}).data

        days = {}
        for row in rows:
            days.setdefault(row["release_date"], []).append(row)

        return Response({
            "month": "{:04d}-{:02d}".format(year, month),
            "first_day": start,
            "today": today,
            "total": len(rows),
            # A plain map of date -> briefs. The frontend lays out the grid;
            # which weekday the first falls on is a presentation question.
            "days": [{"date": d, "briefs": b} for d, b in sorted(days.items())],
            # Undated briefs are on no calendar, and a campaign calendar that
            # silently omits them hides real work.
            "undated": DesignBriefListSerializer(
                _visible(request).open().filter(release_date__isnull=True),
                many=True, context={"request": request}).data,
        })
