from datetime import date

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords


class Collection(models.Model):
    cust_id = models.IntegerField(blank=True, null=True)
    loan_account_no = models.BigIntegerField(blank=True, null=True)
    collection_officer_code = models.CharField(max_length=100, blank=True, null=True)
    collection_officer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    contactibility = models.CharField(max_length=100, blank=True, null=True)
    reasons_for_default = models.CharField(max_length=255, blank=True, null=True)
    outcomes = models.CharField(max_length=255, blank=True, null=True)
    foreclosure_outcomes = models.CharField(max_length=255, blank=True, null=True)
    ptp_amount = models.BigIntegerField(blank=True, null=True)
    profiling = models.CharField(max_length=255, blank=True, null=True)
    next_action = models.CharField(max_length=255, blank=True, null=True)
    next_action_date = models.DateField(blank=True, null=True)
    additional_comments = models.TextField(blank=True, null=True)
    additional_contacts_1 = models.CharField(max_length=100, blank=True, null=True)
    additional_contacts_2 = models.CharField(max_length=100, blank=True, null=True)
    additional_contacts_3 = models.CharField(max_length=100, blank=True, null=True)
    recording_date = models.DateField(default=date.today)
    collection_status = models.CharField(max_length=50, default="closed")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hf_collections_feedback"


class PromiseToPay(models.Model):
    """A borrower's commitment to pay, and whether the money arrived.

    PTP - Promise To Pay - is the unit of work on a collections desk: a
    collector reaches somebody who is behind and takes a commitment, "50,000
    on the 28th". The promise on its own is worth very little. What the desk
    is actually measured on is the KEPT RATE, and that can only be known by
    looking at the money.

    So ``status`` is derived, never typed. There is no setter for it on the
    API: it is computed from ``loan_repayments``, the warehouse's payment
    feed, by comparing what was promised against what was actually paid on
    that loan account inside the window. A collector marking their own
    promise as kept would be marking their own homework, and the kept rate
    would stop being a measurement.

    See ``apps.hf_collections.ptp`` for the settlement rules and the grace
    period.
    """

    STATUS_OPEN = "open"
    STATUS_KEPT = "kept"
    STATUS_PART = "part_kept"
    STATUS_BROKEN = "broken"
    STATUS = (
        (STATUS_OPEN, "Not yet due"),
        (STATUS_KEPT, "Kept"),
        (STATUS_PART, "Partly kept"),
        (STATUS_BROKEN, "Broken"),
    )

    SOURCE_FEEDBACK = "feedback"
    SOURCE_DIRECT = "direct"
    SOURCE = (
        (SOURCE_FEEDBACK, "From a diary entry"),
        (SOURCE_DIRECT, "Recorded directly"),
    )

    cust_id = models.IntegerField(blank=True, null=True, db_index=True)
    #: The account the money has to land on. This is what the repayments feed
    #: is keyed on, so a promise without it can never be settled - which is
    #: why the serializer requires it.
    loan_account_no = models.BigIntegerField(blank=True, null=True,
                                             db_index=True)
    customer_name = models.CharField(max_length=255, blank=True, default="")

    collection_officer_code = models.CharField(max_length=100, blank=True,
                                               default="", db_index=True)
    collection_officer_name = models.CharField(max_length=255, blank=True,
                                               default="")

    #: Money is NUMERIC, never float. These are summed into a desk report and
    #: a float sum of a few thousand rows does not reconcile.
    promised_amount = models.DecimalField(max_digits=18, decimal_places=2,
                                          null=True, blank=True)
    promised_date = models.DateField(
        null=True, blank=True, db_index=True,
        help_text="The day the borrower said the money would be there.")
    #: The day the promise was taken. The settlement window opens here, not
    #: on the due date: a borrower who pays early has still kept their word.
    promised_on = models.DateField(default=date.today)

    # ── derived from the repayments feed, not typed ───────────────────────
    status = models.CharField(max_length=10, choices=STATUS,
                              default=STATUS_OPEN, db_index=True)
    amount_paid = models.DecimalField(max_digits=18, decimal_places=2,
                                      default=0)
    #: When the money actually landed, where it did.
    settled_on = models.DateField(null=True, blank=True)

    source = models.CharField(max_length=10, choices=SOURCE,
                              default=SOURCE_DIRECT)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hf_collections_ptp"
        verbose_name = "Promise to pay"
        verbose_name_plural = "Promises to pay"
        ordering = ["-promised_date", "-id"]
        constraints = [
            # One promise per loan, per date, per officer. Re-importing the
            # diary must correct the promise it already made rather than
            # stack a second copy of it - which would halve the kept rate.
            models.UniqueConstraint(
                fields=["loan_account_no", "promised_date",
                        "collection_officer_code"],
                name="hf_ptp_one_per_loan_date_officer"),
        ]
        indexes = [
            models.Index(fields=["status", "promised_date"]),
            models.Index(fields=["collection_officer_code", "status"]),
        ]

    def __str__(self):
        return (f"{self.customer_name or self.loan_account_no}: "
                f"{self.promised_amount} by {self.promised_date} "
                f"({self.status})")

    @property
    def shortfall(self):
        """How much of the promise never arrived. Never negative."""
        promised = self.promised_amount or 0
        return max(promised - (self.amount_paid or 0), 0)


