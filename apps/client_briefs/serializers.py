from rest_framework import serializers

from .models import ClientBrief


class ClientBriefSerializer(serializers.ModelSerializer):
    rm_name = serializers.SerializerMethodField()
    display_subject = serializers.CharField(read_only=True)

    class Meta:
        model = ClientBrief
        fields = "__all__"
        read_only_fields = ["rm", "created_at", "updated_at"]

    def get_rm_name(self, obj):
        if obj.rm:
            full = obj.rm.get_full_name().strip()
            return full or obj.rm.username
        return None

    def validate_opportunities(self, value):
        """Opportunities must be a list of {title, body} objects."""
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Expected a list of opportunities.")
        cleaned = []
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    f"Opportunity #{i + 1} must be an object with 'title' and 'body'."
                )
            cleaned.append({
                "title": str(item.get("title", "")).strip(),
                "body": str(item.get("body", "")).strip(),
            })
        return cleaned
