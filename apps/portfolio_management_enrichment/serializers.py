from rest_framework import serializers
from .models import CustomerEnrichment, RmTarget


class CustomerEnrichmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerEnrichment
        fields = "__all__"


class RmTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = RmTarget
        fields = "__all__"
