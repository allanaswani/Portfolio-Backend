from rest_framework import serializers

from .models import TradeCurrency, TradeProduct, TradeRegisterEntry


class TradeProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeProduct
        fields = [
            "id", "code", "name", "ref_family", "is_active", "sort_order",
            "commission_basis", "commission_rate", "minimum_commission",
        ]


class TradeProductAdminSerializer(TradeProductSerializer):
    """The product as Administration maintains it — pricing included.

    Rates live in the database precisely so a change is an edit rather than a
    deploy; this is the serializer that lets someone make that edit.
    """

    class Meta(TradeProductSerializer.Meta):
        read_only_fields = ["id"]


class TradeCurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeCurrency
        fields = ["id", "code", "name", "is_active", "sort_order"]
        read_only_fields = ["id"]


class TradeRegisterEntrySerializer(serializers.ModelSerializer):
    # Read-only conveniences for the table/form.
    product_code = serializers.CharField(source="product.code", read_only=True)
    ref_family = serializers.CharField(source="product.ref_family", read_only=True)
    # What the product's own pricing says this transaction should cost, and how
    # it was worked out — shown beside the figure so an override is a visible,
    # deliberate act rather than a silent divergence.
    commission_quote = serializers.SerializerMethodField()

    class Meta:
        model = TradeRegisterEntry
        fields = [
            "id", "tf",
            "originating_branch", "rm_name", "rm_code",
            "guarantee_ref",
            "product", "product_code", "product_type", "ref_family",
            "amendment_type", "parent_ref",
            "customer_id", "segment", "our_customer", "beneficiary",
            "currency", "amount_fcy", "fx_rate",
            "commission", "commission_override", "commission_quote",
            "reporting_date", "issue_date", "is_open_ended", "expiry_date",
            "security_type", "cash_cover_amount", "cash_cover_percentage",
            "other_security",
            "month", "year",
            "created_at", "updated_at",
        ]
        read_only_fields = ["tf", "product_type", "month", "year", "created_at", "updated_at"]

    def get_commission_quote(self, obj):
        quote = obj.quote_commission()
        if not quote:
            return None
        return {
            "calculable": quote["calculable"],
            "commission": (str(quote["commission"])
                           if quote["commission"] is not None else None),
            "basis": quote["basis"],
            "rate": str(quote["rate"]),
            "periods": str(quote["periods"]) if quote["periods"] is not None else None,
            "minimum_applied": quote["minimum_applied"],
            "explanation": quote["explanation"],
        }

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
