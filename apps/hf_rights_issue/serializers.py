from rest_framework import serializers
from .models import RightsIssueApplication


class RightsIssueApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RightsIssueApplication
        fields = "__all__"
