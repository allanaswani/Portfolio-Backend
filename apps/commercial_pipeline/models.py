"""Commercial Pipeline — the spreadsheet the Commercial RMs keep, as a table.

Replaces "Commercial Pipeline - Assets and Trade with Summary.xlsx", which is
mailed around, edited by several people at once and reconciled by hand. Its
four working sheets become one table with a ``kind``:

=============  ===============================================================
Assets         A lending application in flight: amount requested, amount
               expected to disburse, product, and where it has reached.
Trade          A guarantee or LC: exposure amount, the revenue it earns, type.
Deposits       Money expected in: CASA or FD, how much, by when.
Liabilities    An expected balance against an account number, by a date.
=============  ===============================================================

One table rather than four because a Team Leader's question is "what is my
team carrying", which spans all of them, and because every sheet already shares
the same spine: branch, RM, customer, an amount, a stage and a comment. Fields
a kind does not use are simply left blank, and ``FIELDS_BY_KIND`` records which
those are so the API and the UI cannot disagree about it.

**Stages are controlled values here, and were free text in the spreadsheet.**
That is the single biggest change and the reason the file could not be
aggregated: 68 asset rows carried the broad stage as 'Approved', 'Application',
'Credit Risk' and 'Credit Analyis' — the last a typo, and the middle two not
broad stages at all but specific ones written in the broad column. The
Explanations sheet defines four broad stages and twelve specific ones; both are
modelled, and the specific stage is checked against the broad one it belongs
to.

Product is deliberately NOT a controlled list. The same 68 rows spell contract
financing five ways, but the right answer there is a suggestion list rather
than a constraint — a new product must not be un-enterable because nobody has
added it to a choices tuple yet.
"""

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

USER = settings.AUTH_USER_MODEL


