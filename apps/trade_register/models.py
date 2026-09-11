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

# "Nothing was passed" — distinct from a caller passing None to mean "the book
# has no line for this", which is a real answer worth honouring.
_UNSET = object()


def _dec_early(value, default=None):
    """``_dec`` is defined below for readability; tariffs need it above."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


class TradeProductCategory(models.Model):
    """A family of trade products — the desk's own grouping.

    The desk works category-first: pick "Letters of Guarantee", then the
    guarantee. The form's product dropdown is filtered by the chosen category,
    which is why this is a real table and not a label on the product.

    It also selects the price. The tariff book charges by category and action
    ("LC Amendment Charges", "Cancellation Commission"), not per product, so
    the category is half of the key that finds a charge.
    """

    code = models.CharField(max_length=30, unique=True, db_index=True)
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "trade_register_product_category"
        ordering = ["sort_order", "name"]
        verbose_name = "Trade Product Category"
        verbose_name_plural = "Trade Product Categories"

    def __str__(self):
        return self.name


class TradeTariff(models.Model):
    """One charge line from the bank's published tariff book.

    A charge is selected by **what the instrument is and what is being done to
    it** — the tariff lists "LC Issuance Charges", "LC Amendment Charges",
    "Cancellation Commission" and "LC Advising Charges" as separate lines, so a
    line is keyed on (category, action). A line may also name a single product,
    which is how a product-specific price is expressed: a bid bond is 1% flat
    while its category charges 0.75% per quarter.

    Both halves of a charge are editable, because the tariff uses both: some
    lines are a percentage with a floor ("0.75% per quarter; Min. KShs. 2,500")
    and some are a flat amount ("General Amendment — 2,000").
    """

    # How the percentage is applied over the instrument's life.
    BASIS_FLAT = "flat"
    BASIS_PER_QUARTER = "per_quarter"
    BASIS_PER_ANNUM = "per_annum"
    BASIS_PER_MONTH = "per_month"
    BASIS_PER_INSTANCE = "per_instance"
    BASIS_NONE = "none"
    BASIS_CHOICES = [
        (BASIS_FLAT, "Flat % of the amount"),
        (BASIS_PER_QUARTER, "% per quarter (or part) of the tenor"),
        (BASIS_PER_ANNUM, "% per annum over the tenor"),
        (BASIS_PER_MONTH, "Per month (or part) of the tenor"),
        (BASIS_PER_INSTANCE, "A fixed amount, once per transaction"),
        (BASIS_NONE, "Not calculated — entered by hand"),
    ]

    code = models.CharField(max_length=40, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # ── What this line prices ───────────────────────────────────────────────
    # A line with no category applies to every category; a line with no action
    # applies to every action. A line naming a product beats one that does not.
    category = models.ForeignKey(
        TradeProductCategory, on_delete=models.CASCADE, null=True, blank=True,
        related_name="tariffs",
    )
    action = models.CharField(
        max_length=32, blank=True,
        help_text="One of the desk's actions, or blank to apply to all of them.",
    )
    product = models.ForeignKey(
        "TradeProduct", on_delete=models.CASCADE, null=True, blank=True,
        related_name="own_tariffs",
        help_text="Set only for a product priced differently from its category.",
    )

    # ── The charge ──────────────────────────────────────────────────────────
    commission_basis = models.CharField(
        max_length=16, choices=BASIS_CHOICES, default=BASIS_NONE,
    )
    commission_rate = models.DecimalField(
        max_digits=9, decimal_places=6, default=0,
        validators=[MinValueValidator(0)],
        help_text="Percent. 0.75 means 0.75%. Leave 0 for a fixed-amount charge.",
    )
    fixed_amount = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="A flat fee charged instead of a percentage (e.g. 2,000).",
    )
    minimum_commission = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Floor applied after the rate (the tariff's 'Min. KShs …').",
    )
    # The tariff quotes a few charges in dollars (Discrepancy US$100). Storing
    # the currency stops that being silently read as shillings.
    charge_currency = models.CharField(max_length=3, default="KES")

    excise_rate = models.DecimalField(
        max_digits=9, decimal_places=6, default=DEFAULT_EXCISE_RATE,
        validators=[MinValueValidator(0)],
        help_text="Excise duty as a percent OF THE COMMISSION. 20 means 20%.",
    )

    # Charges the tariff does not state as a number ("As charged by the Notary
    # Public", "As per loan account approval"). Recorded so the line exists and
    # says why it cannot be computed, rather than being left out of the book.
    manual_note = models.CharField(max_length=255, blank=True)

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "trade_register_tariff"
        ordering = ["sort_order", "code"]
        verbose_name = "Trade Tariff"
        verbose_name_plural = "Trade Tariffs"
        indexes = [models.Index(fields=["category", "action", "is_active"])]

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

    @classmethod
    def resolve(cls, product, action):
        """The tariff line that prices this product doing this action.

        Most specific wins, so a product-specific price beats its category's:

        1. this product + this action
        2. this product, any action
        3. this product's category + this action
        4. this product's category, any action

        Returns ``None`` when the book has no line for it, which the caller
        reports as "entered by hand" rather than guessing a number.
        """
        if product is None:
            return None
        action = (action or refs.ACTION_ISSUANCE).strip().upper()
        category_id = product.category_id
        lines = list(
            cls.objects.filter(is_active=True)
            .filter(
                models.Q(product=product)
                | models.Q(product__isnull=True, category_id=category_id)
            )
            .filter(models.Q(action=action) | models.Q(action=""))
        )
        if not lines:
            return None

        def rank(line):
            # Lower is better: product beats category, exact action beats blank.
            return (0 if line.product_id else 1, 0 if line.action else 1, line.sort_order)

        return sorted(lines, key=rank)[0]


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

    # The bank's own product code where it has one (14116 = BID BOND
    # GUARANTEE). Blank for products the desk has not been given a code for —
    # the letters of credit and the bills — so the column stays honest rather
    # than carrying an invented number.
    code = models.CharField(max_length=40, unique=True, db_index=True)
    name = models.CharField(max_length=255, unique=True)
    category = models.ForeignKey(
        TradeProductCategory, on_delete=models.PROTECT, null=True, blank=True,
        related_name="products",
    )
    ref_family = models.CharField(max_length=16, choices=FAMILY_CHOICES)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    # The tariff line this product is charged under. Kept for the products
    # mapped before charges moved to (category, action); ``TradeTariff.resolve``
    # is what actually finds the price now, and this is its last fallback.
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
    def pricing_for(self, action=None, tariff_line=_UNSET):
        """The tariff line that prices this product doing ``action``.

        Charges live in the tariff book, keyed on (category, action) with
        product-specific exceptions — see :meth:`TradeTariff.resolve`. A rate
        typed directly on the product still wins over all of it: it is a
        deliberate override, and a book that silently overruled it would leave
        somebody setting a rate, watching nothing happen, and unable to see why.
        """
        if self.commission_basis != self.BASIS_NONE:
            return self, "product"
        # A caller serialising a page has already resolved the line for this
        # (product, action) and passes it in, so the lookup runs once for the
        # page instead of once per row.
        line = TradeTariff.resolve(self, action) if tariff_line is _UNSET else tariff_line
        if line is not None:
            return line, "tariff"
        # Last fallback: the tariff a product was mapped to before charges moved
        # to (category, action).
        if self.tariff_id:
            return self.tariff, "tariff"
        return self, "product"

    @property
    def pricing(self):
        return self.pricing_for()[0]

    @property
    def pricing_source(self):
        return self.pricing_for()[1]

    def excise_rate_for(self, action=None):
        """Excise is a tariff-book figure. A product the book does not reach
        falls back to the statutory default rather than charging no duty."""
        line, source = self.pricing_for(action)
        if source == "tariff":
            return line.excise_rate
        return DEFAULT_EXCISE_RATE

    @property
    def excise_rate(self):
        return self.excise_rate_for()

    def excise_on(self, commission, action=None):
        """Duty on the commission actually charged (see TradeTariff.excise_on)."""
        fee = _dec(commission, Decimal("0")) or Decimal("0")
        rate = _dec(self.excise_rate_for(action), Decimal("0")) or Decimal("0")
        if fee <= 0 or rate <= 0:
            return Decimal("0.00")
        return (fee * rate / Decimal("100")).quantize(Decimal("0.01"))

    def quote(self, amount_fcy, fx_rate=1, issue_date=None, expiry_date=None,
              is_open_ended=False, action=None, tariff_line=_UNSET):
        """What this transaction's commission comes to, and how it got there.

        The charge depends on the ACTION as well as the product — issuing a
        guarantee, amending it and cancelling it are three different lines in
        the tariff book — so the action selects the line.

        Returns ``{commission, periods, basis, rate, minimum_applied,
        calculable, explanation, source, tariff_code, currency}``.
        ``calculable`` is False when the charge is entered by hand, or the tenor
        a per-period rate needs is unknown; the caller then keeps whatever the
        user typed rather than overwriting it with a guess.
        """
        pricing, source = self.pricing_for(action, tariff_line)
        tariff_code = getattr(pricing, "code", "") if source == "tariff" else ""
        tariff_name = getattr(pricing, "name", "") if source == "tariff" else ""
        charge_currency = getattr(pricing, "charge_currency", "KES")
        manual_note = getattr(pricing, "manual_note", "")

        def answer(**kw):
            base = {
                "commission": None, "periods": None,
                "basis": getattr(pricing, "commission_basis", self.BASIS_NONE),
                "rate": Decimal("0"), "minimum_applied": False,
                "calculable": False, "source": source,
                "tariff_code": tariff_code, "tariff_name": tariff_name,
                "currency": charge_currency, "action": (action or "").upper(),
                "explanation": "",
            }
            base.update(kw)
            return base

        amount = _dec(amount_fcy, Decimal("0")) or Decimal("0")
        rate_fx = _dec(fx_rate, Decimal("0")) or Decimal("0")
        # Everything is quoted in local currency, as commission_lcy always was.
        amount_lcy = amount * rate_fx if rate_fx > 0 else amount
        rate = _dec(getattr(pricing, "commission_rate", 0), Decimal("0")) or Decimal("0")
        minimum = _dec(getattr(pricing, "minimum_commission", 0), Decimal("0")) or Decimal("0")
        fixed = _dec(getattr(pricing, "fixed_amount", 0), Decimal("0")) or Decimal("0")
        basis = getattr(pricing, "commission_basis", self.BASIS_NONE)

        # A charge the tariff states only in words ("As charged by the Notary
        # Public"). Checked AFTER the numbers, because a line can carry both:
        # LC advising is 2,500 with a note that a non-customer pays 3,500. The
        # note is guidance on a real charge, not a reason to refuse to compute
        # one — treating it as one would leave the desk typing a figure the
        # book actually states.
        if manual_note and rate <= 0 and fixed <= 0:
            return answer(explanation=f"{tariff_name}: {manual_note}")

        # ── A flat fee: "General Amendment — 2,000" ─────────────────────────
        # Charged per transaction regardless of amount or tenor, so it needs
        # neither and can always be answered.
        if fixed > 0 and rate <= 0:
            return answer(
                commission=fixed.quantize(Decimal("0.01")),
                periods=Decimal("1"), basis=basis, rate=Decimal("0"),
                calculable=True,
                explanation=(
                    (f"Tariff {tariff_code}: " if tariff_code else "")
                    + f"{charge_currency} {fixed:,.2f} per transaction"
                    + (f" — {manual_note}" if manual_note else "")
                ),
            )

        if basis == self.BASIS_NONE or rate <= 0:
            return answer(
                rate=rate,
                explanation=(
                    f"Tariff {tariff_code} does not state a rate; the commission "
                    "is entered by hand." if tariff_code
                    else "This product's commission is entered by hand."
                ),
            )

        periods = Decimal("1")
        unit = None
        if basis in (self.BASIS_PER_QUARTER, self.BASIS_PER_ANNUM,
                     TradeTariff.BASIS_PER_MONTH):
            days = self._tenor_days(issue_date, expiry_date, is_open_ended)
            if days is None:
                return answer(
                    basis=basis, rate=rate,
                    explanation=(
                        "An expiry date is needed before a per-period rate can "
                        "be worked out."
                    ),
                )
            if basis == self.BASIS_PER_QUARTER:
                # A part quarter is charged as a whole one, as the desk prices it.
                periods = Decimal(max(1, -(-days // 90)))
                unit = "quarter"
            elif basis == TradeTariff.BASIS_PER_MONTH:
                periods = Decimal(max(1, -(-days // 30)))
                unit = "month"
            else:
                periods = Decimal(days) / Decimal("365")
                unit = "year"

        gross = amount_lcy * rate / Decimal("100") * periods
        commission = max(gross, minimum) if minimum > 0 else gross
        commission = commission.quantize(Decimal("0.01"))

        how = (f"{rate}% per {unit} x {periods} {unit}(s)" if unit
               else f"{rate}% of the amount")
        return answer(
            commission=commission,
            periods=periods,
            basis=basis,
            rate=rate,
            minimum_applied=bool(minimum > 0 and gross < minimum),
            calculable=True,
            explanation=(
                (f"Tariff {tariff_code}: " if tariff_code else "")
                + how
                + (f", min {charge_currency} {minimum:,.2f}" if minimum > 0 else "")
            ),
        )

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


class TradeRegisterEntryQuerySet(models.QuerySet):
    def with_position(self):
        """Annotate each instrument's live position in ONE query.

        Without this, serialising a list asks the database for each row's
        amendment total, latest expiry and count separately — and the expiry
        several times over, because the diary status, the label and the days to
        expiry each read it. A page of ten was issuing dozens of aggregates.
        """
        return self.annotate(
            _amendment_delta=models.Sum("amendments__amount_delta"),
            _amendment_expiry=models.Max("amendments__new_expiry_date"),
            _amendment_count=models.Count("amendments", distinct=True),
            _cancellation_count=models.Count(
                "amendments",
                filter=models.Q(amendments__action=refs.ACTION_CANCELLATION),
                distinct=True,
            ),
        # The aggregates add a GROUP BY, and Django then treats the queryset as
        # UNORDERED even though Meta.ordering is set. PostgreSQL is free to
        # return grouped rows in any order, so page 2 could repeat or skip rows
        # from page 1 — which quietly breaks paging and makes an export that
        # crawls the pages come back short. Ordering explicitly restores it.
        ).order_by(*(self.model._meta.ordering or ["-id"]))


class TradeRegisterEntry(models.Model):
    """One trade transaction in the register (mirrors one ``trade_finance_data`` row)."""

    objects = TradeRegisterEntryQuerySet.as_manager()

    # ── What this transaction does ──────────────────────────────────────────
    # The desk's six actions. ISSUANCE creates an instrument and draws a fresh
    # reference; the other five act on one that already exists and reuse its
    # reference with the action as a suffix.
    ACTION_CHOICES = [(a, a.title()) for a in refs.ACTIONS]
    ACTIONS_ON_EXISTING = refs.ACTIONS_ON_EXISTING

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

    # ── Action bookkeeping ──────────────────────────────────────────────────
    # Anything other than an issuance reuses the parent's reference with the
    # action as a suffix instead of drawing a fresh one. ``choices`` is NOT set:
    # rows written before the six-action list carry values no longer offered
    # (EXT, CALL UP, RETIREMENT …), and a register is a record of what happened
    # — rewriting a settled transaction to fit a new dropdown would falsify it.
    # The API offers only the six; the column keeps whatever history holds.
    action = models.CharField(max_length=32, blank=True, default=refs.ACTION_ISSUANCE)
    parent_ref = models.CharField(max_length=255, blank=True)
    # The instrument this acts on. parent_ref is what the desk types and what
    # the historical rows carry; this is the resolved link, which is what lets
    # an instrument know its own amendments and compute its live position.
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="amendments",
    )
    # An amendment's effect on the instrument. Positive increases the exposure,
    # negative reduces it; zero for an action that changes only the date or
    # nothing at all. Kept separate from amount_fcy so the amendment row still
    # records the amount it was raised for.
    amount_delta = models.DecimalField(
        max_digits=25, decimal_places=2, default=0,
        help_text="Increase (+) or reduction (−) this amendment applies.",
    )
    # An amendment that moves the expiry. The instrument's live expiry is the
    # latest of these, which is why an extended guarantee stops reading expired.
    new_expiry_date = models.DateField(null=True, blank=True)

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

    # ── Expiry filing ───────────────────────────────────────────────────────
    # An expired instrument leaves the active diary and is filed under Expired,
    # by a job that runs daily (``manage.py archive_expired_trade_items``).
    # It is a FLAG, never a deletion: an expired guarantee is still a record of
    # what the bank issued, and it is still needed for reporting and audit.
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_on = models.DateField(null=True, blank=True)

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
        if self.action and self.action != refs.ACTION_ISSUANCE and self.parent_ref:
            self.guarantee_ref = refs.amend_reference(self.parent_ref, self.action)
            return
        family = self.product.ref_family if self.product else refs.FAMILY_GUARANTEE
        self.guarantee_ref = refs.generate_reference(family, self.issue_date)

    def resolve_parent(self):
        """Link an action to the instrument it acts on, from the typed reference.

        The desk types the original's reference; this finds the row. Matching
        ignores any action suffix the typed value carries, so amending an
        amendment still lands on the original instrument rather than building a
        chain nothing can total.
        """
        if self.action == refs.ACTION_ISSUANCE or not self.parent_ref:
            return
        if self.parent_id:
            return
        base = refs.base_reference(self.parent_ref)
        parent = (
            type(self).objects
            .filter(guarantee_ref=base)
            .exclude(pk=self.pk)
            .order_by("id").first()
        )
        if parent is not None:
            self.parent = parent

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

    # ── The instrument's live position ──────────────────────────────────────
    # An amendment is its own row, so the original keeps saying what was
    # actually issued. What the bank is exposed to TODAY, and when the
    # instrument really runs out, are the original plus its amendments.
    @property
    def is_amendment(self):
        return bool(self.parent_id or self.parent_ref) and self.action != refs.ACTION_ISSUANCE

    # Each of these reads its amendments. Serialising a list calls them several
    # times per row — current_amount, the expiry, the diary status, the days to
    # expiry — so a page of ten was issuing dozens of aggregates. When the
    # queryset has been through ``with_position()`` the figures are already
    # annotated and no query is made; the fallbacks below keep a lone instance
    # correct on its own.
    @property
    def current_amount(self):
        """Issued amount plus every amendment's increase or reduction."""
        base = _dec(self.amount_fcy, Decimal("0")) or Decimal("0")
        if hasattr(self, "_amendment_delta"):
            return base + (_dec(self._amendment_delta, Decimal("0")) or Decimal("0"))
        if not self.pk:
            return base
        delta = self.amendments.aggregate(d=models.Sum("amount_delta"))["d"]
        return base + (_dec(delta, Decimal("0")) or Decimal("0"))

    @property
    def effective_expiry_date(self):
        """When this instrument actually runs out.

        The latest expiry any amendment moved it to, else its own. Reading the
        original's date would show an extended guarantee as expired, and the
        desk would chase an instrument that is still perfectly live.
        """
        if self.is_open_ended:
            return None
        latest = self.expiry_date
        if hasattr(self, "_amendment_expiry"):
            moved = self._amendment_expiry
        elif self.pk:
            moved = (
                self.amendments.exclude(new_expiry_date=None)
                .aggregate(m=models.Max("new_expiry_date"))["m"]
            )
        else:
            moved = None
        if moved and (latest is None or moved > latest):
            latest = moved
        return latest

    @property
    def amendment_count(self):
        if hasattr(self, "_amendment_count"):
            return self._amendment_count or 0
        return self.amendments.count() if self.pk else 0

    @property
    def is_cancelled(self):
        """A cancelled instrument is closed, whatever its expiry says."""
        if hasattr(self, "_cancellation_count"):
            return (self._cancellation_count or 0) > 0
        if not self.pk:
            return False
        return self.amendments.filter(action=refs.ACTION_CANCELLATION).exists()

    def days_to_expiry(self, today=None):
        """Days until expiry — negative once past. None when there is none."""
        expiry = self.effective_expiry_date
        if self.is_open_ended or not expiry:
            return None
        return (expiry - (today or timezone.localdate())).days

    def diary_status(self, today=None):
        """Which shelf of the diary this record sits on."""
        if self.is_open_ended:
            return self.DIARY_OPEN_ENDED
        if not self.effective_expiry_date:
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

    def quote_commission(self, tariff_line=_UNSET):
        """What the tariff charges for this transaction (or None).

        The action is passed through, because the charge for amending an
        instrument is a different line from the charge for issuing it.
        """
        if not self.product:
            return None
        return self.product.quote(
            self.amount_fcy, self.fx_rate, self.issue_date,
            self.expiry_date, self.is_open_ended, action=self.action,
            tariff_line=tariff_line,
        )

    def save(self, *args, **kwargs):
        if self.product:
            self.product_type = self.product.name
        if self.is_open_ended:
            self.expiry_date = None
        if self.issue_date:
            self.month = self.issue_date.strftime("%B").upper()
            self.year = str(self.issue_date.year)
        if not self.action:
            self.action = refs.ACTION_ISSUANCE
        self.resolve_parent()
        # Price the product unless the desk has deliberately overridden it.
        # The action selects the tariff line: issuing, amending and cancelling
        # are three different charges in the book.
        if not self.commission_override:
            quoted = self.quote_commission()
            if quoted and quoted["calculable"]:
                self.commission = quoted["commission"]
        # Duty follows the commission on the record, override or not.
        if self.product:
            line, source = self.product.pricing_for(self.action)
            self.tariff_code = line.code if source == "tariff" else ""
            self.excise_duty = self.product.excise_on(self.commission, self.action)
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
