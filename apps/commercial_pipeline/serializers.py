"""Validation for the commercial pipeline.

The rules here are the ones the spreadsheet could not enforce, and each exists
because the file actually breaks it somewhere.
"""

from rest_framework import serializers

from .models import PipelineEntry


class PipelineEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    broad_stage_display = serializers.CharField(source="get_broad_stage_display",
                                                read_only=True)
    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    owner_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PipelineEntry
        fields = [
            "id", "kind", "kind_display",
            "sales_code", "rm_name", "owner_name", "branch", "segment",
            "customer_name",
            "amount", "amount_to_disburse", "revenue",
            "product", "deposit_product", "account_no",
            "broad_stage", "broad_stage_display", "stage", "stage_display",
            "expected_date", "comments", "is_active",
            "updated_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "segment"]

    def get_owner_name(self, obj):
        return obj.rm_name or obj.sales_code or "—"

    def get_updated_by_name(self, obj):
        u = obj.updated_by
        return (u.get_full_name() or u.username).strip() if u else ""

    def validate_customer_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError(
                "Give the customer's name — this is what the Team Leader reads.")
        return value

    def validate(self, data):
        # On a PATCH only some fields arrive; fall back to what is stored so a
        # partial update is checked against the whole row, not the fragment.
        def get(field):
            if field in data:
                return data[field]
            return getattr(self.instance, field, None) if self.instance else None

        kind = get("kind")
        if not kind:
            raise serializers.ValidationError(
                {"kind": "Say which pipeline this belongs to."})

        errors = {}

        # An amount is the point of every one of these rows.
        amount = get("amount")
        if amount is None:
            errors["amount"] = "How much? Every line in this pipeline carries an amount."
        elif amount < 0:
            errors["amount"] = "An amount cannot be negative."

        if kind == PipelineEntry.KIND_ASSET:
            to_disburse = get("amount_to_disburse")
            if to_disburse is not None and amount is not None and to_disburse > amount:
                # The file has 10m requested against 6m to disburse; the other
                # way round is a typo, not a deal.
                errors["amount_to_disburse"] = (
                    "More cannot be disbursed than was requested.")
            if not (get("product") or "").strip():
                errors["product"] = "Which product? Free text — spell it how you say it."

        if kind == PipelineEntry.KIND_DEPOSIT and not get("deposit_product"):
            errors["deposit_product"] = "CASA or FD."

        if kind == PipelineEntry.KIND_LIABILITY and not (get("account_no") or "").strip():
            # 'New to bank' and 'tba' are both in the file and are legitimate
            # answers - the field is required, its CONTENT is not constrained.
            errors["account_no"] = (
                "Account number — or 'New to bank' if there is not one yet.")

        # The two stage columns must agree. In the spreadsheet they routinely
        # do not: 'Credit Risk' appears in the broad column, where it is not a
        # broad stage at all.
        broad, stage = get("broad_stage"), get("stage")
        if stage and broad:
            allowed = PipelineEntry.STAGES_UNDER_BROAD.get(broad, set())
            if stage not in allowed:
                label = dict(PipelineEntry.STAGE).get(stage, stage)
                broad_label = dict(PipelineEntry.BROAD_STAGE).get(broad, broad)
                errors["stage"] = (
                    f"“{label}” does not sit under “{broad_label}”. Pick the broad "
                    f"stage that matches, or a stage that belongs to this one.")
        if stage and not broad:
            errors["broad_stage"] = "Set the broad stage too — the reports group on it."

        if errors:
            raise serializers.ValidationError(errors)
        return data


class PipelineSummarySerializer(serializers.Serializer):
    """Shape of the summary endpoint. Declared so the schema is honest."""

    kind = serializers.CharField()
    kind_display = serializers.CharField()
    count = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_to_disburse = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_revenue = serializers.DecimalField(max_digits=20, decimal_places=2)
