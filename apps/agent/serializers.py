from rest_framework import serializers
from .models import AgentConversation


class AgentConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentConversation
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]
