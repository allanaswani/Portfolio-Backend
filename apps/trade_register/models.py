"""Trade Register — the trade desk's weekly transactions register.

Replaces the earlier "Records & Registry" (physical-file custody) module. This
digitises Esther's "Weekly Trade Transactions" workbook: one row per guarantee /
LC transaction, with the reference number auto-generated (see
:mod:`.references`) instead of typed by hand.

Data model: ``TradeRegisterEntry`` is a richer table (real dates, a product FK,
generated-ref bookkeeping) that stays mirrored to the existing
``trade_finance_data`` table used by Administration → Trade Finance, via a
``OneToOne`` link and the :meth:`TradeRegisterEntry.sync_to_trade_finance`
mapping. A record added or edited in either place shows in both — the existing
Trade Finance page keeps working unchanged.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from . import references as refs


class TradeProduct(models.Model):
    """A trade-finance product the desk can issue, with its own code.

    These products are NOT in the loan/FD ``product_mapping`` list, so this is a
    purpose-built reference table. ``ref_family`` decides which reference pattern
    the generator uses for the product.
    """

    FAMILY_GUARANTEE = refs.FAMILY_GUARANTEE
    FAMILY_IMPORT_LC = refs.FAMILY_IMPORT_LC
    FAMILY_EXPORT_LC = refs.FAMILY_EXPORT_LC
    FAMILY_CHOICES = [
        (FAMILY_GUARANTEE, "Guarantee (HFCB/GTE/…)"),
        (FAMILY_IMPORT_LC, "Import LC (HF#####)"),
        (FAMILY_EXPORT_LC, "Export LC (HFCB/ELC/…)"),
    ]

    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=255, unique=True)
    ref_family = models.CharField(max_length=16, choices=FAMILY_CHOICES)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        managed = True
        db_table = "trade_register_product"
        ordering = ["sort_order", "name"]
        verbose_name = "Trade Product"

    def __str__(self):
        return f"{self.code} — {self.name}"


def _dec(value, default=None):
    """Coerce to Decimal, tolerating blanks/strings; ``default`` on failure."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


