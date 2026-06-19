from rest_framework import serializers
from .models import ExcoInitiative


class ExcoInitiativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExcoInitiative
        fields = "__all__"
