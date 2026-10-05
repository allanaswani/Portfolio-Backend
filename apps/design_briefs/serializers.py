"""Serialisers for the design board.

The list serialiser is deliberately lean and carries every field the office
screen needs, because that screen refreshes on a timer all day: anything it
has to fetch per row would be a query per row, on a wall display nobody is
watching the network tab of.

Writes never touch ``status``. Each transition has its own endpoint, through
``workflow`` — see that module's docstring.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import BriefEvent, DesignBrief

User = get_user_model()


def _person(user, fallback=""):
    """A name worth showing on a screen, or the snapshot we kept."""
    if user is None:
        return fallback or ""
    return (user.get_full_name() or user.username or fallback or "")


class PersonSerializer(serializers.ModelSerializer):
    """A user as the board shows them — for designer dropdowns."""

    name = serializers.SerializerMethodField()
    initials = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "name", "email", "initials"]

    def get_name(self, obj):
        return _person(obj)

    def get_initials(self, obj):
        name = _person(obj).strip()
        parts = [p for p in name.replace(".", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class BriefEventSerializer(serializers.ModelSerializer):
    actor_display = serializers.SerializerMethodField()
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = BriefEvent
        fields = [
            "id", "kind", "kind_display", "actor", "actor_display", "note",
            "from_status", "to_status", "at",
        ]

    def get_actor_display(self, obj):
        return _person(obj.actor, obj.actor_name)


class DesignBriefListSerializer(serializers.ModelSerializer):
    """One row of the board. Everything the screen draws, in one query."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    item_type_display = serializers.CharField(source="get_item_type_display", read_only=True)
    raised_by_display = serializers.SerializerMethodField()
    designer_display = serializers.SerializerMethodField()
    designer_initials = serializers.SerializerMethodField()
    days_to_release = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    is_closed = serializers.BooleanField(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)
    was_reworked = serializers.BooleanField(read_only=True)

    class Meta:
        model = DesignBrief
        fields = [
            "id", "reference", "design_item", "item_type", "item_type_display",
            "department", "addressed_to",
            "raised_by", "raised_by_display",
            "assigned_designer", "designer_display", "designer_initials",
            "priority", "priority_display",
            "status", "status_display",
            "release_date", "days_to_release", "is_overdue",
            "rework_count", "was_reworked",
            "satisfaction",
            "is_closed", "is_archived", "archived_at",
            "created_at", "updated_at",
        ]

    def get_raised_by_display(self, obj):
        return _person(obj.raised_by, obj.raised_by_name)

    def get_designer_display(self, obj):
        return _person(obj.assigned_designer) or "Unassigned"

    def get_designer_initials(self, obj):
        if obj.assigned_designer is None:
            return "—"
        return PersonSerializer().get_initials(obj.assigned_designer)


class DesignBriefDetailSerializer(DesignBriefListSerializer):
    """The whole brief, with its timeline."""

    events = BriefEventSerializer(many=True, read_only=True)
    assigned_by_display = serializers.SerializerMethodField()
    approved_by_display = serializers.SerializerMethodField()
    can = serializers.SerializerMethodField()

    class Meta(DesignBriefListSerializer.Meta):
        fields = DesignBriefListSerializer.Meta.fields + [
            "brief",
            "assigned_by", "assigned_by_display", "assigned_at",
            "started_at", "submitted_at",
            "last_rework_at", "last_rework_reason",
            "approved_by", "approved_by_display", "approved_at",
            "closing_note",
            "events", "can",
        ]

    def get_assigned_by_display(self, obj):
        return _person(obj.assigned_by)

    def get_approved_by_display(self, obj):
        return _person(obj.approved_by)

    def get_can(self, obj):
        """What the signed-in user may do with this brief.

        Sent with the brief so the UI can hide buttons it would only be told
        off for pressing. It is a convenience, not the control — every one of
        these is enforced again in the view.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None:
            return {}
        from . import rbac

        return {
            "edit": rbac.can_edit_brief(user, obj),
            "assign": rbac.can_assign(user) and not obj.is_closed,
            "work": rbac.can_work(user, obj) and not obj.is_closed,
            "judge": rbac.can_judge(user, obj)
                     and obj.status == DesignBrief.STATUS_SUBMITTED,
            "cancel": rbac.can_cancel(user, obj) and not obj.is_closed,
            "reopen": rbac.is_admin(user) and obj.is_closed,
            "note": rbac.can_view(user, obj),
        }


class DesignBriefCreateSerializer(serializers.ModelSerializer):
    """Raising a brief.

    ``status``, the designer and every timestamp are absent on purpose: a new
    brief is always ``new`` and unassigned, and allowing a requester to post a
    status would put rows on the board that no step accounts for.
    """

    class Meta:
        model = DesignBrief
        fields = [
            "design_item", "item_type", "brief", "department", "addressed_to",
            "priority", "release_date",
        ]

    def validate_design_item(self, value):
        value = (value or "").strip()
        if len(value) < 3:
            raise serializers.ValidationError(
                "Say what is being requested — at least a few words.")
        return value

    def validate_department(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError(
                "Which department is this brief from?")
        return value

    def validate_addressed_to(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError(
                "Who is the brief to? A person, team or audience.")
        return value

    def validate_release_date(self, value):
        # A date in the past is allowed on purpose: briefs get entered late,
        # and refusing the real date would make people enter a false one. The
        # board shows it as overdue, which is the truth.
        return value


class DesignBriefUpdateSerializer(serializers.ModelSerializer):
    """Editing the brief itself — never its status or its designer.

    Who the work is allocated to changes through the assign endpoint, so that
    it is recorded as a step with an actor against it.
    """

    class Meta:
        model = DesignBrief
        fields = [
            "design_item", "item_type", "brief", "department", "addressed_to",
            "priority", "release_date",
        ]


class AssignSerializer(serializers.Serializer):
    designer = serializers.IntegerField(help_text="User id of the designer.")
    note = serializers.CharField(required=False, allow_blank=True)

    def validate_designer(self, value):
        if not User.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError("No such active user.")
        return value


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=False)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False)


class ApproveSerializer(serializers.Serializer):
    satisfaction = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=5)
    note = serializers.CharField(required=False, allow_blank=True)
