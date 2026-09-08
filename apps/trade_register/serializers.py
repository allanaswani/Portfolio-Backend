from rest_framework import serializers

from . import references as refs
from .models import (
    TradeCurrency, TradeProduct, TradeProductCategory, TradeRegisterEntry,
    TradeTariff,
)


class TradeProductCategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = TradeProductCategory
        fields = ["id", "code", "name", "description", "is_active",
                  "sort_order", "product_count"]
        read_only_fields = ["id"]

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class TradeTariffSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    product_code = serializers.CharField(source="product.code", read_only=True, default="")
    charge_summary = serializers.SerializerMethodField()

    class Meta:
        model = TradeTariff
        fields = [
            "id", "code", "name", "description",
            "category", "category_name", "action", "product", "product_code",
            "commission_basis", "commission_rate", "fixed_amount",
            "minimum_commission", "charge_currency", "manual_note",
            "excise_rate", "is_active", "sort_order", "products",
            "charge_summary",
        ]
        read_only_fields = ["id"]

    def get_products(self, obj):
        """Which products this line prices — the point of the mapping is being
        able to see what a rate change would reach."""
        if obj.product_id:
            return [obj.product.code]
        if obj.category_id:
            return list(obj.category.products.filter(is_active=True)
                        .values_list("code", flat=True))
        return []

    def get_charge_summary(self, obj):
        """The line as the tariff book states it, in one string."""
        if obj.manual_note:
            return obj.manual_note
        bits = []
        if obj.commission_rate:
            unit = {
                TradeTariff.BASIS_PER_QUARTER: " per quarter",
                TradeTariff.BASIS_PER_ANNUM: " per annum",
                TradeTariff.BASIS_PER_MONTH: " per month",
            }.get(obj.commission_basis, "")
            bits.append(f"{obj.commission_rate.normalize()}%{unit}")
        if obj.fixed_amount:
            bits.append(f"{obj.charge_currency} {obj.fixed_amount:,.2f}")
        if obj.minimum_commission:
            bits.append(f"Min. {obj.charge_currency} {obj.minimum_commission:,.2f}")
        return "; ".join(bits) or "Not priced — entered by hand"


class TradeProductSerializer(serializers.ModelSerializer):
    # What this product is actually charged at, wherever the rate came from.
    tariff_code = serializers.CharField(source="tariff.code", read_only=True, default="")
    tariff_name = serializers.CharField(source="tariff.name", read_only=True, default="")
    pricing_source = serializers.CharField(read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True, default="")
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    effective_excise_rate = serializers.DecimalField(
        source="excise_rate", max_digits=9, decimal_places=6, read_only=True,
    )

    class Meta:
        model = TradeProduct
        fields = [
            "id", "code", "name", "category", "category_code", "category_name",
            "ref_family", "is_active", "sort_order",
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
    product_category = serializers.PrimaryKeyRelatedField(
        source="product.category", read_only=True,
    )
    product_category_name = serializers.CharField(
        source="product.category.name", read_only=True, default="",
    )
    # The instrument's LIVE position: what was issued plus what its amendments
    # did to it. The issued figures stay on the record untouched.
    current_amount = serializers.SerializerMethodField()
    effective_expiry_date = serializers.SerializerMethodField()
    amendment_count = serializers.SerializerMethodField()

    class Meta:
        model = TradeRegisterEntry
        fields = [
            "id", "tf",
            "originating_branch", "rm_name", "rm_code",
            "guarantee_ref",
            "product", "product_code", "product_type", "ref_family",
            "product_category", "product_category_name",
            "action", "parent", "parent_ref", "amount_delta", "new_expiry_date",
            "current_amount", "effective_expiry_date", "amendment_count",
            "customer_id", "segment", "our_customer", "beneficiary",
            "currency", "amount_fcy", "fx_rate",
            "commission", "commission_override", "commission_quote",
            "excise_duty", "total_charge", "tariff_code",
            "reporting_date", "issue_date", "is_open_ended", "expiry_date",
            "diary_status", "diary_label", "days_to_expiry",
            "is_archived", "archived_on",
            "security_type", "cash_cover_amount", "cash_cover_percentage",
            "other_security",
            "month", "year",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "tf", "product_type", "month", "year", "created_at", "updated_at",
            "excise_duty", "tariff_code", "parent", "archived_on",
        ]

    def get_current_amount(self, obj):
        return str(obj.current_amount)

    def get_effective_expiry_date(self, obj):
        return obj.effective_expiry_date

    def get_amendment_count(self, obj):
        return obj.amendment_count

    def get_total_charge(self, obj):
        """Commission plus duty — what the customer is actually billed."""
        return str((obj.commission or 0) + (obj.excise_duty or 0))

    def get_diary_status(self, obj):
        return obj.diary_status()

    def get_diary_label(self, obj):
        return obj.DIARY_LABELS.get(obj.diary_status(), "")

    def get_days_to_expiry(self, obj):
        return obj.days_to_expiry()

    def _tariff_line(self, obj):
        """The tariff line for this (product, action), resolved once per page.

        The charge depends on the product and the action, not on the amount or
        the dates — so a page of transactions shares very few lines, and looking
        one up per row was the last query still scaling with the row count.
        """
        cache = getattr(self, "_line_cache", None)
        if cache is None:
            cache = self._line_cache = {}
        key = (obj.product_id, obj.action)
        if key not in cache:
            cache[key] = (TradeTariff.resolve(obj.product, obj.action)
                          if obj.product_id else None)
        return cache[key]

    def get_commission_quote(self, obj):
        quote = obj.quote_commission(tariff_line=self._tariff_line(obj))
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

    def validate_action(self, value):
        """Only the desk's six actions may be recorded on a NEW transaction.

        Rows written before the list existed keep whatever they hold — the
        register says what happened — so this validates what is being written,
        not what is already there.
        """
        action = (value or "").strip().upper()
        if not action:
            return refs.ACTION_ISSUANCE
        if action not in refs.ACTIONS:
            # An unchanged legacy value on an existing row is left alone; only a
            # genuinely new value has to be one of the six.
            if self.instance is not None and action == (self.instance.action or "").upper():
                return self.instance.action
            allowed = ", ".join(refs.ACTIONS)
            raise serializers.ValidationError(f"Action must be one of: {allowed}.")
        return action

    def validate(self, attrs):
        """An action on an existing instrument must say which one."""
        action = attrs.get("action", getattr(self.instance, "action", "")) or ""
        parent = attrs.get("parent_ref", getattr(self.instance, "parent_ref", ""))
        if action.upper() in refs.ACTIONS_ON_EXISTING and not parent:
            raise serializers.ValidationError({
                "parent_ref": (
                    f"{action.title()} acts on an instrument that already exists — "
                    "give the original guarantee/LC reference."
                )
            })
        return attrs
