"""Strategy & Business Performance — data the department owns itself.

The bank-wide *actuals* (deposits, loans, NFI, customers, …) already flow from
the GCEO / analytics endpoints. What the executive cockpit adds is a place for
the Strategy & Business Performance team to record the **targets** those actuals
are measured against — deposits/loans/customers have no target source anywhere
else in the system. One row = one target for one metric, at one scope, for one
period. Achievement (% of target) and RAG status are computed on the fly against
the live actuals, so nothing here duplicates a figure that already exists.
"""

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class StrategyTarget(models.Model):
    """A single performance target the strategy team sets and tracks against."""

    class Metric(models.TextChoices):
        DEPOSITS         = "deposits",         "Total Deposits"
        LOANS            = "loans",            "Total Loans"
        NFI              = "nfi",              "Non-Funded Income"
        INTEREST_INCOME  = "interest_income",  "Interest Income"
        INTEREST_EXPENSE = "interest_expense", "Interest Expense"
        REVENUE          = "revenue",          "Total Revenue"
        CUSTOMERS        = "customers",        "Total Customers"
        NEW_CUSTOMERS    = "new_customers",    "New Customers"
        DIGITAL_ACTIVE   = "digital_active",   "Digital Active Customers"

    class Scope(models.TextChoices):
        BANK    = "bank",    "Bank-wide"
        SEGMENT = "segment", "Segment"
        BRANCH  = "branch",  "Branch"
        RM      = "rm",      "Relationship Manager"

    class Period(models.TextChoices):
        ANNUAL    = "annual",    "Annual"
        QUARTERLY = "quarterly", "Quarterly"
        MONTHLY   = "monthly",   "Monthly"

    metric      = models.CharField(max_length=32, choices=Metric.choices)
    scope_type  = models.CharField(max_length=16, choices=Scope.choices, default=Scope.BANK)
    # Segment/branch name or RM sales code; blank for bank-wide.
    scope_value = models.CharField(max_length=120, blank=True, default="")

    period_type = models.CharField(max_length=16, choices=Period.choices, default=Period.ANNUAL)
    year        = models.PositiveIntegerField()
    quarter     = models.PositiveSmallIntegerField(null=True, blank=True)  # 1–4, quarterly only
    month       = models.PositiveSmallIntegerField(null=True, blank=True)  # 1–12, monthly only

    # Monetary metrics in KES; customer metrics are counts. Stored as a plain
    # decimal — the frontend knows each metric's unit.
    target_value = models.DecimalField(max_digits=20, decimal_places=2)
    note         = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bp_strategy_target"
        ordering = ["metric", "-year", "-quarter", "-month"]
        constraints = [
            models.UniqueConstraint(
                fields=["metric", "scope_type", "scope_value",
                        "period_type", "year", "quarter", "month"],
                name="uniq_strategy_target",
            ),
        ]

    def __str__(self):
        scope = self.scope_value or "bank"
        period = self.period_type
        if self.period_type == self.Period.QUARTERLY and self.quarter:
            period = f"Q{self.quarter} {self.year}"
        elif self.period_type == self.Period.MONTHLY and self.month:
            period = f"{self.year}-{self.month:02d}"
        else:
            period = str(self.year)
        return f"{self.get_metric_display()} · {scope} · {period} = {self.target_value}"


class BankingSectorPosition(models.Model):
    """Where every Kenyan bank sits, as CBK publishes it each quarter.

    Nothing in this warehouse knows what another bank is worth. Every table
    here is HF Group's own book, so the honest answer to "how do we compare"
    was "no data" — which is why the assistant kept returning a note panel
    instead of a market-share chart.

    CBK publishes the sector figures quarterly (the Bank Supervision Annual
    Report and the quarterly sector releases). They are public, so holding
    them here breaks no confidence, and once they are a table the assistant
    charts them like any other figure instead of reaching outside the bank.

    One row per bank per period. ``is_us`` marks HF Group's own row so a panel
    can highlight it without string-matching a name that may be spelled three
    ways across releases.
    """

    period = models.CharField(
        max_length=20, db_index=True,
        help_text="The CBK period, e.g. '2026-Q2'. Sorts correctly as text.")
    bank_name = models.CharField(max_length=255, db_index=True)
    is_us = models.BooleanField(
        default=False,
        help_text="True on HF Group's own row, so a chart can highlight it.")

    # All money in KES. Nullable because CBK does not publish every measure
    # for every bank in every release, and a zero would be a lie.
    total_assets = models.DecimalField(max_digits=22, decimal_places=2, blank=True, null=True)
    total_deposits = models.DecimalField(max_digits=22, decimal_places=2, blank=True, null=True)
    total_loans = models.DecimalField(max_digits=22, decimal_places=2, blank=True, null=True)
    profit_before_tax = models.DecimalField(max_digits=22, decimal_places=2, blank=True, null=True)

    market_share_pct = models.DecimalField(max_digits=7, decimal_places=4, blank=True, null=True)
    tier = models.CharField(max_length=20, blank=True, help_text="CBK tier: 1, 2 or 3.")
    branches = models.IntegerField(blank=True, null=True)
    npl_ratio_pct = models.DecimalField(max_digits=7, decimal_places=4, blank=True, null=True)

    source = models.CharField(
        max_length=255, blank=True,
        help_text="Which CBK release this row came from, so a figure can be traced.")
    recorded_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "bp_banking_sector_position"
        unique_together = ("period", "bank_name")
        ordering = ["-period", "-total_assets"]
        verbose_name = "Banking sector position"
        verbose_name_plural = "Banking sector positions"

    def __str__(self):
        return f"{self.period} · {self.bank_name}"
