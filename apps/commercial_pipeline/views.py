"""Commercial Pipeline API — the RM's own lines, and the TL's whole team.

Scoping follows what the platform already does rather than inventing a rule:

* an **RM** sees and edits rows carrying their ``sales_code``, the same key
  ``core.permissions.RBACQueryFilter`` uses for officer-level access;
* a **Team Leader** sees every row in their segment, the same basis
  ``apps.tl_portfolio`` uses for its team views;
* segment is matched through ``core.segments``, never with ``=``. The same
  segment is spelled several ways in this platform and an equality test
  silently returns nothing for half the Team Leaders.

A TL may edit team rows. That is deliberate: the file being replaced is one
the TL already edits on everybody's behalf, and taking that away would send
them back to the spreadsheet.

**``portfolio_mgt`` is not a team group, and that is the whole point.** It was
in :data:`TEAM_GROUPS` when this shipped, read as "portfolio management". It is
not: ``lib/roleNavConfig.tsx`` maps ``portfolio_mgt`` to /rm-portfolio, and
``apps.staff_management.targets_views.RM_GROUP`` says the same thing — it is
the group every Commercial RM is in, and the group that carries the "My
Pipeline" link. So every RM who could open the page was being handed the whole
segment: their own book plus everybody else's. ``is_staff`` went the same way,
for the same reason — ``migrate_legacy_auth`` copies that flag verbatim out of
the old system, so it is not a reliable statement about anybody's seniority.

Two things now have to be true before a caller is widened to the team: they are
in a group that is genuinely a team role, and they did not ask for their own
book. The second is what ``?scope=mine`` is for: the RM page sends it, so "My
Pipeline" means the same thing to a Team Leader as it does to an RM, and a
group added to TEAM_GROUPS later cannot silently turn that page into a
team view.
"""

import csv

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from core.segments import canonical_segment, segment_synonyms
from .importer import parse_workbook
from .models import PipelineEntry
from .serializers import PipelineEntrySerializer

TAG = ["Commercial Pipeline"]

#: Groups whose members see the whole segment rather than only their own book.
#:
#: ``portfolio_mgt`` is deliberately NOT here - see the module docstring. It is
#: the RM group, and listing it gave every RM everybody else's deals.
TEAM_GROUPS = {
    "tl_portfolio", "ceo", "exco", "Management", "business_performance",
}


def _profile(user):
    from apps.portfolio.models import Profile
    return Profile.objects.filter(user=user).first()