class TradeRegisterEntry(models.Model):
    """One trade transaction in the register (mirrors one ``trade_finance_data`` row)."""

    # ── Amendment actions (suffix appended to the parent reference) ──────────
    AMENDMENT_CHOICES = [("", "New (not an amendment)")] + [
        (s, s.title()) for s in refs.AMENDMENT_SUFFIXES
    ]

    # Link to the Administration Trade Finance row this entry mirrors.
    tf = models.OneToOneField(
        "staff_management.TradeFinanceData",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="register_entry",
    )

    originating_branch = models.CharField(max_length=255)
    rm_name = models.CharField(max_length=255)
    rm_code = models.CharField(max_length=255, blank=True)

    guarantee_ref = models.CharField(max_length=255, db_index=True, blank=True)
    product = models.ForeignKey(
        TradeProduct, on_delete=models.PROTECT, null=True, blank=True,
        related_name="entries",
    )
    # Denormalised product label actually written to the register / TF row.
    product_type = models.CharField(max_length=255)

    # Amendment bookkeeping — when set, the reference reuses the parent's number
    # with an action suffix instead of drawing a fresh one.
    amendment_type = models.CharField(max_length=32, blank=True, choices=AMENDMENT_CHOICES)
    parent_ref = models.CharField(max_length=255, blank=True)

    customer_id = models.BigIntegerField()
    segment = models.CharField(max_length=255)
    our_customer = models.CharField(max_length=255)
    beneficiary = models.CharField(max_length=255, blank=True)

    currency = models.CharField(max_length=3, default="KES")
    amount_fcy = models.DecimalField(
        max_digits=25, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    fx_rate = models.DecimalField(
        max_digits=10, decimal_places=6, default=0, validators=[MinValueValidator(0)],
    )
    commission = models.DecimalField(
        max_digits=20, decimal_places=6, default=0, validators=[MinValueValidator(0)],
    )

    issue_date = models.DateField()
    is_open_ended = models.BooleanField(default=False)
    expiry_date = models.DateField(null=True, blank=True)

    security_type = models.CharField(max_length=255, blank=True)
    cash_cover_amount = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    cash_cover_percentage = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    other_security = models.CharField(max_length=255, blank=True)

    # Derived from issue_date on save (kept for parity with the TF row).
    month = models.CharField(max_length=32, blank=True)
    year = models.CharField(max_length=8, blank=True, db_index=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="trade_register_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "trade_register_entry"
        ordering = ["-issue_date", "-id"]
        verbose_name = "Trade Register Entry"
        verbose_name_plural = "Trade Register Entries"

    def __str__(self):
        return f"{self.guarantee_ref} — {self.product_type} — {self.our_customer}"

    # ── Reference generation ────────────────────────────────────────────────
    def assign_reference(self, force=False):
        """Populate ``guarantee_ref`` if empty (or ``force``).

        Amendment → reuse parent's number with suffix. Otherwise generate a
        fresh reference from the product family and issue date. Import-LC numbers
        are only *suggested*: if the user already typed one it is kept.
        """
        if self.guarantee_ref and not force:
            return
        if self.amendment_type and self.parent_ref:
            self.guarantee_ref = refs.amend_reference(self.parent_ref, self.amendment_type)
            return
        family = self.product.ref_family if self.product else refs.FAMILY_GUARANTEE
        self.guarantee_ref = refs.generate_reference(family, self.issue_date)

    def save(self, *args, **kwargs):
        if self.product:
            self.product_type = self.product.name
        if self.is_open_ended:
            self.expiry_date = None
        if self.issue_date:
            self.month = self.issue_date.strftime("%B").upper()
            self.year = str(self.issue_date.year)
        self.assign_reference()
        super().save(*args, **kwargs)
        # Keep the mirrored Trade Finance row in step (same transaction as the
        # caller's, if any). Guarded so the TF→register signal never loops back.
        self.sync_to_trade_finance()

    # ── Sync to the Administration Trade Finance table ──────────────────────
    def _tf_field_values(self):
        expiry = "OPEN ENDED" if self.is_open_ended else (
            self.expiry_date.isoformat() if self.expiry_date else ""
        )
        return {
            "originating_branch": self.originating_branch or "",
            "rm_name": self.rm_name or "",
            "rm_code": self.rm_code or "",
            "guarantee_ref": self.guarantee_ref or "",
            "product_type": self.product_type or "",
            "customer_id": self.customer_id or 0,
            "segment": self.segment or "",
            "our_customer": self.our_customer or "",
            "beneficiary": self.beneficiary or "",
            "currency": self.currency or "KES",
            "amount_fcy": self.amount_fcy or 0,
            "issue_date": self.issue_date.isoformat() if self.issue_date else "",
            "expiry_date": expiry,
            "commission_lcy": self.commission or 0,
            "month": self.month or "",
            "fx_rate": self.fx_rate or 0,
            "year": self.year or "",
            "security_type": self.security_type or "",
            "cash_cover_amount": self.cash_cover_amount,
            "cash_cover_percentage": self.cash_cover_percentage,
            "other_security": self.other_security or "",
        }

    def sync_to_trade_finance(self):
        """Create or update the linked ``trade_finance_data`` row.

        Uses queryset ``.update()``/``.create()`` deliberately: ``.update()``
        does not fire model signals, so the register → TF write never triggers
        the TF → register back-sync (no loop).

        Non-destructive on update: only fields the register actually has a value
        for are written, so a blank the register didn't fill never wipes out
        information Trade Finance already has ("info we have right"). Amounts
        default to 0 — a real value — so they always sync; only empty text and
        null decimals (e.g. cash cover) are skipped. A create writes everything.
        """
        from apps.staff_management.models import TradeFinanceData

        values = self._tf_field_values()
        if self.tf_id:
            updates = {k: v for k, v in values.items() if v not in (None, "")}
            if updates:
                TradeFinanceData.objects.filter(pk=self.tf_id).update(**updates)
        else:
            tf = TradeFinanceData.objects.create(**values)
            # Link without re-triggering save()/sync.
            type(self).objects.filter(pk=self.pk).update(tf=tf)
            self.tf_id = tf.pk

    def apply_from_trade_finance(self, tf):
        """Back-fill scalar fields when the TF row is edited in Administration.

        Called from the ``post_save`` signal; persists via queryset ``.update()``
        so it does not re-enter ``save()``/sync. Non-destructive in the same
        spirit as :meth:`sync_to_trade_finance`: a value TF left blank does not
        wipe what the register already holds (its extra fields — product FK,
        amendment, is_open_ended — are never touched here). Amounts sync as-is
        (0 is a real value); text fields only overwrite when non-empty."""
        from datetime import datetime

        def _parse_date(value):
            if not value:
                return None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(str(value)[:19], fmt).date()
                except ValueError:
                    continue
            return None

        open_ended = str(tf.expiry_date or "").strip().upper() == "OPEN ENDED"

        # Text fields: overwrite only when TF has something (preserve otherwise).
        text = {
            "originating_branch": tf.originating_branch, "rm_name": tf.rm_name,
            "rm_code": tf.rm_code, "guarantee_ref": tf.guarantee_ref,
            "product_type": tf.product_type, "segment": tf.segment,
            "our_customer": tf.our_customer, "beneficiary": tf.beneficiary,
            "currency": tf.currency, "security_type": tf.security_type,
            "other_security": tf.other_security,
        }
        updates = {k: v for k, v in text.items() if v not in (None, "")}

        # Numerics always reflect TF (0 is meaningful); customer_id only if set.
        updates["amount_fcy"] = _dec(tf.amount_fcy, 0)
        updates["fx_rate"] = _dec(tf.fx_rate, 0)
        updates["commission"] = _dec(tf.commission_lcy, 0)
        if tf.customer_id:
            updates["customer_id"] = tf.customer_id
        for key, dec in (("cash_cover_amount", _dec(tf.cash_cover_amount)),
                         ("cash_cover_percentage", _dec(tf.cash_cover_percentage))):
            if dec is not None:
                updates[key] = dec

        # Dates: only overwrite when TF actually parses to a date.
        issue = _parse_date(tf.issue_date)
        if issue is not None:
            updates["issue_date"] = issue
        updates["is_open_ended"] = open_ended
        if open_ended:
            updates["expiry_date"] = None
        else:
            expiry = _parse_date(tf.expiry_date)
            if expiry is not None:
                updates["expiry_date"] = expiry

        type(self).objects.filter(pk=self.pk).update(**updates)
