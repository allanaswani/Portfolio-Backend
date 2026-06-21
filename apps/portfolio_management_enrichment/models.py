from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

# ──────────────────────────────────────────────────────────────────────────────
# Customer–RM reallocation
# ------------------------------------------------------------------------------
# This part of the module documents how customer relationship-management
# ownership is moved between Relationship Managers (RMs) in the bank:
#   • CustomerAllocationBase       — the snapshot of every customer and the RM
#                                    they are currently (and were previously)
#                                    allocated to, with the financials used to
#                                    justify/score a reallocation.
#   • RmAllocationList             — the catalogue of RMs that customers can be
#                                    (re)allocated to.
#   • TeamLeaderMovementApprovers  — the team leaders who approve a movement for
#                                    a given segment/branch.
#   • CustomerTransferHistory      — the audit log of each actual transfer
#                                    (from-RM → to-RM) and its approval state.
# Ported from the legacy backend; managed in the application DB.
# ──────────────────────────────────────────────────────────────────────────────


class CustomerEnrichment(models.Model):
    cust_id = models.BigIntegerField(unique=True)
    income_band = models.CharField(max_length=50, blank=True, null=True)
    employment_status = models.CharField(max_length=100, blank=True, null=True)
    employer = models.CharField(max_length=255, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    monthly_income_estimate = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    property_owner = models.BooleanField(null=True, blank=True)
    credit_score = models.IntegerField(blank=True, null=True)
    risk_rating = models.CharField(max_length=20, blank=True, null=True)
    lifetime_value_estimate = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    preferred_channel = models.CharField(max_length=50, blank=True, null=True)
    data_source = models.CharField(max_length=100, blank=True, null=True)
    enrichment_date = models.DateField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    input_user = models.CharField(max_length=100, default="me")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "portfolio_customer_enrichment"
        ordering = ["-updated_at"]


class RmTarget(models.Model):
    sales_code = models.CharField(max_length=50)
    month = models.DateField()
    deposit_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    loan_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    revenue_target = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    new_customers_target = models.IntegerField(default=0)
    recording_date = models.DateField(auto_now_add=True)
    input_user = models.CharField(max_length=100, default="me")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "portfolio_rm_targets"
        unique_together = (("sales_code", "month"),)


class CustomerAllocationBase(models.Model):
    """Snapshot of customers and their current/previous RM allocation."""
    group_id = models.CharField(max_length=100)
    cust_id = models.CharField(max_length=100, unique=True)
    customer_name = models.CharField(max_length=255)
    segment = models.CharField(max_length=100)
    main_segment_prev = models.CharField(max_length=100)
    main_segment = models.CharField(max_length=100)
    customer_branch_name = models.CharField(max_length=255)
    cust_branch = models.CharField(max_length=100)
    proposed_segment = models.CharField(max_length=100)
    aum_group = models.DecimalField(max_digits=20, decimal_places=2)
    aum_cust_id = models.DecimalField(max_digits=20, decimal_places=2)
    rm_code_prev = models.CharField(max_length=100)
    rm_name_prev = models.CharField(max_length=255)
    rm_role_prev = models.CharField(max_length=100)
    rm_branch_prev = models.CharField(max_length=255)
    rm_segment_prev = models.CharField(max_length=100)
    rank_branch = models.IntegerField()
    rank_rm_code = models.IntegerField()
    rm_code = models.CharField(max_length=100)
    rm_name = models.CharField(max_length=255)
    rm_role = models.CharField(max_length=100)
    rm_branch_name = models.CharField(max_length=255)
    rm_branch_code = models.CharField(max_length=100)
    rm_active_status = models.CharField(max_length=50)
    source = models.CharField(max_length=100)
    interest_income = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    nfi = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    interest_expense = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    net_after_expense = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    loan_loss = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    ftp = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    npl = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    active_one_month = models.DecimalField(max_digits=20, decimal_places=2)
    active_two_month = models.DecimalField(max_digits=20, decimal_places=2)
    active_three_month = models.DecimalField(max_digits=20, decimal_places=2)
    deposit = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    loans = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    telephone = models.CharField(max_length=20, null=True, blank=True)
    home_telephone = models.CharField(max_length=20, null=True, blank=True)
    mobile_tel = models.CharField(max_length=20, null=True, blank=True)
    mobile_tel2 = models.CharField(max_length=20, null=True, blank=True)
    telephone_1 = models.CharField(max_length=20, null=True, blank=True)
    id_no = models.CharField(max_length=50, null=True, blank=True)
    sex = models.CharField(max_length=10, null=True, blank=True)
    e_mail = models.EmailField(null=True, blank=True)
    e_mail2 = models.EmailField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "customer_allocation_base"
        verbose_name = "Customer Allocation Base"
        verbose_name_plural = "Customer Allocation Bases"
        ordering = ["-aum_cust_id"]

    def __str__(self):
        return f"{self.customer_name} - ID: {self.cust_id}"


class RmAllocationList(models.Model):
    """Catalogue of Relationship Managers available for (re)allocation."""
    rm_code = models.CharField(max_length=100, unique=True)
    rm_name = models.CharField(max_length=255)
    rm_role = models.CharField(max_length=100)
    rm_branch_name = models.CharField(max_length=255)
    rm_branch_code = models.CharField(max_length=100)
    rm_active_status = models.CharField(max_length=50)
    source = models.CharField(max_length=100)
    rm_segment = models.CharField(max_length=100)

    class Meta:
        managed = True
        db_table = "rm_allocation_list"
        verbose_name = "RM Allocation List"
        verbose_name_plural = "RM Allocation Lists"
        ordering = ["rm_name"]

    def __str__(self):
        return f"{self.rm_name} ({self.rm_code})"


class TeamLeaderMovementApprovers(models.Model):
    """Team leaders who approve customer movements for a segment/branch."""
    segment = models.CharField(max_length=100)
    sales_code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    branch_code = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        managed = True
        db_table = "customer_movment_approval_list"
        verbose_name = "customer_movment_approval_list"
        verbose_name_plural = "customer_movment_approval_list"
        ordering = ["name"]

    def __str__(self):
        suffix = f" at branch {self.branch_code}" if self.branch_code else ""
        return f"{self.name} - Leader of {self.segment}{suffix}"


class CustomerTransferHistory(models.Model):
    """Audit log of each customer RM transfer and its approval details."""
    group_id = models.CharField(max_length=100)
    cust_id = models.CharField(max_length=100)
    customer_name = models.CharField(max_length=255)
    main_segment = models.CharField(max_length=100)
    customer_branch_name = models.CharField(max_length=255)
    cust_branch = models.CharField(max_length=100)
    from_rm_code = models.CharField(max_length=100)
    from_rm_name = models.CharField(max_length=255)
    from_rm_role = models.CharField(max_length=100)
    from_rm_branch_name = models.CharField(max_length=255)
    to_rm_code = models.CharField(max_length=100)
    to_rm_name = models.CharField(max_length=255)
    to_rm_role = models.CharField(max_length=100)
    to_rm_branch_name = models.CharField(max_length=255)
    transfer_date = models.DateTimeField(default=timezone.now)
    approved_by_team_leader = models.CharField(max_length=255)
    approval_status = models.CharField(max_length=20, default="under_review")
    approval_comments = models.CharField(max_length=255, default="approved")
    requesting_comments = models.CharField(max_length=255, default="reviewed")
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "portfolio_customer_transfer_history"
        verbose_name = "Customer Transfer History"
        verbose_name_plural = "Customer Transfer Histories"
        ordering = ["-transfer_date"]

    def __str__(self):
        return (
            f"Transfer: {self.customer_name} from {self.from_rm_name} "
            f"to {self.to_rm_name} - Status: {self.approval_status}"
        )
