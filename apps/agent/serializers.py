from rest_framework import serializers
from .models import AgentConversation


class AgentConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentConversation
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]


class AgentChatRequestSerializer(serializers.Serializer):
    """Body for POST /chat/<conversation_id>/ — drives the Swagger message box."""
    message = serializers.CharField(help_text="Your message to the assistant.")


class AgentChatResponseSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="The assistant's grounded reply.")
    conversation_id = serializers.IntegerField()
    configured = serializers.BooleanField(
        help_text="False if ANTHROPIC_API_KEY is not set on the backend."
    )
