"""Validation for the commercial pipeline.

The rules here are the ones the spreadsheet could not enforce, and each exists
because the file actually breaks it somewhere.

Three of them came out of the walkthrough with the Commercial RM rather than
out of the file, and all three are deliberately asymmetric between a new line
and an edit:

* a **comment carries at least** ``MIN_COMMENT_WORDS`` **words**. The
  requirements sheet asks for this "at each workflow stage"; it is checked on a
  new line, and on any edit that touches the comment or moves the stage. It is
  NOT checked on an edit that leaves both alone, because every one of the
  imported rows would otherwise be frozen until somebody wrote it a sentence,
  and an RM who cannot correct an amount goes back to the spreadsheet.
* an **Insurance Pipeline line says VIC or non-VIC**. Required on a new line,
  and it cannot be blanked on an existing one. Rows that predate the field
  stay blank until the RM next opens them, which is the only honest way to add
  a required field to a table that already holds rows.
* a **retired stage cannot be chosen**. ``charge_dispatch`` is the sheet's
  "Remove-Charge Dispatch to Customer". It is still accepted when a row
  already carries it and is not being moved - otherwise removing a choice
  would quietly make those rows unsaveable.
"""

from rest_framework import serializers

from .models import PipelineEntry


class PipelineEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    broad_stage_display = serializers.CharField(source="get_broad_stage_display",
                                                read_only=True)
    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    insurance_type_display = serializers.CharField(
        source="get_insurance_type_display", read_only=True)
    deposit_product_display = serializers.CharField(
        source="get_deposit_product_display", read_only=True)
    owner_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PipelineEntry
        fields = [
            "id", "kind", "kind_display",
            "sales_code", "rm_name", "owner_name", "branch", "segment",
            "customer_name",
            "amount", "amount_to_disburse", "revenue",
            "product", "deposit_product", "deposit_product_display",
            "insurance_type", "insurance_type_display", "account_no",
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
            errors["deposit_product"] = (
                "Which kind of deposit? CASA, fixed deposit, cash margin or "
                "escrow.")

        if kind == PipelineEntry.KIND_LIABILITY:
            if not (get("account_no") or "").strip():
                # 'New to bank' and 'tba' are both in the file and are
                # legitimate answers - the field is required, its CONTENT
                # is not constrained.
                errors["account_no"] = (
                    "Account number — or 'New to bank' if there is not "
                    "one yet.")

            # VIC or non-VIC. Demanded of a new line; on an existing one
            # only that it is not blanked, so the rows that predate this
            # field stay editable until somebody fills them in.
            insurance = get("insurance_type")
            if self.instance is None and not insurance:
                errors["insurance_type"] = (
                    "VIC or non-VIC? VIC is all Britam products; non-VIC "
                    "is every other cover.")
            elif "insurance_type" in data and not data.get("insurance_type"):
                errors["insurance_type"] = (
                    "Leave this set — the report splits VIC from non-VIC.")

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

        # A retired choice is refused on a new line, and on an edit that
        # moves onto it. A row already sitting on one may still be saved.
        def is_a_change(field, value):
            if self.instance is None:
                return True
            return field in data and value != getattr(self.instance, field, None)

        if (broad in PipelineEntry.RETIRED_BROAD_STAGES
                and is_a_change("broad_stage", broad)):
            label = dict(PipelineEntry.BROAD_STAGE).get(broad, broad)
            errors["broad_stage"] = (
                f"“{label}” is no longer used. Pick Disbursement instead, and "
                f"the unit that is holding it.")
        if stage in PipelineEntry.RETIRED_STAGES and is_a_change("stage", stage):
            label = dict(PipelineEntry.STAGE).get(stage, stage)
            errors["stage"] = (
                f"“{label}” is no longer used — pick the unit that holds it.")

        # The comment minimum. Checked when the line is new, and when this
        # save touches the comment or moves the stage — which is what the
        # requirements sheet means by "at each workflow stage".
        # "in data" is not enough: the form posts every field it is holding,
        # so an RM correcting an amount re-sends the comment it loaded. What
        # matters is whether this save CHANGES the comment or moves the stage.
        touches_the_story = any(is_a_change(f, get(f))
                                for f in ("comments", "broad_stage", "stage"))
        if self.instance is None or touches_the_story:
            words = len((get("comments") or "").split())
            least = PipelineEntry.MIN_COMMENT_WORDS
            if words < least:
                errors["comments"] = (
                    f"Say what has actually happened — at least {least} words, "
                    f"and this has {words}. What was done, where it stands and "
                    f"what it is waiting on, so nobody has to come back and ask.")

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
