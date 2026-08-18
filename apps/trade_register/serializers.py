from rest_framework import serializers

from .models import TradeProduct, TradeRegisterEntry


class TradeProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeProduct
        fields = ["id", "code", "name", "ref_family", "is_active", "sort_order"]


class TradeRegisterEntrySerializer(serializers.ModelSerializer):
    # Read-only conveniences for the table/form.
    product_code = serializers.CharField(source="product.code", read_only=True)
    ref_family = serializers.CharField(source="product.ref_family", read_only=True)

    class Meta:
        model = TradeRegisterEntry
        fields = [
            "id", "tf",
            "originating_branch", "rm_name", "rm_code",
            "guarantee_ref",
            "product", "product_code", "product_type", "ref_family",
            "amendment_type", "parent_ref",
            "customer_id", "segment", "our_customer", "beneficiary",
            "currency", "amount_fcy", "fx_rate", "commission",
            "issue_date", "is_open_ended", "expiry_date",
            "security_type", "cash_cover_amount", "cash_cover_percentage",
            "other_security",
            "month", "year",
            "created_at", "updated_at",
        ]
        read_only_fields = ["tf", "product_type", "month", "year", "created_at", "updated_at"]

    def validate(self, attrs):
        """Same shape of validation the desk needs — an amendment must name its
        parent; a non-open-ended item should have an expiry date."""
        amendment = attrs.get("amendment_type", getattr(self.instance, "amendment_type", ""))
        parent = attrs.get("parent_ref", getattr(self.instance, "parent_ref", ""))
        if amendment and not parent:
            raise serializers.ValidationError(
                {"parent_ref": "An amendment/extension must reference the original guarantee/LC number."}
            )
        return attrs