class PipelineEntry(models.Model):
    """One line of the commercial pipeline, whatever kind it is."""

    # ── What kind of line this is ────────────────────────────────────────
    KIND_ASSET = "asset"
    KIND_TRADE = "trade"
    KIND_DEPOSIT = "deposit"
    KIND_LIABILITY = "liability"
    KIND = (
        (KIND_ASSET, "Assets Pipeline"),
        (KIND_TRADE, "Trade Pipeline"),
        (KIND_DEPOSIT, "Deposits"),
        (KIND_LIABILITY, "Liabilities"),
    )

    # ── Stage, per the Explanations sheet ────────────────────────────────
    # Four broad stages. The sheet lists these as the whole vocabulary for the
    # "Broad Application stage" column.
    BROAD_DISCUSSION = "discussion"
    BROAD_APPLICATION = "application"
    BROAD_APPROVED = "approved"
    BROAD_DISBURSED = "disbursed"
    BROAD_STAGE = (
        (BROAD_DISCUSSION, "Discussion — not yet in I-Apply"),
        (BROAD_APPLICATION, "Application — in the system, not yet approved"),
        (BROAD_APPROVED, "Approved — anywhere after approval"),
        (BROAD_DISBURSED, "Disbursed"),
    )

    # The twelve specific stages, in the order the sheet lists them, which is
    # the order work actually moves through.
    STAGE = (
        ("discussion", "Discussion"),
        ("at_branch", "At branch"),
        ("at_credit_analyst", "At credit analyst"),
        ("at_credit_risk", "At credit risk"),
        ("offer_letter_generation", "At offer letter generation"),
        ("offer_letter_at_branch", "Offer letter at branch for collection"),
        ("awaiting_execution", "Awaiting customer to execute offer letter"),
        ("valuation", "Valuation"),
        ("charge_preparation", "Charge preparation"),
        ("charge_dispatch", "Charge dispatch to customer"),
        ("charge_execution", "Charge execution by customer"),
        ("awaiting_registration", "Awaiting registration process"),
        ("disbursement", "Disbursement"),
    )

    #: Which specific stages sit under which broad one. Used to validate the
    #: pair, so the two columns can never contradict each other the way they
    #: did in the spreadsheet.
    STAGES_UNDER_BROAD = {
        BROAD_DISCUSSION: {"discussion"},
        BROAD_APPLICATION: {"at_branch", "at_credit_analyst", "at_credit_risk"},
        BROAD_APPROVED: {
            "offer_letter_generation", "offer_letter_at_branch",
            "awaiting_execution", "valuation", "charge_preparation",
            "charge_dispatch", "charge_execution", "awaiting_registration",
        },
        BROAD_DISBURSED: {"disbursement"},
    }

    #: Deposits are one or the other; the sheet has no third value in 40 rows.
    DEPOSIT_PRODUCT = (("CASA", "CASA"), ("FD", "Fixed deposit"))

    #: Which columns each kind actually uses. The API validates against this
    #: and the UI renders from it, so a field cannot be required in one place
    #: and hidden in the other.
    FIELDS_BY_KIND = {
        KIND_ASSET: ["amount", "amount_to_disburse", "product",
                     "broad_stage", "stage", "comments"],
        KIND_TRADE: ["amount", "revenue", "product", "broad_stage", "stage",
                     "comments"],
        KIND_DEPOSIT: ["amount", "deposit_product", "expected_date", "comments"],
        KIND_LIABILITY: ["amount", "account_no", "expected_date", "comments"],
    }

    kind = models.CharField(max_length=12, choices=KIND, db_index=True)

    # ── Who it belongs to ────────────────────────────────────────────────
    # sales_code is the owner: it is what an RM's own view filters on, and it
    # matches portfolio_profile.sales_code, the convention the rest of the
    # platform already uses (see core.permissions.RBACQueryFilter).
    sales_code = models.CharField(max_length=32, blank=True, db_index=True)
    # Kept as written, because rows imported from the spreadsheet have a name
    # and no code, and losing the name would lose the only owner they have.
    rm_name = models.CharField(max_length=150, blank=True)
    branch = models.CharField(max_length=120, blank=True, default="Commercial")
    # What a Team Leader's view filters on. Compared through core.segments,
    # never with equality - the same segment is spelled several ways across
    # this platform.
    segment = models.CharField(max_length=60, blank=True, default="COMMERCIAL",
                               db_index=True)

    # ── The line itself ──────────────────────────────────────────────────
    customer_name = models.CharField(max_length=200)

    # Money is NUMERIC, never float: these are reported to a Team Leader and
    # summed, and a float sum of twenty rows does not reconcile with the
    # spreadsheet it replaced.
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    #: Assets: the part expected to actually draw down, which is often far less
    #: than the amount requested (10m requested, 6m to disburse, in the file).
    amount_to_disburse = models.DecimalField(max_digits=18, decimal_places=2,
                                             null=True, blank=True)
    #: Trade: what the facility earns. Blank on plenty of trade rows already.
    revenue = models.DecimalField(max_digits=18, decimal_places=2,
                                  null=True, blank=True)

    product = models.CharField(max_length=160, blank=True)
    deposit_product = models.CharField(max_length=8, choices=DEPOSIT_PRODUCT, blank=True)
    account_no = models.CharField(max_length=40, blank=True)

    broad_stage = models.CharField(max_length=20, choices=BROAD_STAGE, blank=True)
    stage = models.CharField(max_length=30, choices=STAGE, blank=True)

    #: Deposits call this "Receipt date/By When"; liabilities "Date expected".
    #: One field, because both mean the date the money is expected.
    expected_date = models.DateField(null=True, blank=True)

    comments = models.TextField(blank=True)

    # ── Housekeeping ─────────────────────────────────────────────────────
    is_active = models.BooleanField(
        default=True,
        help_text="Cleared rather than deleted, so a dropped deal stays in the "
                  "record and can be explained.")
    created_by = models.ForeignKey(USER, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="pipeline_created")
    updated_by = models.ForeignKey(USER, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="pipeline_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    # Who changed what, which the spreadsheet could never answer.
    history = HistoricalRecords(table_name="commercial_pipeline_entry_history")

    class Meta:
        db_table = "commercial_pipeline_entry"
        ordering = ["-updated_at"]
        verbose_name_plural = "Pipeline entries"
        indexes = [
            models.Index(fields=["kind", "is_active", "-updated_at"]),
            models.Index(fields=["sales_code", "kind"]),
            models.Index(fields=["segment", "kind"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.customer_name}"

    @property
    def uses(self):
        """The field names this row's kind actually uses."""
        return self.FIELDS_BY_KIND.get(self.kind, [])
