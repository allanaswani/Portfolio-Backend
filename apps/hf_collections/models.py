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
