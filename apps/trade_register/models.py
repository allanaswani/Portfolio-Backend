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
from django.utils import timezone
from simple_history.models import HistoricalRecords

from . import references as refs


# Excise duty on fees charged by a financial institution, as a percentage of
# the fee. Kenya's rate at the time of writing; it is a DEFAULT for new tariff
# rows and not a constant the calculation reads, so a Finance Act change is an
# edit in Administration rather than a deploy. Confirm the rate and the base
# with the trade desk before relying on the figures.
DEFAULT_EXCISE_RATE = Decimal("20")


def _dec_early(value, default=None):
    """``_dec`` is defined below for readability; tariffs need it above."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


class TradeTariff(models.Model):
    """A line in the bank's trade tariff book.

    Products map to a tariff, and the tariff carries the charge. That is the
    point of the mapping: one tariff change reprices every product on it,
    instead of the same rate being edited product by product and drifting.

    A product with no tariff falls back to its own rate fields, which is how
    every product behaved before tariffs existed — so nothing is repriced by
    the mere act of adding this table.
    """

    BASIS_FLAT = "flat"
    BASIS_PER_QUARTER = "per_quarter"
    BASIS_PER_ANNUM = "per_annum"
    BASIS_NONE = "none"
    BASIS_CHOICES = [
        (BASIS_FLAT, "Flat % of the amount"),
        (BASIS_PER_QUARTER, "% per quarter (or part) of the tenor"),
        (BASIS_PER_ANNUM, "% per annum over the tenor"),
        (BASIS_NONE, "Not calculated — entered by hand"),
    ]

    code = models.CharField(max_length=30, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    commission_basis = models.CharField(
        max_length=16, choices=BASIS_CHOICES, default=BASIS_NONE,
    )
    commission_rate = models.DecimalField(
        max_digits=9, decimal_places=6, default=0,
        validators=[MinValueValidator(0)],
        help_text="Percent. 0.5 means 0.5%.",
    )
    minimum_commission = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Floor in local currency, applied after the rate.",
    )
    excise_rate = models.DecimalField(
        max_digits=9, decimal_places=6, default=DEFAULT_EXCISE_RATE,
        validators=[MinValueValidator(0)],
        help_text="Excise duty as a percent OF THE COMMISSION. 20 means 20%.",
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "trade_register_tariff"
        ordering = ["sort_order", "code"]
        verbose_name = "Trade Tariff"
        verbose_name_plural = "Trade Tariffs"

    def __str__(self):
        return f"{self.code} — {self.name}"

    def excise_on(self, commission):
        """Duty payable on a commission actually charged.

        Always computed from the fee on the record, not from the fee the tariff
        would have produced — when the desk overrides a negotiated commission,
        the duty is owed on what was charged.
        """
        fee = _dec_early(commission, Decimal("0")) or Decimal("0")
        rate = _dec_early(self.excise_rate, Decimal("0")) or Decimal("0")
        if fee <= 0 or rate <= 0:
            return Decimal("0.00")
        return (fee * rate / Decimal("100")).quantize(Decimal("0.01"))


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

    # ── How this product's commission is worked out ─────────────────────────
    BASIS_FLAT = "flat"
    BASIS_PER_QUARTER = "per_quarter"
    BASIS_PER_ANNUM = "per_annum"
    BASIS_NONE = "none"
    BASIS_CHOICES = [
        (BASIS_FLAT, "Flat % of the amount"),
        (BASIS_PER_QUARTER, "% per quarter (or part) of the tenor"),
        (BASIS_PER_ANNUM, "% per annum over the tenor"),
        (BASIS_NONE, "Not calculated — entered by hand"),
    ]

    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=255, unique=True)
    ref_family = models.CharField(max_length=16, choices=FAMILY_CHOICES)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    # The tariff line this product is charged under. When set, the tariff's
    # rate wins and the product's own rate fields below are ignored — that is
    # what makes the mapping worth having: repricing a tariff reprices every
    # product on it at once. A product with no tariff keeps using its own
    # fields, so nothing is repriced merely by this table existing.
    tariff = models.ForeignKey(
        TradeTariff, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
    )

    # The desk's pricing, kept as data so a rate change is an edit rather than a
    # deploy. A product left on BASIS_NONE calculates nothing and the figure is
    # typed, which is exactly how every product behaved before this existed.
    commission_basis = models.CharField(
        max_length=16, choices=BASIS_CHOICES, default=BASIS_NONE,
    )
    commission_rate = models.DecimalField(
        max_digits=9, decimal_places=6, default=0,
        validators=[MinValueValidator(0)],
        help_text="Percent. 0.5 means 0.5%.",
    )
    minimum_commission = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Floor in local currency, applied after the rate.",
    )
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "trade_register_product"
        ordering = ["sort_order", "name"]
        verbose_name = "Trade Product"

    def __str__(self):
        return f"{self.code} — {self.name}"

    # ── Where the charge comes from ─────────────────────────────────────────
    @property
    def pricing(self):
        """Whichever of the product or its tariff actually prices this.

        **A rate set on the product wins.** A tariff line is the general charge
        for a family; a rate typed against one product is a deliberate exception
        to it, and an exception that a mapping silently overruled would be a
        trap — somebody would set a rate, watch nothing happen, and have no way
        to see why. So the tariff answers only where the product does not, which
        also means mapping a product to a tariff never reprices it.

        Both objects expose the same rate fields, so the calculation does not
        care which answered; ``pricing_source`` tells the reader which did.
        """
        if self.commission_basis != self.BASIS_NONE:
            return self
        return self.tariff or self

    @property
    def pricing_source(self):
        if self.commission_basis != self.BASIS_NONE:
            return "product"
        return "tariff" if self.tariff_id else "product"

    @property
    def excise_rate(self):
        """Excise is a tariff-book figure. A product with no tariff falls back
        to the statutory default rather than silently charging no duty."""
        if self.tariff_id:
            return self.tariff.excise_rate
        return DEFAULT_EXCISE_RATE

    def excise_on(self, commission):
        """Duty on the commission actually charged (see TradeTariff.excise_on)."""
        if self.tariff_id:
            return self.tariff.excise_on(commission)
        fee = _dec(commission, Decimal("0")) or Decimal("0")
        rate = _dec(DEFAULT_EXCISE_RATE, Decimal("0")) or Decimal("0")
        if fee <= 0 or rate <= 0:
            return Decimal("0.00")
        return (fee * rate / Decimal("100")).quantize(Decimal("0.01"))

    def quote(self, amount_fcy, fx_rate=1, issue_date=None, expiry_date=None,
              is_open_ended=False):
        """What this product's commission comes to, and how it got there.

        Returns ``{commission, periods, basis, rate, minimum_applied,
        calculable, explanation, source, tariff_code}``. ``calculable`` is False
        when the charge is entered by hand, or the tenor a per-period rate needs
        is unknown — in that case the caller keeps whatever the user typed
        rather than overwriting it with a guess.

        The rate is read from the mapped tariff when the product has one.
        """
        pricing = self.pricing
        source = self.pricing_source
        # The line it is MAPPED to, reported whether or not it priced this —
        # the mapping is what the desk asked for, and a product priced by an
        # exception still belongs to its tariff family.
        tariff_code = self.tariff.code if self.tariff_id else ""

        amount = _dec(amount_fcy, Decimal("0")) or Decimal("0")
        rate_fx = _dec(fx_rate, Decimal("0")) or Decimal("0")
        # Everything is quoted in local currency, as commission_lcy always was.
        amount_lcy = amount * rate_fx if rate_fx > 0 else amount
        rate = _dec(pricing.commission_rate, Decimal("0")) or Decimal("0")
        minimum = _dec(pricing.minimum_commission, Decimal("0")) or Decimal("0")
        basis = pricing.commission_basis

        if basis == self.BASIS_NONE or rate <= 0:
            return {
                "commission": None, "periods": None, "basis": basis,
                "rate": rate, "minimum_applied": False, "calculable": False,
                "source": source, "tariff_code": tariff_code,
                "explanation": (
                    f"Neither this product nor tariff {tariff_code} prices it; "
                    "the commission is entered by hand." if tariff_code
                    else "This product's commission is entered by hand."
                ),
            }

        periods = Decimal("1")
        if basis in (self.BASIS_PER_QUARTER, self.BASIS_PER_ANNUM):
            days = self._tenor_days(issue_date, expiry_date, is_open_ended)
            if days is None:
                return {
                    "commission": None, "periods": None,
                    "basis": basis, "rate": rate,
                    "minimum_applied": False, "calculable": False,
                    "source": source, "tariff_code": tariff_code,
                    "explanation": (
                        "An expiry date is needed before a per-period rate can "
                        "be worked out."
                    ),
                }
            if basis == self.BASIS_PER_QUARTER:
                # A part quarter is charged as a whole one, as the desk prices it.
                periods = Decimal(max(1, -(-days // 90)))
                unit = "quarter"
            else:
                periods = Decimal(days) / Decimal("365")
                unit = "year"
        else:
            unit = None

        gross = amount_lcy * rate / Decimal("100") * periods
        commission = max(gross, minimum) if minimum > 0 else gross
        commission = commission.quantize(Decimal("0.01"))

        if unit:
            how = f"{rate}% per {unit} x {periods} {unit}(s)"
        else:
            how = f"{rate}% of the amount"
        return {
            "commission": commission,
            "periods": periods,
            "basis": basis,
            "rate": rate,
            "minimum_applied": bool(minimum > 0 and gross < minimum),
            "calculable": True,
            "source": source,
            "tariff_code": tariff_code,
            "explanation": (
                (f"Tariff {tariff_code}: " if source == "tariff" else "")
                + how + (f", floored at {minimum}" if minimum > 0 else "")
            ),
        }

    @staticmethod
    def _tenor_days(issue_date, expiry_date, is_open_ended):
        """Days between issue and expiry, or None when that is not knowable.

        An open-ended instrument has no tenor at all, so a per-period rate
        cannot be applied to it and the caller is told so.
        """
        if is_open_ended or not issue_date or not expiry_date:
            return None
        days = (expiry_date - issue_date).days
        return days if days > 0 else None


class TradeCurrency(models.Model):
    """A currency the desk may write a transaction in.

    A hard-coded list in the frontend is why currencies went missing: adding one
    meant a deploy. This is the list, and Administration can extend it.
    """

    code = models.CharField(max_length=3, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        managed = True
        db_table = "trade_register_currency"
        ordering = ["sort_order", "code"]
        verbose_name = "Trade Currency"
        verbose_name_plural = "Trade Currencies"

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
    # Set when the desk types a commission that differs from the product's own
    # pricing — a negotiated rate, or a figure the rate table cannot express.
    # While it is set the calculation leaves the number alone, so re-saving a
    # record never quietly undoes a deliberate correction.
    commission_override = models.BooleanField(default=False)

    # Excise duty on the commission. Always derived from the commission ON THIS
    # RECORD, including an overridden one — the duty is owed on the fee actually
    # charged, not on the fee the tariff would have produced.
    excise_duty = models.DecimalField(
        max_digits=20, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    # The tariff line this was charged under, captured at save time so the
    # record still says what it was charged under after the tariff is reprised.
    tariff_code = models.CharField(max_length=30, blank=True, db_index=True)

    # Reporting date — when the transaction is captured/reported. Auto-defaults to
    # the system date (Stacy's request); editable per record.
    reporting_date = models.DateField(default=timezone.localdate)

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

    # ── Expiry diary ────────────────────────────────────────────────────────
    # How the desk reads its own book: what has run out, what is about to, and
    # what never will. The thresholds are here rather than in the view so the
    # API, the page and any report all say the same thing about a record.
    DIARY_EXPIRED = "expired"
    DIARY_DUE_7 = "due_7"
    DIARY_DUE_30 = "due_30"
    DIARY_DUE_90 = "due_90"
    DIARY_LIVE = "live"
    DIARY_OPEN_ENDED = "open_ended"
    DIARY_UNDATED = "undated"

    DIARY_LABELS = {
        DIARY_EXPIRED: "Expired",
        DIARY_DUE_7: "Expires within 7 days",
        DIARY_DUE_30: "Expires within 30 days",
        DIARY_DUE_90: "Expires within 90 days",
        DIARY_LIVE: "Live",
        DIARY_OPEN_ENDED: "Open-ended",
        DIARY_UNDATED: "No expiry date recorded",
    }

    def days_to_expiry(self, today=None):
        """Days until expiry — negative once past. None when there is none."""
        if self.is_open_ended or not self.expiry_date:
            return None
        return (self.expiry_date - (today or timezone.localdate())).days

    def diary_status(self, today=None):
        """Which shelf of the diary this record sits on."""
        if self.is_open_ended:
            return self.DIARY_OPEN_ENDED
        if not self.expiry_date:
            # An instrument that is neither open-ended nor dated is a gap in the
            # register, not a live item — it is surfaced, not hidden in "live".
            return self.DIARY_UNDATED
        days = self.days_to_expiry(today)
        if days < 0:
            return self.DIARY_EXPIRED
        if days <= 7:
            return self.DIARY_DUE_7
        if days <= 30:
            return self.DIARY_DUE_30
        if days <= 90:
            return self.DIARY_DUE_90
        return self.DIARY_LIVE

    def quote_commission(self):
        """The product's own commission for this transaction (or None)."""
        if not self.product:
            return None
        return self.product.quote(
            self.amount_fcy, self.fx_rate, self.issue_date,
            self.expiry_date, self.is_open_ended,
        )

    def save(self, *args, **kwargs):
        if self.product:
            self.product_type = self.product.name
        if self.is_open_ended:
            self.expiry_date = None
        if self.issue_date:
            self.month = self.issue_date.strftime("%B").upper()
            self.year = str(self.issue_date.year)
        # Price the product unless the desk has deliberately overridden it.
        if not self.commission_override:
            quoted = self.quote_commission()
            if quoted and quoted["calculable"]:
                self.commission = quoted["commission"]
        # Duty follows the commission on the record, override or not.
        if self.product:
            self.tariff_code = self.product.tariff.code if self.product.tariff_id else ""
            self.excise_duty = self.product.excise_on(self.commission)
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
