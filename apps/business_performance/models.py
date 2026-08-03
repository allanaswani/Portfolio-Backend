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
