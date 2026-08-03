from django.contrib import admin

from .models import StrategyTarget


@admin.register(StrategyTarget)
class StrategyTargetAdmin(admin.ModelAdmin):
    list_display = ("metric", "scope_type", "scope_value", "period_type",
                    "year", "quarter", "month", "target_value", "created_by")
    list_filter = ("metric", "scope_type", "period_type", "year")
    search_fields = ("scope_value", "note")
    autocomplete_fields = ()
