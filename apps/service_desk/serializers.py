"""What the API sends and accepts.

The list serializer is deliberately lighter than the detail one: the queue is
the screen people leave open, and sending every comment and event with every row
would make the page that has to stay fast the slowest one.
"""

from rest_framework import serializers

from .models import (
    DeskRecipient, DeskSettings, Holiday, Ticket, TicketCategory, TicketComment,
    TicketEvent,
)
from .worktime import describe


def _person(user):
    if user is None:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "name": user.get_full_name() or user.username,
        "email": user.email or "",
    }


class TicketCategorySerializer(serializers.ModelSerializer):
    ticket_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = TicketCategory
        fields = [
            "id", "name", "slug", "description", "queue",
            "response_minutes", "resolution_minutes", "is_active", "ticket_count",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        merged = {**(self.instance.__dict__ if self.instance else {}), **attrs}
        response = merged.get("response_minutes") or 0
        resolution = merged.get("resolution_minutes") or 0
        if response and resolution and response > resolution:
            raise serializers.ValidationError(
                "The response target cannot be later than the resolution target — "
                "a ticket would breach its first reply after it was already due to "
                "be finished."
            )
        return attrs


class DeskRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeskRecipient
        fields = ["id", "email", "name", "queue", "escalations", "is_active"]

    def validate(self, attrs):
        """Somebody subscribed to nothing is on the list and never written to.

        A field left out of the payload means "leave it as it is" on an edit,
        and "use the model default" on a create — both of which are True here.
        Reading an absent field as False would reject every request that simply
        did not mention it.
        """
        def current(field):
            if field in attrs:
                return attrs[field]
            if self.instance is not None:
                return getattr(self.instance, field)
            return DeskRecipient._meta.get_field(field).default

        if not (current("queue") or current("escalations")):
            raise serializers.ValidationError(
                "Choose the queue, escalations, or both — otherwise this "
                "address is on the list but will never be emailed."
            )
        return attrs


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "day", "name"]


class DeskSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeskSettings
        fields = [
            "opens_minute", "closes_minute", "workdays",
            "auto_close_after_days", "reopen_window_days",
            "notify_requester", "notify_assignee",
        ]

    def validate(self, attrs):
        merged = {**(self.instance.__dict__ if self.instance else {}), **attrs}
        if merged.get("opens_minute", 0) >= merged.get("closes_minute", 0):
            raise serializers.ValidationError(
                "The desk must close after it opens, or no time is working time "
                "and every SLA target becomes unreachable."
            )
        return attrs


class TicketEventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    gap = serializers.SerializerMethodField()
    label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = TicketEvent
        fields = [
            "id", "kind", "label", "actor", "actor_label", "from_status",
            "to_status", "note", "at", "gap",
            "seconds_since_previous", "working_seconds_since_previous",
        ]

    def get_actor(self, obj):
        return _person(obj.actor)

    def get_gap(self, obj):
        """How long this step took, in the desk's working time."""
        return describe(obj.working_seconds_since_previous)


class TicketCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = TicketComment
        fields = ["id", "author", "body", "is_internal", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

    def get_author(self, obj):
        return _person(obj.author)


class TicketListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", default="", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    raised_by = serializers.SerializerMethodField()
    assigned_to = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    sla = serializers.SerializerMethodField()
    comment_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Ticket
        fields = [
            "id", "reference", "subject", "status", "status_label",
            "priority", "priority_label", "category", "category_name",
            "raised_by", "on_behalf_of", "assigned_to",
            "created_at", "first_response_at", "resolved_at", "closed_at",
            "response_due_at", "resolution_due_at",
            "reopened_count", "confirmed_by_requester",
            "age", "sla", "comment_count",
        ]

    def get_raised_by(self, obj):
        return _person(obj.raised_by) or (
            {"name": obj.on_behalf_of, "username": "", "email": obj.requester_email}
            if obj.on_behalf_of else None
        )

    def get_assigned_to(self, obj):
        return _person(obj.assigned_to)

    def get_age(self, obj):
        seconds = obj.working_seconds_open()
        return {"seconds": seconds, "label": describe(seconds)}

    def get_sla(self, obj):
        """Three states, never two. ``None`` means still in time — rendering
        that as 'met' would call a ticket a success before it is finished."""
        return {
            "response_breached": obj.response_breached,
            "resolution_breached": obj.resolution_breached,
            "response_due_at": obj.response_due_at,
            "resolution_due_at": obj.resolution_due_at,
        }


class TicketDetailSerializer(TicketListSerializer):
    events = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    time_breakdown = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + [
            "body", "requester_email", "requester_department", "requester_branch",
            "resolution_note", "satisfaction", "assigned_at", "started_at",
            "on_hold_seconds", "last_reopened_at",
            "events", "comments", "permissions", "time_breakdown",
        ]

    def get_events(self, obj):
        return TicketEventSerializer(obj.events.all(), many=True).data

    def get_comments(self, obj):
        from .rbac import is_handler

        rows = obj.comments.all()
        # Internal notes are dropped for a requester rather than sent and
        # hidden — a field the browser can see is a field the browser can show.
        if not is_handler(self.context.get("request").user if self.context.get("request") else None):
            rows = [row for row in rows if not row.is_internal]
        return TicketCommentSerializer(rows, many=True).data

    def get_permissions(self, obj):
        """What this viewer may do, so the UI offers exactly those buttons."""
        from . import rbac

        request = self.context.get("request")
        user = request.user if request else None
        return {
            "comment": rbac.can_comment(user, obj),
            "resolve": rbac.can_resolve(user, obj),
            "confirm": rbac.can_confirm(user, obj) and obj.status == Ticket.STATUS_RESOLVED,
            "reopen": rbac.can_view(user, obj) and obj.can_reopen(),
            "assign": rbac.can_assign(user, obj),
            "take": rbac.is_handler(user),
            "assign_others": rbac.can_assign_to_others(user, obj),
            "cancel": rbac.can_cancel(user, obj) and obj.status not in Ticket.CLOSED_STATUSES,
            "set_status": rbac.is_handler(user),
            "internal_note": rbac.is_handler(user),
        }

    def get_time_breakdown(self, obj):
        """Where the time actually went. The answer to 'it has been weeks'."""
        return {
            "to_first_response": describe(obj.working_seconds_to_response()),
            "open_total": describe(obj.working_seconds_open()),
            "waiting_on_requester": describe(obj.on_hold_seconds) if obj.on_hold_seconds else None,
            "steps": [
                {
                    "label": event.get_kind_display(),
                    "at": event.at,
                    "gap": describe(event.working_seconds_since_previous),
                    "actor": event.actor_label,
                }
                for event in obj.events.all()
            ],
        }


class TicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = [
            "subject", "body", "category", "priority",
            "on_behalf_of", "requester_email",
            "requester_department", "requester_branch",
        ]

    def validate_subject(self, value):
        value = (value or "").strip()
        if len(value) < 5:
            raise serializers.ValidationError(
                "Give it a subject somebody can recognise in a list — "
                "at least a few words."
            )
        return value

    def validate(self, attrs):
        if attrs.get("on_behalf_of") and not attrs.get("requester_email"):
            raise serializers.ValidationError({
                "requester_email":
                    "Logging this for somebody else needs their email address, "
                    "or they cannot be told when it is answered — which is the "
                    "problem this desk exists to fix."
            })
        return attrs
