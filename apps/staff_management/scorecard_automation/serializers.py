from rest_framework import serializers
from .models import (
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance,
)


class ScKpiSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScKpi
        fields = "__all__"


class ScRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScRole
        fields = "__all__"


class ScRoleKpiMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScRoleKpiMapping
        fields = "__all__"


class ScEmployeePerformanceActualSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScEmployeePerformanceActual
        fields = "__all__"


class ScEmployeeMonthlyPerformanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScEmployeeMonthlyPerformance
        fields = "__all__"


class RunScorecardSerializer(serializers.Serializer):
    """Payload for triggering a monthly scorecard run."""
    eom_date = serializers.DateField()
    scope = serializers.ChoiceField(
        choices=["all", "employee", "department", "role"], default="all"
    )
    sales_code = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    role_code = serializers.CharField(required=False, allow_blank=True)
