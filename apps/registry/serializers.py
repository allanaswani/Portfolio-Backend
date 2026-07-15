from rest_framework import serializers

from .models import (
    ArchiveBox,
    ArchiveConsignment,
    DestructionBatch,
    FileRecord,
    MovementCard,
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
