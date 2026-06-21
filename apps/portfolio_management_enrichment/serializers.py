from rest_framework import serializers
from .models import (
    CustomerEnrichment, RmTarget, CustomerAllocationBase, RmAllocationList,
    TeamLeaderMovementApprovers, CustomerTransferHistory,
)


class CustomerEnrichmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerEnrichment
        fields = "__all__"


class RmTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = RmTarget
        fields = "__all__"


class CustomerAllocationBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAllocationBase
        fields = "__all__"


class RmAllocationListSerializer(serializers.ModelSerializer):
    class Meta:
        model = RmAllocationList
        fields = "__all__"


class TeamLeaderMovementApproversSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamLeaderMovementApprovers
        fields = "__all__"


class CustomerTransferHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerTransferHistory
        fields = "__all__"
