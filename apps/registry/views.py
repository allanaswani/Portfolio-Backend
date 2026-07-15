"""Records & Registry API — Phase 1 (§3.1–3.4).

Endpoints (mounted at ``registry/``):
    GET/POST      files/                  list / index a new file
    GET/PATCH/DEL files/<pk>/             retrieve / amend / remove a file
    POST          files/<pk>/issue/       issue the file to an officer
    POST          files/<pk>/return/      discharge borrower, return to pocket
    GET           cards/                  movement-card history (filterable)
    GET           overdue/                the fortnightly overdue report
    GET           my-files/               files the caller currently holds

Write actions require registry staff; reads require an authenticated user.
"""

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
import django_filters.rest_framework
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from core.permissions import InGroup, get_user_role, ROLE_ADMIN
from .models import (
    ArchiveBox,
    ArchiveConsignment,
    DestructionBatch,
    FileRecord,
    MovementCard,
    MAX_OPEN_FILES_PER_BORROWER,
    OVERDUE_DAYS,
    RETENTION_YEARS,
    _add_years,
)
from .serializers import (
    ApproveSerializer,
    ArchiveBoxSerializer,
    ArchiveConsignmentSerializer,
    CertifySerializer,
    DestroySerializer,
    DestructionBatchSerializer,
    FileRecordSerializer,
    FileSummarySerializer,
    IssueSerializer,
    MovementCardSerializer,
    ReceiveConsignmentSerializer,
    ReturnSerializer,
)

DjangoFilterBackend = django_filters.rest_framework.DjangoFilterBackend
TAG = ["Registry"]

# Registry back-office roles (superuser always allowed — see core.InGroup).
IsRegistryStaff = InGroup("registry_officer", "registry_supervisor", "archives_officer")


def _resolve_borrower(user_id):
    from django.contrib.auth.models import User
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist:
        raise ValidationError({"borrower": "No such user."})


# ── File register (§3.1) ─────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class FileListCreateView(generics.ListCreateAPIView):
    serializer_class = FileRecordSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "file_type", "retention_class", "account_no"]
    search_fields = ["file_no", "customer_name", "account_no"]
    queryset = FileRecord.objects.select_related("created_by").all()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsRegistryStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        # Lightweight free-text search (?search=) without a dedicated backend.
        term = self.request.query_params.get("search", "").strip()
        if term:
            from django.db.models import Q
            qs = qs.filter(
                Q(file_no__icontains=term)
                | Q(customer_name__icontains=term)
                | Q(account_no__icontains=term)
            )
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@extend_schema(tags=TAG)
class FileDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = FileRecordSerializer
    queryset = FileRecord.objects.select_related("created_by").all()

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [IsRegistryStaff()]


# ── Issue / Return (§3.2 / §3.3) ─────────────────────────────────────────────

