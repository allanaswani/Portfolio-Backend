from rest_framework import serializers

from .models import StrategyTarget


class StrategyTargetSerializer(serializers.ModelSerializer):
    metric_display     = serializers.CharField(source="get_metric_display", read_only=True)
    scope_type_display = serializers.CharField(source="get_scope_type_display", read_only=True)
    created_by_name    = serializers.SerializerMethodField()

    class Meta:
        model = StrategyTarget
        fields = [
            "id", "metric", "metric_display",
            "scope_type", "scope_type_display", "scope_value",
            "period_type", "year", "quarter", "month",
            "target_value", "note",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return None
        u = obj.created_by
        return (u.get_full_name() or "").strip() or u.username

    def validate(self, data):
        period = data.get("period_type", getattr(self.instance, "period_type", "annual"))
        quarter = data.get("quarter", getattr(self.instance, "quarter", None))
        month = data.get("month", getattr(self.instance, "month", None))
        if period == StrategyTarget.Period.QUARTERLY and not quarter:
            raise serializers.ValidationError({"quarter": "Quarter (1–4) is required for a quarterly target."})
        if period == StrategyTarget.Period.MONTHLY and not month:
            raise serializers.ValidationError({"month": "Month (1–12) is required for a monthly target."})
        if quarter is not None and not (1 <= int(quarter) <= 4):
            raise serializers.ValidationError({"quarter": "Quarter must be between 1 and 4."})
        if month is not None and not (1 <= int(month) <= 12):
            raise serializers.ValidationError({"month": "Month must be between 1 and 12."})
        return data


class ExecBriefMetricSerializer(serializers.Serializer):
    label  = serializers.CharField()
    actual = serializers.FloatField(required=False, allow_null=True)
    target = serializers.FloatField(required=False, allow_null=True)
    growth = serializers.FloatField(required=False, allow_null=True)  # % change vs last period
    unit   = serializers.ChoiceField(choices=["currency", "number", "percent"], default="number")


class ExecBriefRequestSerializer(serializers.Serializer):
    section      = serializers.CharField()
    period_label = serializers.CharField(required=False, allow_blank=True, default="")
    metrics      = ExecBriefMetricSerializer(many=True)
