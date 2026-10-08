"""Commercial Pipeline — the spreadsheet the Commercial RMs keep, as a table.

Replaces "Commercial Pipeline - Assets and Trade with Summary.xlsx", which is
mailed around, edited by several people at once and reconciled by hand. Its
four working sheets become one table with a ``kind``:

==================  ==========================================================
Assets Pipeline     A lending application in flight: amount requested, amount
                    expected to disburse, product, and where it has reached.
Trade Pipeline      A guarantee or LC: exposure amount, the revenue it earns.
Deposits Pipeline   Money expected in: CASA, FD, cash margin or escrow, how
                    much, by when.
Insurance Pipeline  An insurance cover expected against an account: VIC (all
                    Britam products) or non-VIC (everything else), by a date.
==================  ==========================================================

The last two were called "Deposits" and "Liabilities" when this shipped, after
the sheet names in the workbook. They were renamed after the walkthrough with
the Commercial RM — the liabilities sheet has in practice only ever held
insurance, and calling it that is what lets the VIC / non-VIC split exist at
all. The stored ``kind`` values did not change; see ``KIND``.

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

The vocabulary was then widened by "Additional System requirements.xlsx", which
came out of the walkthrough with the Commercial RM: it adds the RM Only, Credit
Analysis, Credit Evaluation and Disbursement stages and names the unit
responsible at each point. Nothing was deleted to make room — see
``RETIRED_STAGES``.

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
    #: Labels are what the RM reads, and two of them were renamed after the
    #: Commercial RM walkthrough: "Deposits" became "Deposits Pipeline", and
    #: "Liabilities" became "Insurance Pipeline" - which is what that sheet has
    #: always actually held. The STORED VALUES are deliberately unchanged:
    #: ``liability`` still means the insurance pipeline. Renaming the value
    #: would mean a data migration, a changed API contract and a changed
    #: workbook sheet name, to no one's benefit - nobody types the value.
    KIND = (
        (KIND_ASSET, "Assets Pipeline"),
        (KIND_TRADE, "Trade Pipeline"),
        (KIND_DEPOSIT, "Deposits Pipeline"),
        (KIND_LIABILITY, "Insurance Pipeline"),
    )

    # ── Stage ────────────────────────────────────────────────────────────
    # Two sources, in this order:
    #
    # 1. the workbook's own Explanations sheet, which gave the four broad
    #    stages and twelve specific ones this module shipped with;
    # 2. "Additional System requirements.xlsx", the sheet that came out of the
    #    walkthrough with the Commercial RM. It lists each application stage
    #    against the unit responsible at that point, and it is ADDITIVE: the
    #    two rows prefixed "Remove-" are the only things it takes away.
    #
    # Nothing is deleted from either tuple. A stage that is no longer offered
    # goes into RETIRED_STAGES instead, so a row that already carries it still
    # renders a label and can still be edited. Deleting the choice would leave
    # stored rows showing a bare slug and no way to save them.

    BROAD_DISCUSSION = "discussion"
    BROAD_APPLICATION = "application"
    BROAD_RM_ONLY = "rm_only"
    BROAD_CREDIT_ANALYSIS = "credit_analysis"
    BROAD_CREDIT_EVALUATION = "credit_evaluation"
    BROAD_APPROVED = "approved"
    BROAD_DISBURSEMENT = "disbursement"
    #: Superseded by BROAD_DISBURSEMENT - the requirements sheet says
    #: "Remove-Disbursed". Kept as a value so history still reads properly;
    #: not offered, and migration 0002 moves live rows onto the new one.
    BROAD_DISBURSED = "disbursed"

    BROAD_STAGE = (
        (BROAD_DISCUSSION, "Discussion — not yet in I-Apply"),
        (BROAD_RM_ONLY, "RM Only"),
        (BROAD_APPLICATION, "Application — in the system, not yet approved"),
        (BROAD_CREDIT_ANALYSIS, "Credit Analysis"),
        (BROAD_CREDIT_EVALUATION, "Credit Evaluation"),
        (BROAD_APPROVED, "Approved — anywhere after approval"),
        (BROAD_DISBURSEMENT, "Disbursement"),
        (BROAD_DISBURSED, "Disbursed"),
    )

    #: The specific stages. The Explanations sheet's thirteen, plus the
    #: requirements sheet's "Responsible User / Unit" column, labelled in its
    #: own words so the RM recognises the list they gave us.
    STAGE = (
        ("discussion", "Discussion"),
        ("relationship_manager", "Relationship Manager (RM)"),
        ("at_branch", "At branch"),
        ("at_credit_analyst", "At credit analyst"),
        ("credit_analyst", "Credit Analyst"),
        ("credit_origination_manager", "Credit Origination Manager"),
        ("at_credit_risk", "At credit risk"),
        ("pre", "PRE"),
        ("ccm", "CCM"),
        ("dcr", "DCR"),
        ("bmd", "BMD"),
        ("mlc", "MLC"),
        ("board", "Board"),
        ("branch_rm", "Branch / RM"),
        ("offer_letter_generation", "At offer letter generation"),
        ("offer_letter_at_branch", "Offer letter at branch for collection"),
        ("awaiting_execution", "Awaiting customer to execute offer letter"),
        ("valuation", "Valuation"),
        ("valuation_adoption", "Valuation Adoption"),
        ("instructions_to_lawyers", "Instructions to Lawyers"),
        ("charge_preparation", "Charge preparation"),
        ("joint_registration", "Joint Registration"),
        ("bank_attorneys_execution", "Bank Attorneys Execution"),
        ("charge_dispatch", "Charge dispatch to customer"),
        ("charge_execution", "Charge execution by customer"),
        ("awaiting_registration", "Awaiting registration process"),
        ("confirmation_of_securities", "Confirmation of Securities"),
        ("disbursement_officer", "Disbursement Officer"),
        ("insurance_confirmation", "Insurance Confirmation"),
        ("trade_middle_officer", "Trade Middle Officer"),
        ("cpc", "CPC"),
        ("disbursement", "Disbursement"),
    )

    #: Not offered on the form any more, and refused on a new row or on a
    #: change. Still accepted on a row that already carries one, so nothing
    #: becomes un-editable. ``charge_dispatch`` is the sheet's "Remove-Charge
    #: Dispatch to Customer"; the specific ``disbursement`` is superseded by
    #: the six units the sheet now lists under the Disbursement stage.
    RETIRED_STAGES = {"charge_dispatch", "disbursement"}
    RETIRED_BROAD_STAGES = {BROAD_DISBURSED}

    #: Which specific stages sit under which broad one. Used to validate the
    #: pair, so the two columns can never contradict each other the way they
    #: did in the spreadsheet.
    #:
    #: ``pre`` sits under three broad stages, because the requirements sheet
    #: genuinely lists PRE at three points in the journey. The PAIR is what
    #: says which one is meant, which is the whole reason both columns exist.
    STAGES_UNDER_BROAD = {
        BROAD_DISCUSSION: {"discussion"},
        BROAD_RM_ONLY: {"relationship_manager"},
        BROAD_APPLICATION: {"at_branch", "at_credit_analyst", "at_credit_risk"},
        BROAD_CREDIT_ANALYSIS: {"credit_analyst", "credit_origination_manager"},
        BROAD_CREDIT_EVALUATION: {"pre", "ccm", "dcr", "bmd", "mlc", "board"},
        BROAD_APPROVED: {
            "branch_rm", "offer_letter_generation", "offer_letter_at_branch",
            "awaiting_execution", "valuation", "valuation_adoption",
            "instructions_to_lawyers", "charge_preparation",
            "joint_registration", "bank_attorneys_execution",
            "charge_execution", "awaiting_registration", "pre",
            # Retired, kept valid for rows that already carry it.
            "charge_dispatch",
        },
        BROAD_DISBURSEMENT: {
            "confirmation_of_securities", "disbursement_officer", "pre",
            "insurance_confirmation", "trade_middle_officer", "cpc",
            # Retired, kept valid for rows carried over from "Disbursed".
            "disbursement",
        },
        BROAD_DISBURSED: {"disbursement"},
    }

    #: Deposits. CASA and FD are the workbook's own two values; cash margin
    #: and escrow come from the requirements sheet's Deposits block.
    DEPOSIT_PRODUCT = (
        ("CASA", "CASA"),
        ("FD", "Fixed deposit"),
        ("CASH_MARGIN", "Cash margin"),
        ("ESCROW", "Escrow"),
    )

    #: Insurance Pipeline. The requirements sheet gives exactly two, and says
    #: what each covers - so the label carries the scope, rather than a help
    #: text nobody opens.
    INSURANCE_VIC = "VIC"
    INSURANCE_NON_VIC = "NON_VIC"
    INSURANCE_TYPE = (
        (INSURANCE_VIC, "VIC — all Britam products"),
        (INSURANCE_NON_VIC, "Non-VIC — all other insurance covers"),
    )

    #: The fewest words a comment may carry. From the requirements sheet: "the
    #: system should enforce a minimum word requirement for comments at each
    #: workflow stage ... to enable management and other users to understand
    #: the position clearly without requiring additional clarification."
    #:
    #: The sheet does not give a number. Eight is one short sentence, and this
    #: is the single constant to change if the desk wants more. Enforced in the
    #: serializer, on a new line and on any change to the stage or the comment
    #: itself - never retrospectively, or every imported row would be frozen
    #: until somebody wrote it a paragraph.
    MIN_COMMENT_WORDS = 8

    #: Which columns each kind actually uses. The API validates against this
    #: and the UI renders from it, so a field cannot be required in one place
    #: and hidden in the other.
    FIELDS_BY_KIND = {
        KIND_ASSET: ["amount", "amount_to_disburse", "product",
                     "broad_stage", "stage", "comments"],
        KIND_TRADE: ["amount", "revenue", "product", "broad_stage", "stage",
                     "comments"],
        KIND_DEPOSIT: ["amount", "deposit_product", "expected_date", "comments"],
        KIND_LIABILITY: ["amount", "insurance_type", "account_no",
                         "expected_date", "comments"],
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
    # 16, not 8: 'CASH_MARGIN' does not fit in 8 characters.
    deposit_product = models.CharField(max_length=16,
                                       choices=DEPOSIT_PRODUCT, blank=True)
    #: Insurance Pipeline only. Blank on every row that predates it, and
    #: on anything the workbook importer loads - the old Liabilities sheet
    #: has no such column, so the RM sets it when they next touch the line.
    #: No index: two values over a few hundred rows, where a btree costs more
    #: than the sequential scan it would replace.
    insurance_type = models.CharField(max_length=8, choices=INSURANCE_TYPE,
                                      blank=True, verbose_name="VIC / Non-VIC")
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
