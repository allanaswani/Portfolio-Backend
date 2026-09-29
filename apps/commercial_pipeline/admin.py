from django.contrib import admin

from .models import PipelineEntry


@admin.register(PipelineEntry)
class PipelineEntryAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "kind", "rm_name", "amount",
                    "broad_stage", "is_active", "updated_at")
    list_filter = ("kind", "broad_stage", "is_active", "segment")
    search_fields = ("customer_name", "rm_name", "sales_code", "product")
