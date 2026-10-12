"""Administration endpoints for the cost analysis.

The cost figures on the CEO deck were hard-coded in the frontend. These are
what replaces them, plus the screens to keep the mappings current — which is
the part that matters, because a posting whose cost centre is not mapped is
money missing from a department total and nobody would see it.

Reading the summary needs only a signed-in user, because the CEO deck reads it.
Changing a mapping or loading an extract is an administrator's action.
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from .cost_serializers import (
    SapCostCentreSerializer, SapCostExclusionSerializer,
    SapCostPostingSerializer, SapSubsidiarySerializer,
)
from .models import (
    SapCostCentre, SapCostExclusion, SapCostPosting, SapSubsidiary,
)

TAG = "Cost analysis"


def _may_change(user):
    """Changing what every department's cost total is built from.

    The same gate the scorecard figures use, and for the same reason: this is
    not per-module RBAC, it is "may this person change what the CEO deck
    reports". ``is_staff`` is deliberately not accepted - it is legacy noise in
    this estate and carried by a great many accounts.
    """
    return bool(
        user and user.is_authenticated
        and (user.is_superuser
             or user.groups.filter(
                 name__in=("staff_mgt", "Management", "finance")).exists()))


@extend_schema(tags=[TAG])
class CostSummaryView(APIView):
    """Operating cost by department, by branch, by expense line, by company.

    One call, because the screen is one document: read separately, the four
    tables could disagree about which extract they came from.

    ``?snapshot=YYYY-MM-DD`` reads an older extract; without it, the newest.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime

        from . import cost_analysis

        raw = str(request.query_params.get("snapshot") or "").strip()
        snapshot = None
        if raw:
            try:
                snapshot = datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"snapshot": f"{raw!r} is not a date. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST)

        years = None
        raw_year = str(request.query_params.get("year") or "").strip()
        if raw_year.isdigit():
            years = [int(raw_year) - 1, int(raw_year)]

        payload = cost_analysis.summary(snapshot, years)
        if payload["snapshot_date"] is None:
            # Said plainly rather than returning empty tables: the screen can
            # then tell "nothing loaded yet" apart from "loaded and nil".
            payload["detail"] = (
                "No SAP cost extract has been loaded yet. Run "
                "'manage.py load_sap_costs' on the host, or load the extract "
                "on this screen.")
        return Response(payload)