def sees_team(user):
    """True when this user should see the whole segment, not just their rows.

    ``is_staff`` is not enough on its own: ``migrate_legacy_auth`` carries that
    flag over from the old system unchanged, so it says where an account came
    from rather than what it is entitled to. A superuser, or a member of a
    group that is actually a team role.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(set(user.groups.values_list("name", flat=True)) & TEAM_GROUPS)


def wants_own_book(request):
    """True when the caller asked for their own lines regardless of their role.

    The RM page sends ``?scope=mine``. That keeps "My Pipeline" meaning my
    pipeline for a Team Leader too, and means a group added to TEAM_GROUPS in
    future cannot quietly turn that page into a team view.
    """
    return str(request.query_params.get("scope", "")).strip().lower() == "mine"


def visible_to(user, mine_only=False):
    """The rows this user may see. One definition, used by every endpoint."""
    qs = PipelineEntry.objects.select_related("updated_by")

    # No user, nothing. Every API path here is behind IsAuthenticated, but the
    # fall-through below is ``filter(created_by=user)``, and with user=None
    # that reads "every row nobody typed" - which is every imported row. One
    # line, so a caller outside the API cannot find that out the hard way.
    if not user or not getattr(user, "is_authenticated", False):
        return qs.none()

    profile = _profile(user)

    if sees_team(user) and not mine_only:
        segment = (profile.segment if profile else "") or "COMMERCIAL"
        synonyms = segment_synonyms(segment)
        # Rows whose segment is blank are visible to the team too: an imported
        # row with no segment belongs to somebody, and hiding it from everyone
        # is how a pipeline line goes missing.
        return qs.filter(Q(segment__in=synonyms) | Q(segment=""))

    code = (profile.sales_code if profile else "") or ""
    if not code:
        # No sales code means no book to scope to. Their own entries by
        # authorship rather than nothing at all, so a new RM can still work.
        return qs.filter(created_by=user)
    return qs.filter(Q(sales_code__iexact=code) | Q(created_by=user))


def _apply_filters(qs, params):
    kind = params.get("kind")
    if kind:
        qs = qs.filter(kind=kind)

    active = params.get("is_active")
    if active in ("true", "false"):
        qs = qs.filter(is_active=(active == "true"))
    elif active is None:
        qs = qs.filter(is_active=True)      # dropped deals are out by default

    for field in ("broad_stage", "stage", "deposit_product", "insurance_type",
                  "sales_code"):
        value = params.get(field)
        if value:
            qs = qs.filter(**{field: value})

    search = (params.get("search") or "").strip()
    if search:
        qs = qs.filter(
            Q(customer_name__icontains=search)
            | Q(rm_name__icontains=search)
            | Q(product__icontains=search)
            | Q(comments__icontains=search)
            | Q(account_no__icontains=search))
    return qs


@extend_schema(tags=TAG)
class PipelineListCreateView(generics.ListCreateAPIView):
    serializer_class = PipelineEntrySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        return _apply_filters(
            visible_to(self.request.user, mine_only=wants_own_book(self.request)),
            self.request.query_params)

    def perform_create(self, serializer):
        profile = _profile(self.request.user)
        user = self.request.user
        data = serializer.validated_data

        # A team lead may raise a line on somebody's behalf, so the owner they
        # named is respected. An RM may not: without this, an RM could post a
        # line into a colleague's book - and then not be able to see it, which
        # is the confusing half of the bug rather than the dangerous half.
        if sees_team(user):
            code = data.get("sales_code") or (profile.sales_code if profile else "") or ""
            name = data.get("rm_name") or (user.get_full_name() or user.username).strip()
        else:
            code = (profile.sales_code if profile else "") or ""
            name = (user.get_full_name() or user.username).strip()

        serializer.save(
            created_by=user,
            updated_by=user,
            sales_code=code,
            rm_name=name,
            branch=data.get("branch") or (profile.branch if profile else "") or "Commercial",
            segment=canonical_segment(profile.segment if profile else "") or "COMMERCIAL",
        )


@extend_schema(tags=TAG)
class PipelineDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PipelineEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return visible_to(self.request.user)

    def perform_update(self, serializer):
        # Only a team lead may move a line to another RM. For everybody else
        # the owner is pinned to what it already is, so an edit cannot hand a
        # deal to somebody else - by accident or otherwise.
        if sees_team(self.request.user):
            serializer.save(updated_by=self.request.user)
        else:
            serializer.save(updated_by=self.request.user,
                            sales_code=serializer.instance.sales_code,
                            rm_name=serializer.instance.rm_name)

    def perform_destroy(self, instance):
        # Cleared, not deleted. A deal that fell through is part of the record,
        # and a pipeline whose history can be erased cannot be reported on.
        instance.is_active = False
        instance.updated_by = self.request.user
        instance.save(update_fields=["is_active", "updated_by", "updated_at"])


@extend_schema(tags=TAG)
class PipelineSummaryView(APIView):
    """Totals per pipeline, and per RM — what a Team Leader opens this for."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        mine = wants_own_book(request)
        rows = _apply_filters(visible_to(request.user, mine_only=mine),
                              request.query_params)
        labels = dict(PipelineEntry.KIND)

        by_kind = (rows.values("kind")
                        .annotate(count=Count("id"),
                                  total_amount=Sum("amount"),
                                  total_to_disburse=Sum("amount_to_disburse"),
                                  total_revenue=Sum("revenue"))
                        .order_by("kind"))

        by_rm = (rows.values("sales_code", "rm_name")
                     .annotate(count=Count("id"), total_amount=Sum("amount"))
                     .order_by("-total_amount")[:50])

        by_stage = (rows.exclude(broad_stage="")
                        .values("broad_stage")
                        .annotate(count=Count("id"), total_amount=Sum("amount"))
                        .order_by("broad_stage"))
        broad_labels = dict(PipelineEntry.BROAD_STAGE)

        return Response({
            "scope": "team" if (sees_team(request.user) and not mine) else "mine",
            "by_kind": [
                {**r, "kind_display": labels.get(r["kind"], r["kind"])}
                for r in by_kind
            ],
            "by_rm": list(by_rm),
            "by_stage": [
                {**r, "broad_stage_display": broad_labels.get(r["broad_stage"],
                                                              r["broad_stage"])}
                for r in by_stage
            ],
        })


@extend_schema(tags=TAG)
class PipelineExportView(APIView):
    """The report the Team Leader used to build by hand from the workbook."""

    permission_classes = [IsAuthenticated]

    COLUMNS = [
        "kind", "branch", "rm_name", "sales_code", "customer_name",
        "amount", "amount_to_disburse", "revenue",
        "product", "deposit_product", "insurance_type", "account_no",
        "broad_stage", "stage", "expected_date", "comments",
        "is_active", "updated_by", "updated_at",
    ]

    def get(self, request):
        rows = _apply_filters(
            visible_to(request.user, mine_only=wants_own_book(request)),
            request.query_params)

        response = HttpResponse(content_type="text/csv")
        stamp = timezone.now().strftime("%Y-%m-%d")
        response["Content-Disposition"] = (
            f'attachment; filename="commercial-pipeline-{stamp}.csv"')

        writer = csv.writer(response)
        writer.writerow(self.COLUMNS)
        for e in rows.iterator():
            writer.writerow([
                e.get_kind_display(),
                e.branch,
                e.rm_name,
                e.sales_code,
                e.customer_name,
                e.amount if e.amount is not None else "",
                e.amount_to_disburse if e.amount_to_disburse is not None else "",
                e.revenue if e.revenue is not None else "",
                e.product,
                e.get_deposit_product_display() if e.deposit_product else "",
                e.get_insurance_type_display() if e.insurance_type else "",
                e.account_no,
                e.get_broad_stage_display() if e.broad_stage else "",
                e.get_stage_display() if e.stage else "",
                e.expected_date.strftime("%Y-%m-%d") if e.expected_date else "",
                e.comments,
                "yes" if e.is_active else "no",
                (e.updated_by.get_full_name() or e.updated_by.username).strip()
                if e.updated_by else "",
                timezone.localtime(e.updated_at).strftime("%Y-%m-%d %H:%M"),
            ])
        return response


