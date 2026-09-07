from rest_framework import serializers

from .models import TradeCurrency, TradeProduct, TradeRegisterEntry, TradeTariff


class TradeTariffSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = TradeTariff
        fields = [
            "id", "code", "name", "description",
            "commission_basis", "commission_rate", "minimum_commission",
            "excise_rate", "is_active", "sort_order", "products",
        ]
        read_only_fields = ["id"]

    def get_products(self, obj):
        """Which products this line prices — the point of the mapping is being
        able to see what a rate change would reach."""
        return list(obj.products.values_list("code", flat=True))


class TradeProductSerializer(serializers.ModelSerializer):
    # What this product is actually charged at, wherever the rate came from.
    tariff_code = serializers.CharField(source="tariff.code", read_only=True, default="")
    tariff_name = serializers.CharField(source="tariff.name", read_only=True, default="")
    pricing_source = serializers.CharField(read_only=True)
    effective_excise_rate = serializers.DecimalField(
        source="excise_rate", max_digits=9, decimal_places=6, read_only=True,
    )

    class Meta:
        model = TradeProduct
        fields = [
            "id", "code", "name", "ref_family", "is_active", "sort_order",
            "tariff", "tariff_code", "tariff_name", "pricing_source",
            "commission_basis", "commission_rate", "minimum_commission",
            "effective_excise_rate",
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
    # Excise and the tariff line are worked out on save; exposing them read-only
    # keeps the one calculation in the model rather than letting a client post a
    # duty figure that does not match the fee.
    total_charge = serializers.SerializerMethodField()
    diary_status = serializers.SerializerMethodField()
    diary_label = serializers.SerializerMethodField()
    days_to_expiry = serializers.SerializerMethodField()

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
            "excise_duty", "total_charge", "tariff_code",
            "reporting_date", "issue_date", "is_open_ended", "expiry_date",
            "diary_status", "diary_label", "days_to_expiry",
            "security_type", "cash_cover_amount", "cash_cover_percentage",
            "other_security",
            "month", "year",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "tf", "product_type", "month", "year", "created_at", "updated_at",
            "excise_duty", "tariff_code",
        ]

    def get_total_charge(self, obj):
        """Commission plus duty — what the customer is actually billed."""
        return str((obj.commission or 0) + (obj.excise_duty or 0))

    def get_diary_status(self, obj):
        return obj.diary_status()

    def get_diary_label(self, obj):
        return obj.DIARY_LABELS.get(obj.diary_status(), "")

    def get_days_to_expiry(self, obj):
        return obj.days_to_expiry()

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
            "source": quote.get("source", ""),
            "tariff_code": quote.get("tariff_code", ""),
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
