"""Serializers for the Referral module.

All validation that matters lives here (server-side): Kenyan phone normalisation,
national-ID sanity, and the soft staff-register lookup. Allocation and status
fields are read-only on this serializer — they are only ever mutated through the
dedicated, permission-checked action endpoints (allocate / status), so a capturer
cannot self-allocate a referral by PATCHing it.
"""

import re

from rest_framework import serializers

from .models import Referral
from .rbac import is_postbank
from .staff import verify_staff

# Kenyan MSISDN: national significant number is 9 digits starting 7 (Safaricom/Airtel/
# Telkom) or 1 (newer ranges, e.g. 011/010). We accept the common written forms
# (+254…, 254…, 0…, or bare) and normalise everything to +254XXXXXXXXX.
_PHONE_RE = re.compile(r"^(?:\+?254|0)?([17]\d{8})$")
_NATIONAL_ID_RE = re.compile(r"^\d{6,9}$")


def normalize_kenyan_phone(raw: str) -> str:
    """Validate and canonicalise a Kenyan phone number to ``+254XXXXXXXXX``."""
    compact = re.sub(r"[\s\-()]", "", raw or "")
    match = _PHONE_RE.match(compact)
    if not match:
        raise serializers.ValidationError(
            "Enter a valid Kenyan phone number, e.g. 0712345678 or +254712345678."
        )
    return "+254" + match.group(1)


class ReferralSerializer(serializers.ModelSerializer):
    # Human-friendly, read-only projections for the UI.
    created_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    allocated_by_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    referrer_type_display = serializers.CharField(
        source="get_referrer_type_display", read_only=True)
    # Live sales code / branch of the assignee, so the RM working the referral (and
    # anyone reviewing it) can see which code it sits under even before allocation
    # snapshots one.
    assigned_to_sales_code = serializers.SerializerMethodField()
    assigned_to_branch = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = "__all__"
        # These are set by the server (capture context) or only by the dedicated
        # allocate/status endpoints — never trust them from the request body.
        read_only_fields = [
            "referral_ref",
            "created_by",
            "staff_verified",
            "verified_staff_name",
            "is_possible_duplicate",
            "status",
            "assigned_to",
            "allocated_by",
            "allocated_at",
            "assigned_sales_code",
            "contacted_at",
            "converted_at",
        ]

    # ── Field validation ──────────────────────────────────────────────────────
    def validate_phone(self, value):
        return normalize_kenyan_phone(value)

    def validate_national_id(self, value):
        cleaned = (value or "").strip()
        if not _NATIONAL_ID_RE.match(cleaned):
            raise serializers.ValidationError(
                "National ID must be 6–9 digits (numbers only)."
            )
        return cleaned

    def validate(self, attrs):
        """Who the referrer is, by institution.

        * HFCB staff: the PF number is required, as before.
        * Postbank: the referrer's Postbank sales code and name are required
          and the PF number is not asked for. A Postbank team member's own
          referrals are always Postbank's, whatever the form sent.
        """
        request = self.context.get("request")
        if request is not None and is_postbank(request.user):
            attrs["referrer_type"] = Referral.REFERRER_POSTBANK

        def current(field):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, "") if self.instance else ""

        kind = current("referrer_type") or Referral.REFERRER_HFCB
        for field in ("pf_number", "sales_code", "referrer_name"):
            if field in attrs:
                attrs[field] = (attrs[field] or "").strip()

        errors = {}
        if kind == Referral.REFERRER_POSTBANK:
            if not (current("sales_code") or "").strip():
                errors["sales_code"] = "Enter the Postbank referrer's sales code."
            if not (current("referrer_name") or "").strip():
                errors["referrer_name"] = "Enter the Postbank referrer's name."
        elif not (current("pf_number") or "").strip():
            errors["pf_number"] = "PF number is required."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    # ── Staff-register soft verification ──────────────────────────────────────
    @staticmethod
    def _apply_staff_verification(data):
        """Stamp ``staff_verified`` / ``verified_staff_name`` from the roster lookup.

        Never raises — an unknown PF/sales code is *flagged*, not rejected.
        A Postbank referrer is not on the bank's staff registers, and Postbank's
        codes can repeat ours, so a Postbank referral is never looked up there:
        it would "verify" against whichever of our staff shares the code.
        """
        if data.get("referrer_type") == Referral.REFERRER_POSTBANK:
            data["staff_verified"] = None
            data["verified_staff_name"] = ""
            return
        name, had_data = verify_staff(data.get("pf_number"), data.get("sales_code"))
        if name:
            data["staff_verified"] = Referral.STAFF_VERIFIED
            data["verified_staff_name"] = name
        elif had_data:
            data["staff_verified"] = Referral.STAFF_UNVERIFIED
            data["verified_staff_name"] = ""
        else:
            data["staff_verified"] = None  # could not check (roster empty/unavailable)
            data["verified_staff_name"] = ""

    @staticmethod
    def _fill_referrer_name(data):
        """An HFCB referrer left unnamed takes the name the register found."""
        if not (data.get("referrer_name") or "").strip() and data.get("verified_staff_name"):
            data["referrer_name"] = data["verified_staff_name"]

    def create(self, validated_data):
        validated_data.setdefault("referrer_type", Referral.REFERRER_HFCB)
        self._apply_staff_verification(validated_data)
        self._fill_referrer_name(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Re-verify only when the referrer identity actually changed.
        if {"pf_number", "sales_code", "referrer_type"} & set(validated_data):
            merged = {
                field: validated_data.get(field, getattr(instance, field))
                for field in ("pf_number", "sales_code", "referrer_type", "referrer_name")
            }
            self._apply_staff_verification(merged)
            self._fill_referrer_name(merged)
            validated_data.update(merged)
        return super().update(instance, validated_data)

    # ── Read-only name projections ────────────────────────────────────────────
    @staticmethod
    def _name(user):
        if not user:
            return None
        return user.get_full_name().strip() or user.username

    def get_created_by_name(self, obj):
        return self._name(obj.created_by)

    def get_assigned_to_name(self, obj):
        return self._name(obj.assigned_to)

    def get_allocated_by_name(self, obj):
        return self._name(obj.allocated_by)

    @staticmethod
    def _profile_field(user, field):
        return (getattr(getattr(user, "profile", None), field, "") or "").strip()

    def get_assigned_to_sales_code(self, obj):
        # Prefer the snapshot taken at allocation; fall back to the live Profile
        # for referrals allocated before the snapshot field existed.
        return obj.assigned_sales_code or self._profile_field(obj.assigned_to, "sales_code")

    def get_assigned_to_branch(self, obj):
        return self._profile_field(obj.assigned_to, "branch")


class TelesalesAgentSerializer(serializers.Serializer):
    """User projection for the allocation dropdown.

    Carries the Profile's sales code, branch and segment so a supervisor can pick
    the right relationship manager — two staff often share a first name, and the
    sales code is what the referral ends up credited to.
    """

    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    username = serializers.CharField()
    sales_code = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    segment = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    def get_name(self, obj):
        full = obj.get_full_name().strip()
        return full or obj.username

    @staticmethod
    def _profile_field(obj, field):
        return (getattr(getattr(obj, "profile", None), field, "") or "").strip()

    def get_sales_code(self, obj):
        return self._profile_field(obj, "sales_code")

    def get_branch(self, obj):
        return self._profile_field(obj, "branch")

    def get_segment(self, obj):
        return self._profile_field(obj, "segment")

    def get_roles(self, obj):
        return sorted(g.name for g in obj.groups.all())
