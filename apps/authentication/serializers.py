"""
Admin user-management serializers.

Powers a clean Users admin screen (create users, assign roles, reset passwords)
so administrators no longer depend on the Django admin UI.
"""

import secrets
import string

from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from core.roles import ALL_ROLE_DESCRIPTIONS, tier_for_groups
from core.signals import muted_profile_signals


def _generate_password(length: int = 12) -> str:
    """A reasonably strong, human-shareable random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%*?"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _apply_profile(user, sales_code, branch, segment):
    """Create/update the user's Profile with the given fields (only those given)."""
    from apps.portfolio.models import Profile

    profile, _ = Profile.objects.get_or_create(user=user)
    if sales_code is not None:
        profile.sales_code = sales_code
    if branch is not None:
        profile.branch = branch
    if segment is not None:
        profile.segment = segment
    profile.save()
    return profile


class RoleSerializer(serializers.Serializer):
    """A selectable role (Django Group) for the admin Users screen dropdown."""

    name = serializers.CharField()
    description = serializers.SerializerMethodField()
    tier = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    def get_description(self, obj):
        return ALL_ROLE_DESCRIPTIONS.get(obj.name, "")

    def get_tier(self, obj):
        return tier_for_groups({obj.name})

    def get_member_count(self, obj):
        return obj.user_set.count()


class AdminUserSerializer(serializers.ModelSerializer):
    """Read/write serializer for managing users.

    - ``groups`` is read & written by role name (the migration-safe contract).
    - ``password`` is write-only & optional; if omitted on create, a strong one
      is generated and returned ONCE via ``generated_password``.
    - Profile fields (sales_code/branch/segment) are flattened to the top level.
    """

    groups = serializers.SlugRelatedField(
        slug_field="name", queryset=Group.objects.all(), many=True, required=False
    )
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    sales_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    segment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    role_tier = serializers.SerializerMethodField()
    generated_password = serializers.CharField(read_only=True, required=False)

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "first_name", "last_name",
            "is_active", "is_staff", "is_superuser", "groups",
            "sales_code", "branch", "segment",
            "role_tier", "password", "generated_password",
            "date_joined", "last_login",
        )
        read_only_fields = ("id", "role_tier", "date_joined", "last_login")

    def get_role_tier(self, obj):
        return tier_for_groups(obj.groups.values_list("name", flat=True))

    # ---- read: flatten profile fields ------------------------------------
    def to_representation(self, instance):
        data = super().to_representation(instance)
        profile = getattr(instance, "profile", None)
        data["sales_code"] = getattr(profile, "sales_code", None)
        data["branch"] = getattr(profile, "branch", None)
        data["segment"] = getattr(profile, "segment", None)
        return data

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_username(self, value):
        qs = User.objects.filter(username__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    # ---- create ----------------------------------------------------------
    def create(self, validated_data):
        groups = validated_data.pop("groups", [])
        sales_code = validated_data.pop("sales_code", None)
        branch = validated_data.pop("branch", None)
        segment = validated_data.pop("segment", None)
        raw_password = validated_data.pop("password", None)

        generated = None
        if not raw_password:
            raw_password = _generate_password()
            generated = raw_password

        # Mute the welcome-email/auto-profile signal — we manage both ourselves.
        with muted_profile_signals():
            user = User(**validated_data)
            user.set_password(raw_password)
            user.save()
            user.groups.set(groups)
            _apply_profile(user, sales_code, branch, segment)

        if generated:
            # Surfaced ONCE to the admin so they can share it.
            user.generated_password = generated
        return user

    # ---- update ----------------------------------------------------------
    def update(self, instance, validated_data):
        groups = validated_data.pop("groups", None)
        sales_code = validated_data.pop("sales_code", None)
        branch = validated_data.pop("branch", None)
        segment = validated_data.pop("segment", None)
        # Password changes go through the dedicated set-password endpoint.
        validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if groups is not None:
            instance.groups.set(groups)
        if any(v is not None for v in (sales_code, branch, segment)):
            _apply_profile(instance, sales_code, branch, segment)
        return instance


class SetPasswordSerializer(serializers.Serializer):
    """Admin-initiated password reset for a user."""

    password = serializers.CharField(write_only=True, required=False, allow_blank=False)

    def validate_password(self, value):
        validate_password(value)
        return value

    def save(self, user):
        raw = self.validated_data.get("password") or _generate_password()
        user.set_password(raw)
        user.save(update_fields=["password"])
        return raw
