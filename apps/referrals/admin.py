from django.contrib import admin

from .models import Referral


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        "referral_ref", "customer_name", "phone", "status",
        "assigned_to", "is_possible_duplicate", "staff_verified", "created_at",
    )
    list_filter = ("status", "is_possible_duplicate", "staff_verified")
    search_fields = ("referral_ref", "customer_name", "national_id", "phone", "pf_number", "sales_code")
    readonly_fields = ("referral_ref", "is_possible_duplicate", "created_at", "updated_at")
    autocomplete_fields = ("created_by", "assigned_to", "allocated_by")
    date_hierarchy = "created_at"
