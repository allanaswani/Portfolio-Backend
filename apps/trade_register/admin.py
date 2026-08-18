from django.contrib import admin

from .models import TradeProduct, TradeRegisterEntry


@admin.register(TradeProduct)
class TradeProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "ref_family", "is_active", "sort_order")
    list_filter = ("ref_family", "is_active")
    search_fields = ("code", "name")


@admin.register(TradeRegisterEntry)
class TradeRegisterEntryAdmin(admin.ModelAdmin):
    list_display = ("guarantee_ref", "product_type", "our_customer", "issue_date", "amount_fcy", "currency")
    list_filter = ("currency", "segment", "originating_branch")
    search_fields = ("guarantee_ref", "our_customer", "beneficiary", "rm_name")
    date_hierarchy = "issue_date"
