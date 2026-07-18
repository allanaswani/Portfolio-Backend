from django.contrib import admin

from .models import (
    ArchiveBox, ArchiveConsignment, DestructionBatch, FileRecord,
    MissingFileIncident, MovementCard, StockTake, StockTakeItem,
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


class StockTakeItemInline(admin.TabularInline):
    model = StockTakeItem
    extra = 0
    raw_id_fields = ("file", "sighted_by")


@admin.register(StockTake)
class StockTakeAdmin(admin.ModelAdmin):
    list_display = ("title", "location", "status", "opened_by", "opened_at", "closed_at")
    list_filter = ("status",)
    search_fields = ("title",)
    inlines = [StockTakeItemInline]


@admin.register(MissingFileIncident)
class MissingFileIncidentAdmin(admin.ModelAdmin):
    list_display = ("file", "status", "reported_by", "created_at", "resolved_at")
    list_filter = ("status",)
    search_fields = ("file__file_no",)
    raw_id_fields = ("file", "stock_take", "skeleton_file")
