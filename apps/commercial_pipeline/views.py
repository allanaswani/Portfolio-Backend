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
"""

import csv

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from core.segments import canonical_segment, segment_synonyms
from .models import PipelineEntry
from .serializers import PipelineEntrySerializer

TAG = ["Commercial Pipeline"]

#: Groups whose members see the whole segment rather than only their own book.
TEAM_GROUPS = {
    "tl_portfolio", "portfolio_mgt", "ceo", "exco", "Management",
    "business_performance",
}


def _profile(user):
    from apps.portfolio.models import Profile
    return Profile.objects.filter(user=user).first()


def sees_team(user):
    """True when this user should see the whole segment, not just their rows."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return bool(set(user.groups.values_list("name", flat=True)) & TEAM_GROUPS)


def visible_to(user):
    """The rows this user may see. One definition, used by every endpoint."""
    qs = PipelineEntry.objects.select_related("updated_by")
    profile = _profile(user)

    if sees_team(user):
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

    for field in ("broad_stage", "stage", "deposit_product", "sales_code"):
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
        return _apply_filters(visible_to(self.request.user), self.request.query_params)

    def perform_create(self, serializer):
        profile = _profile(self.request.user)
        user = self.request.user
        # An RM's row is stamped with their own code and name. A team lead
        # creating on somebody's behalf may name them, so the value they sent
        # is respected when there is one.
        data = serializer.validated_data
        serializer.save(
            created_by=user,
            updated_by=user,
            sales_code=data.get("sales_code") or (profile.sales_code if profile else "") or "",
            rm_name=data.get("rm_name") or (user.get_full_name() or user.username).strip(),
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
        serializer.save(updated_by=self.request.user)

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
        rows = _apply_filters(visible_to(request.user), request.query_params)
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
            "scope": "team" if sees_team(request.user) else "mine",
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
        "product", "deposit_product", "account_no",
        "broad_stage", "stage", "expected_date", "comments",
        "is_active", "updated_by", "updated_at",
    ]

    def get(self, request):
        rows = _apply_filters(visible_to(request.user), request.query_params)

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
                e.deposit_product,
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
        rows = visible_to(request.user)
        products = (rows.exclude(product="")
                        .values_list("product", flat=True)
                        .distinct().order_by("product")[:200])
        return Response({
            "kinds": [{"value": v, "label": l} for v, l in PipelineEntry.KIND],
            "broad_stages": [{"value": v, "label": l}
                             for v, l in PipelineEntry.BROAD_STAGE],
            "stages": [{"value": v, "label": l} for v, l in PipelineEntry.STAGE],
            "stages_under_broad": {
                k: sorted(v) for k, v in PipelineEntry.STAGES_UNDER_BROAD.items()
            },
            "deposit_products": [{"value": v, "label": l}
                                 for v, l in PipelineEntry.DEPOSIT_PRODUCT],
            "fields_by_kind": PipelineEntry.FIELDS_BY_KIND,
            "product_suggestions": sorted(set(products)),
            "can_see_team": sees_team(request.user),
        })
