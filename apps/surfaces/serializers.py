from rest_framework import serializers
from .models import Surface


class SurfaceSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    panel_count = serializers.SerializerMethodField()

    class Meta:
        model = Surface
        fields = ["id", "title", "prompt", "spec", "visibility", "note",
                  "created_by", "created_by_name", "panel_count",
                  "created_at", "updated_at"]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def get_created_by_name(self, obj):
        u = obj.created_by
        if not u:
            return None
        return (u.get_full_name() or u.username).strip()

    def get_panel_count(self, obj):
        return len((obj.spec or {}).get("panels", []))


class GenerateRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=2000)


class RefineRequestSerializer(serializers.Serializer):
    """An adjustment to a surface that already exists.

    Separate from ``GenerateRequestSerializer`` because the two are not the
    same act: generating starts from nothing, refining starts from a layout
    somebody is already looking at and must keep everything they did not
    mention.
    """

    instruction = serializers.CharField(max_length=2000)