@extend_schema(tags=[TAG])
class CostSnapshotsView(APIView):
    """Which extracts have been loaded, newest first."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Max, Min, Sum

        rows = (SapCostPosting.objects
                .values("snapshot_date")
                .annotate(postings=Count("id"), amount=Sum("amount"),
                          first_month=Min("entry_month"),
                          last_month=Max("entry_month"),
                          loaded=Max("loaded_at"))
                .order_by("-snapshot_date"))
        return Response({"snapshots": [{
            "snapshot_date": r["snapshot_date"].isoformat()
            if r["snapshot_date"] else None,
            "postings": r["postings"],
            "amount": float(r["amount"] or 0),
            "first_month": r["first_month"],
            "last_month": r["last_month"],
            "loaded_at": r["loaded"].isoformat() if r["loaded"] else None,
        } for r in rows]})


@extend_schema(tags=[TAG])
class CostUploadView(APIView):
    """Load an extract from a file.

    Read and report first; only a second call with ``apply=true`` writes. These
    figures are what the CEO deck reports, and an import that silently replaced
    a snapshot would be worse than no import.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 80 * 1024 * 1024

    def post(self, request):
        from . import cost_analysis, cost_ingest

        if not _may_change(request.user):
            return Response(
                {"detail": "Only an administrator can load the cost extract."},
                status=status.HTTP_403_FORBIDDEN)

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Choose the extract first."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not upload.name.lower().endswith((".xlsx", ".xlsm")):
            return Response(
                {"file": f"{upload.name} is not an Excel workbook. Save it as "
                         f".xlsx and try again."},
                status=status.HTTP_400_BAD_REQUEST)
        if upload.size > self.MAX_BYTES:
            return Response(
                {"file": f"That file is {upload.size / 1024 / 1024:.1f} MB; "
                         f"the limit is {self.MAX_BYTES // 1024 // 1024} MB."},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            rows = cost_ingest.read_workbook(upload)
        except ValueError as exc:
            return Response({"file": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return Response({"file": f"That file could not be read: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)

        if not rows:
            return Response(
                {"file": "That extract is empty. Nothing has been changed - an "
                         "empty load must not wipe the snapshot that is there."},
                status=status.HTTP_400_BAD_REQUEST)

        who = (request.user.get_full_name() or request.user.username).strip()
        postings, report = cost_ingest.rows_to_postings(rows, loaded_by=who)
        report.pop("snapshot_dates_set", None)

        if str(request.data.get("apply", "")).strip().lower() not in (
                "1", "true", "yes", "on"):
            return Response({
                "applied": False,
                "report": report,
                "detail": (f"{report['kept']:,} posting(s) read for extract "
                           f"date {', '.join(report['snapshot_dates']) or '-'}. "
                           f"Nothing has been saved. Send the same file with "
                           f"apply=true to save."),
            })

        if not report["kept"]:
            return Response(
                {"applied": False, "report": report,
                 "detail": "Nothing in that extract could be read."},
                status=status.HTTP_400_BAD_REQUEST)

        result = cost_ingest.save_postings(postings, report)
        if not result["written"]:
            return Response({"applied": False, "report": report,
                             "detail": result["detail"]},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "applied": True,
            "report": report,
            "result": result,
            "health": cost_analysis.health(),
            "detail": result["detail"],
        })


@extend_schema(tags=[TAG])
class CostTrinoLoadView(APIView):
    """Pull the extract from the lake, now.

    The scheduled command is the normal route; this is for when somebody needs
    it before the next run. It can take a while and it replaces the snapshot,
    so it is a POST and it is gated.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from . import cost_analysis, cost_ingest

        if not _may_change(request.user):
            return Response(
                {"detail": "Only an administrator can load the cost extract."},
                status=status.HTTP_403_FORBIDDEN)

        try:
            rows = cost_ingest.fetch_from_trino()
        except RuntimeError as exc:
            # TRINO_HOST unset - a configuration answer, not a failure.
            return Response({"detail": str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:  # noqa: BLE001 - the reason matters
            return Response(
                {"detail": f"The lake could not be queried: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY)

        if not rows:
            return Response(
                {"detail": "The lake returned no rows. Nothing has been "
                           "changed."},
                status=status.HTTP_400_BAD_REQUEST)

        who = (request.user.get_full_name() or request.user.username).strip()
        postings, report = cost_ingest.rows_to_postings(rows, loaded_by=who)
        result = cost_ingest.save_postings(postings, report)
        if not result["written"]:
            return Response({"report": report, "detail": result["detail"]},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"report": report, "result": result,
                         "health": cost_analysis.health(),
                         "detail": result["detail"]})


# ── The mappings, which are the part that needs keeping current ──────────────


class _AdminWritable(generics.ListCreateAPIView):
    """Anybody signed in may read a mapping; only an administrator may add."""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]

    def create(self, request, *args, **kwargs):
        if not _may_change(request.user):
            return Response(
                {"detail": "Only an administrator can change the cost "
                           "mappings."}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        who = (self.request.user.get_full_name()
               or self.request.user.username).strip()
        if "updated_by" in serializer.fields:
            serializer.save(updated_by=who[:150])
        else:
            serializer.save()


class _AdminEditable(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]

    def _gate(self, request):
        if not _may_change(request.user):
            return Response(
                {"detail": "Only an administrator can change the cost "
                           "mappings."}, status=status.HTTP_403_FORBIDDEN)
        return None

    def update(self, request, *args, **kwargs):
        return self._gate(request) or super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return self._gate(request) or super().destroy(request, *args, **kwargs)

    def perform_update(self, serializer):
        who = (self.request.user.get_full_name()
               or self.request.user.username).strip()
        if "updated_by" in serializer.fields:
            serializer.save(updated_by=who[:150])
        else:
            serializer.save()


@extend_schema(tags=[TAG])
class CostCentreListCreateView(_AdminWritable):
    serializer_class = SapCostCentreSerializer
    filterset_fields = ["cost_department", "is_branch", "is_reportable"]
    queryset = SapCostCentre.objects.all()


@extend_schema(tags=[TAG])
class CostCentreDetailView(_AdminEditable):
    serializer_class = SapCostCentreSerializer
    queryset = SapCostCentre.objects.all()


@extend_schema(tags=[TAG])
class SubsidiaryListCreateView(_AdminWritable):
    serializer_class = SapSubsidiarySerializer
    filterset_fields = ["company_code"]
    queryset = SapSubsidiary.objects.all()


@extend_schema(tags=[TAG])
class SubsidiaryDetailView(_AdminEditable):
    serializer_class = SapSubsidiarySerializer
    queryset = SapSubsidiary.objects.all()


@extend_schema(tags=[TAG])
class CostExclusionListCreateView(_AdminWritable):
    serializer_class = SapCostExclusionSerializer
    filterset_fields = ["gl"]
    queryset = SapCostExclusion.objects.all()


@extend_schema(tags=[TAG])
class CostExclusionDetailView(_AdminEditable):
    serializer_class = SapCostExclusionSerializer
    queryset = SapCostExclusion.objects.all()


@extend_schema(tags=[TAG])
class CostPostingListView(generics.ListAPIView):
    """The postings behind a figure.

    The reason the mirror is kept at document-item grain: a department total
    nobody can break down into its postings is a figure nobody can defend.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SapCostPostingSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["snapshot_date", "fiscal_year", "cost_centre",
                        "gl_account_number", "entry_month", "company_code"]
    queryset = SapCostPosting.objects.all().order_by("-entry_date", "-id")
