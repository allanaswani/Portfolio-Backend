from rest_framework import serializers

from . import ptp
from .models import Collection, PromiseToPay


class CollectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Collection
        fields = "__all__"


class PromiseToPaySerializer(serializers.ModelSerializer):
    """A promise, in and out.

    The four derived fields are READ ONLY, and that is the whole design: the
    kept rate is what a collections desk is judged on, so a collector cannot
    mark their own promise kept. ``status``, ``amount_paid`` and
    ``settled_on`` come from the repayments feed - see
    ``apps.hf_collections.ptp`` - and are recomputed, not submitted.
    """

    status_display = serializers.CharField(source="get_status_display",
                                           read_only=True)
    shortfall = serializers.DecimalField(max_digits=18, decimal_places=2,
                                         read_only=True)

    class Meta:
        model = PromiseToPay
        fields = "__all__"
        read_only_fields = ("status", "amount_paid", "settled_on", "source",
                            "created_at", "updated_at")

    def validate(self, data):
        errors = {}

        def get(field):
            if field in data:
                return data.get(field)
            return getattr(self.instance, field, None)

        # Without the loan account there is nothing to settle the promise
        # against, so it could never be anything but "open" - which is worse
        # than refusing it, because it would sit in the report for ever.
        if not get("loan_account_no"):
            errors["loan_account_no"] = (
                "Which loan account? The promise is settled by looking for "
                "the money on that account, so without it there is nothing "
                "to check.")

        amount = get("promised_amount")
        if amount is None or amount <= 0:
            errors["promised_amount"] = (
                "How much did they promise? A promise of nothing is a call, "
                "not a promise.")

        if not get("promised_date"):
            errors["promised_date"] = (
                "By when? Without a date the promise can never come due.")

        made_on, due = get("promised_on"), get("promised_date")
        if made_on and due and due < made_on:
            errors["promised_date"] = (
                "That date is before the promise was taken. A promise is a "
                "commitment about the future.")

        if errors:
            raise serializers.ValidationError(errors)
        return data

    def create(self, validated):
        validated["source"] = PromiseToPay.SOURCE_DIRECT
        promise = super().create(validated)
        # Settled on the way in: a promise recorded late, for a date that has
        # already passed, is judged immediately rather than sitting open
        # until the nightly run.
        ptp.settle(promise)
        promise.save(update_fields=["status", "amount_paid", "settled_on"])
        return promise

    def update(self, instance, validated):
        promise = super().update(instance, validated)
        ptp.settle(promise)
        promise.save(update_fields=["status", "amount_paid", "settled_on"])
        return promise