class CollectionAllocation(models.Model):
    """A customer this desk allocated to an officer, because nobody had.

    Deliberately NOT written to ``loans.delay_officer``. That is a warehouse
    table the ETL rewrites from core banking every night, so anything put
    there is gone by morning - and it would be arguing with the source of
    truth besides. An officer's book is the union of the two: what core
    banking assigned, plus what was allocated here for the customers it left
    blank.

    One row per customer, not per loan. A customer with three loans in
    arrears is one person to call.
    """

    cust_id = models.BigIntegerField(unique=True, db_index=True)
    customer_name = models.CharField(max_length=255, blank=True, default="")
    branch = models.CharField(max_length=60, blank=True, default="")

    collection_officer_code = models.CharField(max_length=100, db_index=True)
    collection_officer_name = models.CharField(max_length=255, blank=True,
                                               default="")

    #: What was owed when this was allocated. Kept because it is the only
    #: record of what the officer was actually handed - the live figure moves
    #: the moment they start working it, and a book that looks small at
    #: review time may have been large when it was given out.
    arrears_at_allocation = models.DecimalField(
        max_digits=18, decimal_places=2, default=0)

    allocated_at = models.DateTimeField(auto_now_add=True, db_index=True)
    allocated_by = models.CharField(max_length=255, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")

    #: Cleared rather than deleted, so a reallocation keeps its history and
    #: somebody can be asked why a customer moved.
    is_active = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hf_collections_allocation"
        verbose_name = "Collections allocation"
        verbose_name_plural = "Collections allocations"
        ordering = ["-allocated_at"]
        indexes = [models.Index(fields=["collection_officer_code",
                                        "is_active"])]

    def __str__(self):
        return f"{self.cust_id} -> {self.collection_officer_code}"


class LoanCollateral(models.Model):
    """What a loan is actually secured on.

    A mirror of ``account_collateral`` joined to ``collateral`` in the lake,
    which is where the real security lives: 17,094 charges over 15,265 loan
    accounts, typed PROPERTY, VEHICLE, TERM DEPOSIT COLLATERAL, PLOT, BOND,
    PENSION, INSURANCE or GUARANTEE, each with its own estimated value.

    Not the same thing as what the collections page showed before. That read
    ``product_mapping``, which types the PRODUCT - so every mortgage read
    "PROPERTY" whether or not a charge existed, and a vehicle loan secured on
    a term deposit read whatever its product said. This is the charge itself.

    One row per loan account per charge. A loan can carry several: one
    customer in the sample has three against a single account, and summing
    their values is the only honest way to say what the bank is holding.

    Mirrored rather than read live for the same reason as the activity feed:
    the customer page is built on request, and a lake read on that path is
    what hands the browser a dead connection.
    """

    loan_account_no = models.CharField(max_length=40, db_index=True)
    cust_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    customer_name = models.CharField(max_length=255, blank=True, default="")

    #: The charge's own identity in core banking. Three columns, because
    #: ``collateral_sn`` repeats across units - the sample has a dozen
    #: charges numbered 1.
    unit_code = models.IntegerField(default=0)
    collateral_co = models.IntegerField(default=0)
    collateral_sn = models.IntegerField(default=0)

    collateral_type = models.CharField(max_length=80, blank=True, default="",
                                       db_index=True)
    collateral_desc = models.CharField(max_length=255, blank=True, default="")
    collateral_status = models.CharField(max_length=40, blank=True, default="")

    #: What it is reckoned to be worth. ``estimated_value`` is the figure on
    #: the account charge; ``collateral_value`` is the one on the charge
    #: itself, and the two do not always agree - both are kept rather than
    #: one being chosen for the reader.
    estimated_value = models.DecimalField(max_digits=20, decimal_places=2,
                                          null=True, blank=True)
    collateral_value = models.DecimalField(max_digits=20, decimal_places=2,
                                           null=True, blank=True)
    insurance_value = models.DecimalField(max_digits=20, decimal_places=2,
                                          null=True, blank=True)
    mortgage_amount = models.DecimalField(max_digits=20, decimal_places=2,
                                          null=True, blank=True)
    mortgage_class = models.CharField(max_length=40, blank=True, default="")
    expires_on = models.DateField(null=True, blank=True)

    loaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "hf_loan_collateral"
        verbose_name = "Loan collateral"
        verbose_name_plural = "Loan collateral"
        constraints = [
            models.UniqueConstraint(
                fields=["loan_account_no", "unit_code", "collateral_co",
                        "collateral_sn"],
                name="hf_one_charge_per_loan"),
        ]
        indexes = [models.Index(fields=["loan_account_no",
                                        "collateral_type"])]

    def __str__(self):
        return f"{self.loan_account_no} {self.collateral_type}"
