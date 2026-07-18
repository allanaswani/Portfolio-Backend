from rest_framework import serializers

from .models import (
    ArchiveBox,
    ArchiveConsignment,
    DestructionBatch,
    FileRecord,
    MissingFileIncident,
    MovementCard,
    StockTake,
    StockTakeItem,
)


def _user_name(user):
    if not user:
        return None
    return user.get_full_name().strip() or user.username


class FileSummarySerializer(serializers.ModelSerializer):
    """Compact file representation for embedding in consignments/destructions."""

    retention_due_on = serializers.DateField(read_only=True)

    class Meta:
        model = FileRecord
        fields = ["id", "file_no", "customer_name", "file_type", "status", "retention_due_on"]


class MovementCardSerializer(serializers.ModelSerializer):
    borrower_name = serializers.SerializerMethodField()
    issued_by_name = serializers.SerializerMethodField()
    file_no = serializers.CharField(source="file.file_no", read_only=True)
    customer_name = serializers.CharField(source="file.customer_name", read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_out = serializers.IntegerField(read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)

    class Meta:
        model = MovementCard
        fields = "__all__"
        read_only_fields = [
            "issued_at", "issued_by", "due_at", "returned_at",
            "escalated_at",
        ]

    def get_borrower_name(self, obj):
        return _user_name(obj.borrower)

    def get_issued_by_name(self, obj):
        return _user_name(obj.issued_by)


class FileRecordSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    held_by = serializers.SerializerMethodField()
    retention_due_on = serializers.DateField(read_only=True)
    is_destruction_due = serializers.BooleanField(read_only=True)

    class Meta:
        model = FileRecord
        fields = "__all__"
        read_only_fields = ["created_by", "created_at", "updated_at", "archived_at", "archive_box"]

    def get_created_by_name(self, obj):
        return _user_name(obj.created_by)

    def get_held_by(self, obj):
        """Summary of who currently holds the file (if on loan)."""
        card = obj.open_card
        if not card:
            return None
        return {
            "card_id": card.id,
            "borrower": _user_name(card.borrower),
            "borrower_id": card.borrower_id,
            "issued_at": card.issued_at,
            "due_at": card.due_at,
            "is_overdue": card.is_overdue,
            "days_overdue": card.days_overdue,
        }


class IssueSerializer(serializers.Serializer):
    """Issue one file to a borrower — creates a MovementCard (§3.2)."""

    file = serializers.PrimaryKeyRelatedField(queryset=FileRecord.objects.all())
    borrower = serializers.IntegerField(help_text="User id of the officer taking the file.")
    department = serializers.CharField(required=False, allow_blank=True, default="")
    purpose = serializers.CharField(required=False, allow_blank=True, default="")
    borrower_ack = serializers.BooleanField(default=False)


class ReturnSerializer(serializers.Serializer):
    """Discharge the borrower and return the file to its pocket (§3.3)."""

    returned_condition = serializers.ChoiceField(
        choices=MovementCard.CONDITION_CHOICES, default=MovementCard.CONDITION_OK,
    )
    return_note = serializers.CharField(required=False, allow_blank=True, default="")


# ── Archives: transfer & storage (§3.5) ──────────────────────────────────────

class ArchiveBoxSerializer(serializers.ModelSerializer):
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = ArchiveBox
        fields = ["id", "code", "location", "consignment", "created_at", "file_count"]

    def get_file_count(self, obj):
        return obj.files.count()


class ArchiveConsignmentSerializer(serializers.ModelSerializer):
    files = FileSummarySerializer(many=True, read_only=True)
    file_ids = serializers.PrimaryKeyRelatedField(
        queryset=FileRecord.objects.all(), many=True, write_only=True, source="files",
    )
    requested_by_name = serializers.SerializerMethodField()
    received_by_name = serializers.SerializerMethodField()
    boxes = ArchiveBoxSerializer(many=True, read_only=True)

    class Meta:
        model = ArchiveConsignment
        fields = "__all__"
        read_only_fields = [
            "status", "requested_by", "created_at", "received_by", "received_at",
        ]

    def get_requested_by_name(self, obj):
        return _user_name(obj.requested_by)

    def get_received_by_name(self, obj):
        return _user_name(obj.received_by)


class ReceiveConsignmentSerializer(serializers.Serializer):
    """Box and archive every file in a consignment (§3.5)."""

    box_code = serializers.CharField()
    location = serializers.CharField(required=False, allow_blank=True, default="")


# ── Archives: destruction of records (§3.6) ──────────────────────────────────

class DestructionBatchSerializer(serializers.ModelSerializer):
    files = FileSummarySerializer(many=True, read_only=True)
    file_ids = serializers.PrimaryKeyRelatedField(
        queryset=FileRecord.objects.all(), many=True, write_only=True, source="files",
    )
    created_by_name = serializers.SerializerMethodField()
    unit_ack_by_name = serializers.SerializerMethodField()
    head_ops_by_name = serializers.SerializerMethodField()
    coo_by_name = serializers.SerializerMethodField()
    is_fully_approved = serializers.BooleanField(read_only=True)

    class Meta:
        model = DestructionBatch
        fields = "__all__"
        read_only_fields = [
            "reference", "status", "created_by", "created_at",
            "unit_ack_by", "unit_ack_at", "head_ops_by", "head_ops_at",
            "coo_by", "coo_at", "destroyed_at",
        ]

    def get_created_by_name(self, obj):
        return _user_name(obj.created_by)

    def get_unit_ack_by_name(self, obj):
        return _user_name(obj.unit_ack_by)

    def get_head_ops_by_name(self, obj):
        return _user_name(obj.head_ops_by)

    def get_coo_by_name(self, obj):
        return _user_name(obj.coo_by)


class ApproveSerializer(serializers.Serializer):
    STAGE_CHOICES = ["unit", "head_ops", "coo"]
    stage = serializers.ChoiceField(choices=STAGE_CHOICES)


class DestroySerializer(serializers.Serializer):
    vendor = serializers.CharField()
    destruction_location = serializers.CharField(required=False, allow_blank=True, default="")


class CertifySerializer(serializers.Serializer):
    certificate_ref = serializers.CharField()
    certificate_note = serializers.CharField(required=False, allow_blank=True, default="")


# ── Stock-take & missing files (§3.7) ────────────────────────────────────────

class StockTakeItemSerializer(serializers.ModelSerializer):
    file_no = serializers.CharField(source="file.file_no", read_only=True)
    customer_name = serializers.CharField(source="file.customer_name", read_only=True)
    pocket = serializers.CharField(source="file.pocket", read_only=True)
    sighted_by_name = serializers.SerializerMethodField()
    marked_to_name = serializers.SerializerMethodField()

    class Meta:
        model = StockTakeItem
        fields = [
            "id", "file", "file_no", "customer_name", "pocket",
            "sighted", "sighted_by", "sighted_by_name", "sighted_at", "remark",
            "marked_to", "marked_to_name",
        ]
        read_only_fields = ["file", "sighted_by", "sighted_at", "marked_to"]

    def get_sighted_by_name(self, obj):
        return _user_name(obj.sighted_by)

    def get_marked_to_name(self, obj):
        return _user_name(obj.marked_to)


class StockTakeSerializer(serializers.ModelSerializer):
    opened_by_name = serializers.SerializerMethodField()
    closed_by_name = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    sighted = serializers.SerializerMethodField()
    missing = serializers.SerializerMethodField()
    missing_marked = serializers.SerializerMethodField()
    missing_unmarked = serializers.SerializerMethodField()

    class Meta:
        model = StockTake
        fields = [
            "id", "title", "location", "status", "notes",
            "opened_by", "opened_by_name", "opened_at",
            "closed_by", "closed_by_name", "closed_at",
            "total", "sighted", "missing", "missing_marked", "missing_unmarked",
        ]
        read_only_fields = [
            "status", "opened_by", "opened_at", "closed_by", "closed_at",
        ]

    def get_opened_by_name(self, obj):
        return _user_name(obj.opened_by)

    def get_closed_by_name(self, obj):
        return _user_name(obj.closed_by)

    def get_total(self, obj):
        return obj.items.count()

    def get_sighted(self, obj):
        return obj.items.filter(sighted=True).count()

    def get_missing(self, obj):
        # Meaningful once closed; while open it's just "not yet sighted".
        return obj.items.filter(sighted=False).count()

    # §3.7 step 3 splits the untraced files for the stock-take status report:
    # those marked to an officer (chase per the overdue procedure) and those
    # marked to nobody (no trace — the skeleton path).
    def get_missing_marked(self, obj):
        return obj.items.filter(sighted=False, marked_to__isnull=False).count()

    def get_missing_unmarked(self, obj):
        return obj.items.filter(sighted=False, marked_to__isnull=True).count()


class StockTakeDetailSerializer(StockTakeSerializer):
    items = StockTakeItemSerializer(many=True, read_only=True)

    class Meta(StockTakeSerializer.Meta):
        fields = StockTakeSerializer.Meta.fields + ["items"]


class SightSerializer(serializers.Serializer):
    """Mark one stock-take line as sighted (or not) (§3.7)."""

    item = serializers.PrimaryKeyRelatedField(queryset=StockTakeItem.objects.all())
    sighted = serializers.BooleanField(default=True)
    remark = serializers.CharField(required=False, allow_blank=True, default="")


class MissingFileIncidentSerializer(serializers.ModelSerializer):
    file_no = serializers.CharField(source="file.file_no", read_only=True)
    customer_name = serializers.CharField(source="file.customer_name", read_only=True)
    reported_by_name = serializers.SerializerMethodField()
    resolved_by_name = serializers.SerializerMethodField()
    marked_to_name = serializers.SerializerMethodField()
    skeleton_file_no = serializers.CharField(source="skeleton_file.file_no", read_only=True)

    class Meta:
        model = MissingFileIncident
        fields = "__all__"
        read_only_fields = [
            "status", "reported_by", "created_at",
            "resolution_note", "skeleton_file", "resolved_by", "resolved_at",
        ]

    def get_reported_by_name(self, obj):
        return _user_name(obj.reported_by)

    def get_resolved_by_name(self, obj):
        return _user_name(obj.resolved_by)

    def get_marked_to_name(self, obj):
        return _user_name(obj.marked_to)


class ResolveIncidentSerializer(serializers.Serializer):
    """Close a missing-file incident (§3.7).

    ``found``   — the original turned up; file returns to active.
    ``skeleton``— reconstruct a skeleton file to stand in for the lost original.
    ``written_off`` — file is written off; stays missing.
    """

    outcome = serializers.ChoiceField(choices=["found", "skeleton", "written_off"])
    resolution_note = serializers.CharField(required=False, allow_blank=True, default="")
