from rest_framework import serializers
from .models import (
    ExcoInitiative, StrategicExcoOwner, StrategicThrust,
    StrategicInitiative, StrategicMilestone,
)


class ExcoInitiativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExcoInitiative
        fields = "__all__"


class StrategicExcoOwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = StrategicExcoOwner
        fields = "__all__"


class StrategicThrustSerializer(serializers.ModelSerializer):
    class Meta:
        model = StrategicThrust
        fields = "__all__"


class StrategicInitiativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StrategicInitiative
        fields = "__all__"


class StrategicMilestoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = StrategicMilestone
        fields = "__all__"
