"""Referral module — telesales lead capture and allocation.

A member of staff keys in a *referral* (a prospective customer they know), which a
telesales supervisor then allocates to a telesales agent to work. The lifecycle is a
single status enum:

    unallocated → allocated → contacted → converted
                                        ↘ rejected
    (and, via the retention cron, → expired/purged if it goes stale)

The model deliberately mirrors ``apps.mortgages.Lead``: a ``TimeStamped`` base, a
short business reference, an ``assigned_to`` owner, and ``simple_history`` tracking
so every allocation/status change (and even deletions by the retention job) is
auditable.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from simple_history.models import HistoricalRecords

# Reuse the bank's canonical branch/segment lists (the same ones the Users admin
# screen offers and Profile stores) so referral tracking stays consistent with the
# rest of the platform instead of inventing a parallel list.
from apps.portfolio.models import BRANCH_CHOICES, SEGMENT_CHOICES

USER = settings.AUTH_USER_MODEL


def _ref(prefix: str) -> str:
    """Short unique business reference, e.g. ``RF-9F3A1C2B``."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Referral(TimeStamped):
    # ── Lifecycle ─────────────────────────────────────────────────────────────
    STATUS_UNALLOCATED = "unallocated"
    STATUS_ALLOCATED = "allocated"
    STATUS_CONTACTED = "contacted"
    STATUS_CONVERTED = "converted"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS = [
        (STATUS_UNALLOCATED, "Unallocated"),
        (STATUS_ALLOCATED, "Allocated"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_CONVERTED, "Converted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED, "Expired"),
    ]
    #: Statuses an agent may set via the "update status" endpoint.
    AGENT_SETTABLE_STATUSES = {STATUS_CONTACTED, STATUS_CONVERTED, STATUS_REJECTED}

    # Verification of the PF/sales code against the staff register.
    STAFF_VERIFIED = True      # matched a roster row
    STAFF_UNVERIFIED = False   # roster has data but no match
    # (``None`` = roster empty/unavailable, i.e. could not be checked.)

    referral_ref = models.CharField(max_length=40, unique=True, blank=True)

    # ── Referrer (who is making the referral) ─────────────────────────────────
    # ``pf_number`` is the field of record (staff aren't 1:1 with system logins),
    # while ``created_by`` links the authenticated user who actually keyed it in.
    pf_number = models.CharField(max_length=30)
    sales_code = models.CharField(max_length=50, blank=True)
    created_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals_created"
    )
    # Result of the soft staff-register lookup (see ``apps.referrals.staff``).
    staff_verified = models.BooleanField(null=True, blank=True)
    verified_staff_name = models.CharField(max_length=200, blank=True)

    # ── Referred customer ─────────────────────────────────────────────────────
    customer_name = models.CharField(max_length=200)
    national_id = models.CharField(max_length=20)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)

    # ── Tracking (branch / segment) ───────────────────────────────────────────
    # Selected from the canonical BRANCH_CHOICES / SEGMENT_CHOICES so referrals can
    # be grouped and filtered by branch and segment. Optional at capture.
    branch = models.CharField(max_length=32, choices=BRANCH_CHOICES, blank=True)
    segment = models.CharField(max_length=32, choices=SEGMENT_CHOICES, blank=True)
    # Free-text (dropdown fed from the live employee_table department list, which is
    # dynamic — so no static choices here); optional at capture.
    department = models.CharField(max_length=120, blank=True)

    # ── Allocation to telesales ───────────────────────────────────────────────
    status = models.CharField(max_length=20, choices=STATUS, default=STATUS_UNALLOCATED)
    assigned_to = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals_assigned"
    )
    allocated_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals_allocated"
    )
    allocated_at = models.DateTimeField(null=True, blank=True)

    # ── Working / lifecycle timestamps ────────────────────────────────────────
    contacted_at = models.DateTimeField(null=True, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Flagged (not blocked) when the same national ID or phone was referred before.
    is_possible_duplicate = models.BooleanField(default=False)

    history = HistoricalRecords(table_name="referrals_history")

    class Meta:
        managed = True
        db_table = "referrals"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["national_id"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["assigned_to"]),
            models.Index(fields=["created_by"]),
        ]

    def __str__(self):
        return f"{self.referral_ref} — {self.customer_name}"

    def _recompute_duplicate_flag(self):
        """Flag when this customer's national ID or phone was referred before.

        We flag rather than block (per the module's duplicate policy): the same
        person legitimately being referred twice is worth surfacing, not forbidding.
        """
        match = Q()
        if self.national_id:
            match |= Q(national_id=self.national_id)
        if self.phone:
            match |= Q(phone=self.phone)
        if not match:
            self.is_possible_duplicate = False
            return
        self.is_possible_duplicate = (
            Referral.objects.exclude(pk=self.pk).filter(match).exists()
        )

    def save(self, *args, **kwargs):
        if not self.referral_ref:
            self.referral_ref = _ref("RF")
        self._recompute_duplicate_flag()
        super().save(*args, **kwargs)
