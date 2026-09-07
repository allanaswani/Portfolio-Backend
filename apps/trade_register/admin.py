from django.contrib import admin

from .models import TradeCurrency, TradeProduct, TradeRegisterEntry, TradeTariff


@admin.register(TradeTariff)
class TradeTariffAdmin(admin.ModelAdmin):
    """The tariff book. Editing a rate here reprices every product mapped to it."""

    list_display = (
        "code", "name", "commission_basis", "commission_rate",
        "minimum_commission", "excise_rate", "product_count", "is_active",
    )
    list_filter = ("commission_basis", "is_active")
    search_fields = ("code", "name", "description")
    ordering = ("sort_order", "code")

    @admin.display(description="Products")
    def product_count(self, obj):
        return obj.products.count()


@admin.register(TradeProduct)
class TradeProductAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "ref_family", "tariff", "commission_basis",
        "commission_rate", "is_active", "sort_order",
    )
    list_filter = ("ref_family", "is_active", "tariff")
    search_fields = ("code", "name")
    autocomplete_fields = ()


@admin.register(TradeCurrency)
class TradeCurrencyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(TradeRegisterEntry)
class TradeRegisterEntryAdmin(admin.ModelAdmin):
    list_display = (
        "guarantee_ref", "product_type", "our_customer", "issue_date",
        "expiry_date", "amount_fcy", "currency", "commission", "excise_duty",
    )
    list_filter = ("currency", "segment", "originating_branch", "tariff_code")
    search_fields = ("guarantee_ref", "our_customer", "beneficiary", "rm_name")
    date_hierarchy = "issue_date"
    readonly_fields = ("excise_duty", "tariff_code")