@extend_schema(tags=TAG)
class PipelineOptionsView(APIView):
    """Choices and suggestions, so the form never hard-codes them.

    Products come from what has actually been entered rather than a fixed
    list: the workbook spells contract financing five different ways, and the
    fix for that is a suggestion list, not a constraint that makes a new
    product un-enterable.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        P = PipelineEntry
        rows = visible_to(request.user, mine_only=wants_own_book(request))
        products = (rows.exclude(product="")
                        .values_list("product", flat=True)
                        .distinct().order_by("product")[:200])

        # Retired choices are left out of what the form offers, but kept in the
        # label maps: a row that already carries one still has to render as
        # words rather than as a slug. The two lists are separate for exactly
        # that reason, and the UI must not treat either as the other.
        return Response({
            "kinds": [{"value": v, "label": l} for v, l in P.KIND],
            "broad_stages": [{"value": v, "label": l} for v, l in P.BROAD_STAGE
                             if v not in P.RETIRED_BROAD_STAGES],
            "stages": [{"value": v, "label": l} for v, l in P.STAGE
                       if v not in P.RETIRED_STAGES],
            "stage_labels": dict(P.STAGE),
            "broad_stage_labels": dict(P.BROAD_STAGE),
            "stages_under_broad": {
                broad: sorted(s for s in stages if s not in P.RETIRED_STAGES)
                for broad, stages in P.STAGES_UNDER_BROAD.items()
                if broad not in P.RETIRED_BROAD_STAGES
            },
            "deposit_products": [{"value": v, "label": l}
                                 for v, l in P.DEPOSIT_PRODUCT],
            "insurance_types": [{"value": v, "label": l}
                                for v, l in P.INSURANCE_TYPE],
            "fields_by_kind": P.FIELDS_BY_KIND,
            "min_comment_words": P.MIN_COMMENT_WORDS,
            "product_suggestions": sorted(set(products)),
            "can_see_team": sees_team(request.user) and not wants_own_book(request),
        })


@extend_schema(tags=TAG)
class PipelineUploadView(APIView):
    """Load the workbook by uploading it, instead of copying it to a server.

    The management command needs a shell on the application host, which the
    people who actually keep this spreadsheet do not have - so without this the
    import can only ever be done by somebody else, on request, which is how the
    spreadsheet stayed the system of record in the first place.

    Two steps on purpose. The first upload reads the file and reports what it
    found, writing nothing; only a second call with ``apply=true`` saves. A
    140-row import that silently doubled the pipeline would be worse than no
    import at all.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    #: Comfortably above the real file, mean enough to refuse a mistake.
    MAX_BYTES = 10 * 1024 * 1024

    def post(self, request):
        # Loading everybody's rows is a team action, so it is the team's to do.
        if not sees_team(request.user):
            return Response(
                {"detail": "Only a team leader can load the workbook."}, status=403)

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the workbook first."}, status=400)
        if not upload.name.lower().endswith((".xlsx", ".xlsm")):
            return Response(
                {"file": f"{upload.name} is not an Excel workbook. Save it as "
                         f".xlsx and try again."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; the "
                         f"limit is {self.MAX_BYTES // 1024 // 1024} MB."}, status=400)

        try:
            entries, warnings, skipped = parse_workbook(upload)
        except Exception as exc:  # noqa: BLE001 - the message is for the reader
            return Response(
                {"file": f"That workbook could not be read: {exc}"}, status=400)

        by_kind = {}
        for e in entries:
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        labels = dict(PipelineEntry.KIND)
        found = [{"kind": k, "kind_display": labels.get(k, k), "count": n}
                 for k, n in sorted(by_kind.items())]

        applied = str(request.data.get("apply", "")).lower() in ("1", "true", "yes")
        if not applied:
            return Response({
                "applied": False,
                "found": found,
                "total": len(entries),
                "skipped": skipped,
                "warnings": warnings,
            })

        profile = _profile(request.user)
        segment = canonical_segment(profile.segment if profile else "") or "COMMERCIAL"
        replace = str(request.data.get("replace", "")).lower() in ("1", "true", "yes")

        with transaction.atomic():
            removed = 0
            if replace:
                # Only ever rows that came from a workbook: created_by is null
                # on those and set on anything an RM typed. Uploading a fresh
                # copy must never delete somebody's own work.
                removed = PipelineEntry.objects.filter(
                    created_by__isnull=True, segment=segment).delete()[0]
            for e in entries:
                e.segment = segment
            PipelineEntry.objects.bulk_create(entries, batch_size=200)

        return Response({
            "applied": True,
            "found": found,
            "total": len(entries),
            "skipped": skipped,
            "removed": removed,
            "warnings": warnings,
        }, status=201)
