from django.contrib import admin

from .models import (
    ArchiveBox, ArchiveConsignment, DestructionBatch, FileRecord, MovementCard,
)


@admin.register(FileRecord)
class FileRecordAdmin(admin.ModelAdmin):
    list_display = ("file_no", "customer_name", "file_type", "status", "pocket", "current_volume")
    list_filter = ("status", "file_type", "retention_class")
    search_fields = ("file_no", "customer_name", "account_no")


@admin.register(MovementCard)
class MovementCardAdmin(admin.ModelAdmin):
    list_display = ("file", "borrower", "issued_at", "due_at", "returned_at")
    list_filter = ("returned_condition",)
    search_fields = ("file__file_no", "borrower__username")
    autocomplete_fields = ("file", "borrower", "issued_by")


@admin.register(ArchiveConsignment)
class ArchiveConsignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "source_unit", "status", "requested_by", "received_at")
    list_filter = ("status",)


@admin.register(ArchiveBox)
class ArchiveBoxAdmin(admin.ModelAdmin):
    list_display = ("code", "location", "consignment", "created_at")
    search_fields = ("code",)


@admin.register(DestructionBatch)
class DestructionBatchAdmin(admin.ModelAdmin):
    list_display = ("reference", "status", "created_by", "destroyed_at", "certificate_ref")
    list_filter = ("status",)
    search_fields = ("reference",)