@extend_schema(tags=TAG, request=IssueSerializer, responses=MovementCardSerializer)
class IssueView(APIView):
    """POST files/<pk>/issue/ — issue the file to an officer."""

    permission_classes = [IsRegistryStaff]

    def post(self, request, pk):
        file = generics.get_object_or_404(FileRecord, pk=pk)
        data = request.data.copy()
        data["file"] = file.pk
        payload = IssueSerializer(data=data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        if file.status == FileRecord.STATUS_ON_LOAN or file.open_card:
            raise ValidationError(
                {"file": "File is already on loan — return it before re-issuing."}
            )
        if file.status not in (FileRecord.STATUS_ACTIVE, FileRecord.STATUS_REDEEMED):
            raise ValidationError(
                {"file": f"File is '{file.get_status_display()}' and cannot be issued."}
            )

        borrower = _resolve_borrower(data["borrower"])

        # §3.2 cap: an officer may not hold more than 50 files at a time.
        open_count = MovementCard.objects.filter(
            borrower=borrower, returned_at__isnull=True
        ).count()
        if open_count >= MAX_OPEN_FILES_PER_BORROWER:
            raise ValidationError({
                "borrower": (
                    f"{borrower.get_username()} already holds {open_count} files "
                    f"(max {MAX_OPEN_FILES_PER_BORROWER}). Return some before issuing more."
                )
            })

        with transaction.atomic():
            card = MovementCard.objects.create(
                file=file,
                borrower=borrower,
                department=data.get("department", ""),
                purpose=data.get("purpose", ""),
                issued_by=request.user,
                borrower_ack=data.get("borrower_ack", False),
            )
            file.status = FileRecord.STATUS_ON_LOAN
            file.save(update_fields=["status", "updated_at"])

        return Response(MovementCardSerializer(card).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAG, request=ReturnSerializer, responses=MovementCardSerializer)
class ReturnView(APIView):
    """POST files/<pk>/return/ — discharge the borrower and shelve the file."""

    permission_classes = [IsRegistryStaff]

    def post(self, request, pk):
        file = generics.get_object_or_404(FileRecord, pk=pk)
        card = file.open_card
        if not card:
            raise ValidationError({"file": "File is not currently on loan."})

        payload = ReturnSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        with transaction.atomic():
            card.returned_at = timezone.now()
            card.returned_condition = data["returned_condition"]
            card.return_note = data.get("return_note", "")
            card.save(update_fields=[
                "returned_at", "returned_condition", "return_note",
            ])
            file.status = FileRecord.STATUS_ACTIVE
            file.save(update_fields=["status", "updated_at"])

        return Response(MovementCardSerializer(card).data)


# ── Movement-card history ────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class CardListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MovementCardSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["file", "borrower", "returned_condition"]
    queryset = MovementCard.objects.select_related("file", "borrower", "issued_by").all()


# ── Overdue report (§3.4) ────────────────────────────────────────────────────

@extend_schema(tags=TAG, responses=MovementCardSerializer(many=True))
class OverdueReportView(APIView):
    """GET overdue/ — every file held beyond the 4-week window.

    The fortnightly report the registry prints today, on demand and always
    current. Sorted worst-first; each row carries days overdue for triage.
    """

    permission_classes = [IsRegistryStaff]

    def get(self, request):
        now = timezone.now()
        cards = (
            MovementCard.objects
            .select_related("file", "borrower")
            .filter(returned_at__isnull=True, due_at__lt=now)
            .order_by("due_at")
        )
        rows = MovementCardSerializer(cards, many=True).data
        return Response({
            "as_of": now,
            "overdue_days_threshold": OVERDUE_DAYS,
            "count": len(rows),
            "results": rows,
        })


# ── Borrower lookup ──────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class UserLookupView(APIView):
    """GET users/?search= — minimal active-user list for the borrower picker.

    Registry officers aren't Django admins, so they cannot use the admin
    ``auth/users/`` API. This returns just id/username/name for active users so
    a file can be issued to the right person.
    """

    permission_classes = [IsRegistryStaff]

    def get(self, request):
        from django.contrib.auth.models import User
        from django.db.models import Q

        qs = User.objects.filter(is_active=True)
        term = request.query_params.get("search", "").strip()
        if term:
            qs = qs.filter(
                Q(username__icontains=term)
                | Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
            )
        qs = qs.order_by("first_name", "username")[:50]
        return Response([
            {
                "id": u.id,
                "username": u.username,
                "name": u.get_full_name().strip() or u.username,
            }
            for u in qs
        ])


# ── Self-service: files I hold ───────────────────────────────────────────────

@extend_schema(tags=TAG, responses=MovementCardSerializer(many=True))
class MyFilesView(APIView):
    """GET my-files/ — files the calling user currently has out."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cards = (
            MovementCard.objects
            .select_related("file")
            .filter(borrower=request.user, returned_at__isnull=True)
            .order_by("due_at")
        )
        return Response(MovementCardSerializer(cards, many=True).data)


# ── Archives: transfer & storage (§3.5) ──────────────────────────────────────

@extend_schema(tags=TAG)
class ConsignmentListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsRegistryStaff]
    serializer_class = ArchiveConsignmentSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "source_unit"]
    queryset = ArchiveConsignment.objects.prefetch_related("files", "boxes").all()

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)


@extend_schema(tags=TAG)
class ConsignmentDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsRegistryStaff]
    serializer_class = ArchiveConsignmentSerializer
    queryset = ArchiveConsignment.objects.prefetch_related("files", "boxes").all()


@extend_schema(tags=TAG, request=ReceiveConsignmentSerializer, responses=ArchiveConsignmentSerializer)
class ReceiveConsignmentView(APIView):
    """POST consignments/<pk>/receive/ - box the files and mark them archived."""

    permission_classes = [IsRegistryStaff]

    def post(self, request, pk):
        consignment = generics.get_object_or_404(ArchiveConsignment, pk=pk)
        if consignment.status == ArchiveConsignment.STATUS_RECEIVED:
            raise ValidationError({"consignment": "Already received."})

        payload = ReceiveConsignmentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        box_code = payload.validated_data["box_code"].strip()
        if ArchiveBox.objects.filter(code=box_code).exists():
            raise ValidationError({"box_code": "A box with this code already exists."})

        files = list(consignment.files.all())
        if not files:
            raise ValidationError({"consignment": "No files attached to this consignment."})

        now = timezone.now()
        with transaction.atomic():
            box = ArchiveBox.objects.create(
                code=box_code,
                location=payload.validated_data.get("location", ""),
                consignment=consignment,
            )
            for f in files:
                f.archive_box = box
                f.archived_at = now
                f.status = FileRecord.STATUS_ARCHIVED
            FileRecord.objects.bulk_update(files, ["archive_box", "archived_at", "status"])
            consignment.status = ArchiveConsignment.STATUS_RECEIVED
            consignment.received_by = request.user
            consignment.received_at = now
            consignment.save(update_fields=["status", "received_by", "received_at"])

        return Response(ArchiveConsignmentSerializer(consignment).data)


@extend_schema(tags=TAG)
class BoxListView(generics.ListAPIView):
    permission_classes = [IsRegistryStaff]
    serializer_class = ArchiveBoxSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["consignment"]
    queryset = ArchiveBox.objects.prefetch_related("files").all()


# ── Retention clock (§3.5 / §3.6) ────────────────────────────────────────────

@extend_schema(tags=TAG, responses=FileSummarySerializer(many=True))
class RetentionDueView(APIView):
    """GET retention-due/ - files whose 7-year retention has elapsed.

    Life-retention files (mortgage / account-opening) are never listed.
    """

    permission_classes = [IsRegistryStaff]

    def get(self, request):
        from django.db.models import Q

        today = timezone.now().date()
        threshold = _add_years(today, -RETENTION_YEARS)  # base <= threshold => due
        qs = (
            FileRecord.objects
            .exclude(retention_class=FileRecord.RETENTION_LIFE)
            .exclude(status=FileRecord.STATUS_DESTROYED)
            .filter(
                Q(redeemed_on__isnull=False, redeemed_on__lte=threshold)
                | Q(redeemed_on__isnull=True, opened_on__lte=threshold)
            )
            .order_by("opened_on")
        )
        rows = FileSummarySerializer(qs, many=True).data
        return Response({
            "as_of": today,
            "retention_years": RETENTION_YEARS,
            "count": len(rows),
            "results": rows,
        })


# ── Archives: destruction of records (§3.6) ──────────────────────────────────

@extend_schema(tags=TAG)
class DestructionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsRegistryStaff]
    serializer_class = DestructionBatchSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status"]
    queryset = DestructionBatch.objects.prefetch_related("files").all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@extend_schema(tags=TAG)
class DestructionDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsRegistryStaff]
    serializer_class = DestructionBatchSerializer
    queryset = DestructionBatch.objects.prefetch_related("files").all()


@extend_schema(tags=TAG, request=ApproveSerializer, responses=DestructionBatchSerializer)
class ApproveDestructionView(APIView):
    """POST destructions/<pk>/approve/ - record a sign-off stage (§3.6 step 1).

    ``unit`` may be signed by registry staff; ``head_ops`` and ``coo`` require an
    admin-tier user (Head of Operations / COO). All three => batch approved.
    """

    permission_classes = [IsRegistryStaff]

    def post(self, request, pk):
        batch = generics.get_object_or_404(DestructionBatch, pk=pk)
        payload = ApproveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        stage = payload.validated_data["stage"]

        if batch.status not in (DestructionBatch.STATUS_PENDING, DestructionBatch.STATUS_APPROVED):
            raise ValidationError({"batch": f"Cannot approve a '{batch.get_status_display()}' batch."})

        if stage in ("head_ops", "coo") and get_user_role(request.user) != ROLE_ADMIN:
            raise ValidationError(
                {"stage": "Head of Operations / COO sign-off requires an admin-tier user."}
            )

        now = timezone.now()
        if stage == "unit":
            batch.unit_ack_by, batch.unit_ack_at = request.user, now
        elif stage == "head_ops":
            batch.head_ops_by, batch.head_ops_at = request.user, now
        else:  # coo
            batch.coo_by, batch.coo_at = request.user, now

        if batch.is_fully_approved and batch.status == DestructionBatch.STATUS_PENDING:
            batch.status = DestructionBatch.STATUS_APPROVED
        batch.save()

        return Response(DestructionBatchSerializer(batch).data)


@extend_schema(tags=TAG, request=DestroySerializer, responses=DestructionBatchSerializer)
class DestroyBatchView(APIView):
    """POST destructions/<pk>/destroy/ - pulp the approved batch (§3.6 step 2)."""

    permission_classes = [IsRegistryStaff]

    def post(self, request, pk):
        batch = generics.get_object_or_404(DestructionBatch, pk=pk)
        if batch.status != DestructionBatch.STATUS_APPROVED:
            raise ValidationError(
                {"batch": "Batch must be fully approved (unit + Head of Ops + COO) before destruction."}
            )
        payload = DestroySerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        now = timezone.now()
        files = list(batch.files.all())
        with transaction.atomic():
            for f in files:
                f.status = FileRecord.STATUS_DESTROYED
            FileRecord.objects.bulk_update(files, ["status"])
            batch.vendor = payload.validated_data["vendor"]
            batch.destruction_location = payload.validated_data.get("destruction_location", "")
            batch.destroyed_at = now
            batch.status = DestructionBatch.STATUS_DESTROYED
            batch.save(update_fields=["vendor", "destruction_location", "destroyed_at", "status"])

        return Response(DestructionBatchSerializer(batch).data)


@extend_schema(tags=TAG, request=CertifySerializer, responses=DestructionBatchSerializer)
class CertifyDestructionView(APIView):
    """POST destructions/<pk>/certify/ - record the vendor certificate (§3.6 step 3)."""

    permission_classes = [IsRegistryStaff]

    def post(self, request, pk):
        batch = generics.get_object_or_404(DestructionBatch, pk=pk)
        if batch.status != DestructionBatch.STATUS_DESTROYED:
            raise ValidationError({"batch": "Only destroyed batches can be certified."})
        payload = CertifySerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        batch.certificate_ref = payload.validated_data["certificate_ref"]
        batch.certificate_note = payload.validated_data.get("certificate_note", "")
        batch.status = DestructionBatch.STATUS_CERTIFIED
        batch.save(update_fields=["certificate_ref", "certificate_note", "status"])

        return Response(DestructionBatchSerializer(batch).data)
