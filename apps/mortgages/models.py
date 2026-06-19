"""
Mortgages module — loan lifecycle + field-sales CRM.

All tables are greenfield and app-managed (``managed = True``), so they live in
the ``default`` database and are created by this app's migrations. Reference
chain: ``Lead → MortgageApplication → MortgageLoan`` (nullable FKs, each with its
own status enum).
"""

import uuid

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

USER = settings.AUTH_USER_MODEL


def _ref(prefix: str) -> str:
    """Short unique business reference, e.g. ``LD-9F3A1C2B``."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ──────────────────────────────────────────────────────────────────────────────
# Loan lifecycle
# ──────────────────────────────────────────────────────────────────────────────

class MortgageProduct(TimeStamped):
    PRODUCT_TYPES = [
        ("home_purchase", "Home Purchase"),
        ("construction", "Construction"),
        ("refinance", "Refinance"),
        ("equity_release", "Equity Release"),
        ("affordable_housing", "Affordable Housing"),
    ]
    RATE_TYPES = [("fixed", "Fixed"), ("variable", "Variable")]

    name = models.CharField(max_length=150)
    product_type = models.CharField(max_length=30, choices=PRODUCT_TYPES, default="home_purchase")
    interest_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    rate_type = models.CharField(max_length=10, choices=RATE_TYPES, default="fixed")
    min_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    min_tenure_months = models.PositiveIntegerField(default=12)
    max_tenure_months = models.PositiveIntegerField(default=300)
    processing_fee_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    eligibility = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "mortgage_products"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Borrower(TimeStamped):
    EMPLOYMENT = [
        ("employed", "Employed"),
        ("self_employed", "Self Employed"),
        ("business", "Business Owner"),
        ("contract", "Contract"),
        ("other", "Other"),
    ]
    RISK = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
    KYC = [("pending", "Pending"), ("verified", "Verified"), ("rejected", "Rejected")]

    full_name = models.CharField(max_length=200)
    national_id = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    employment_status = models.CharField(max_length=20, choices=EMPLOYMENT, default="employed")
    employer = models.CharField(max_length=200, blank=True)
    gross_monthly_income = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_monthly_income = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    existing_loans = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    dependants = models.PositiveIntegerField(default=0)
    credit_score = models.PositiveIntegerField(null=True, blank=True)
    risk_rating = models.CharField(max_length=10, choices=RISK, default="medium")
    kyc_status = models.CharField(max_length=10, choices=KYC, default="pending")
    branch = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="mortgage_borrowers")
    history = HistoricalRecords(table_name="mortgage_borrowers_history")

    class Meta:
        managed = True
        db_table = "mortgage_borrowers"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class Property(TimeStamped):
    PROPERTY_TYPES = [
        ("residential", "Residential"),
        ("apartment", "Apartment"),
        ("commercial", "Commercial"),
        ("land", "Land"),
        ("mixed_use", "Mixed Use"),
    ]
    borrower = models.ForeignKey(Borrower, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="properties")
    address = models.CharField(max_length=255, blank=True)
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPES, default="residential")
    valuation_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    market_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    ownership_details = models.CharField(max_length=255, blank=True)
    title_deed_no = models.CharField(max_length=120, blank=True)
    valuation_report_ref = models.CharField(max_length=120, blank=True)

    class Meta:
        managed = True
        db_table = "mortgage_properties"
        ordering = ["-id"]

    def __str__(self):
        return self.address or f"Property #{self.pk}"


class MortgageApplication(TimeStamped):
    STATUS = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("under_review", "Under Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("disbursed", "Disbursed"),
        ("closed", "Closed"),
    ]
    application_ref = models.CharField(max_length=40, unique=True, blank=True)
    borrower = models.ForeignKey(Borrower, on_delete=models.CASCADE, related_name="applications")
    product = models.ForeignKey(MortgageProduct, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="applications")
    property = models.ForeignKey(Property, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="applications")
    lead = models.ForeignKey("Lead", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="applications")
    amount_requested = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    purpose = models.CharField(max_length=255, blank=True)
    tenure_months = models.PositiveIntegerField(default=240)
    ltv_ratio = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dti_ratio = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    risk_assessment = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="mortgage_reviews")
    decision_notes = models.TextField(blank=True)
    history = HistoricalRecords(table_name="mortgage_applications_history")

    class Meta:
        managed = True
        db_table = "mortgage_applications"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.application_ref:
            self.application_ref = _ref("APP")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.application_ref


class LoanApproval(TimeStamped):
    DECISION = [("approved", "Approved"), ("rejected", "Rejected"), ("escalated", "Escalated")]
    application = models.ForeignKey(MortgageApplication, on_delete=models.CASCADE, related_name="approvals")
    approver = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="mortgage_approvals")
    approval_limit = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    ltv = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dti = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    decision = models.CharField(max_length=12, choices=DECISION, default="approved")
    decision_date = models.DateField(null=True, blank=True)
    comments = models.TextField(blank=True)

    class Meta:
        managed = True
        db_table = "mortgage_loan_approvals"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.application_id} · {self.decision}"


class MortgageLoan(TimeStamped):
    STATUS = [
        ("active", "Active"),
        ("closed", "Closed"),
        ("default", "Default"),
        ("restructured", "Restructured"),
    ]
    loan_ref = models.CharField(max_length=40, unique=True, blank=True)
    application = models.OneToOneField(MortgageApplication, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="loan")
    borrower = models.ForeignKey(Borrower, on_delete=models.CASCADE, related_name="loans")
    product = models.ForeignKey(MortgageProduct, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="loans")
    principal = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    interest_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    tenure_months = models.PositiveIntegerField(default=240)
    disbursement_date = models.DateField(null=True, blank=True)
    monthly_installment = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    outstanding_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    maturity_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=14, choices=STATUS, default="active")
    history = HistoricalRecords(table_name="mortgage_loans_history")

    class Meta:
        managed = True
        db_table = "mortgage_loans"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.loan_ref:
            self.loan_ref = _ref("LN")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.loan_ref


class RepaymentScheduleItem(models.Model):
    loan = models.ForeignKey(MortgageLoan, on_delete=models.CASCADE, related_name="schedule")
    installment_no = models.PositiveIntegerField()
    due_date = models.DateField(null=True, blank=True)
    payment_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    principal_component = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    interest_component = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)

    class Meta:
        managed = True
        db_table = "mortgage_repayment_schedule"
        ordering = ["loan", "installment_no"]
        unique_together = ("loan", "installment_no")

    def __str__(self):
        return f"{self.loan_id} · #{self.installment_no}"


class Payment(TimeStamped):
    METHODS = [
        ("mpesa", "M-Pesa"),
        ("bank_transfer", "Bank Transfer"),
        ("standing_order", "Standing Order"),
        ("cheque", "Cheque"),
        ("cash", "Cash"),
    ]
    loan = models.ForeignKey(MortgageLoan, on_delete=models.CASCADE, related_name="payments")
    payment_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    principal_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    interest_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    penalty_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    method = models.CharField(max_length=20, choices=METHODS, default="bank_transfer")
    reference = models.CharField(max_length=120, blank=True)
    recorded_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="mortgage_payments")

    class Meta:
        managed = True
        db_table = "mortgage_payments"
        ordering = ["-payment_date", "-id"]

    def __str__(self):
        return f"{self.loan_id} · {self.amount}"


class Fee(TimeStamped):
    FEE_TYPES = [
        ("processing", "Processing"),
        ("legal", "Legal"),
        ("valuation", "Valuation"),
        ("insurance", "Insurance"),
        ("late_payment", "Late Payment"),
    ]
    STATUS = [("pending", "Pending"), ("paid", "Paid"), ("waived", "Waived")]
    application = models.ForeignKey(MortgageApplication, null=True, blank=True,
                                    on_delete=models.CASCADE, related_name="fees")
    loan = models.ForeignKey(MortgageLoan, null=True, blank=True,
                             on_delete=models.CASCADE, related_name="fees")
    fee_type = models.CharField(max_length=20, choices=FEE_TYPES, default="processing")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    charged_date = models.DateField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "mortgage_fees"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.fee_type} · {self.amount}"


class MortgageInsurancePolicy(TimeStamped):
    POLICY_TYPES = [("property", "Property"), ("mortgage_protection", "Mortgage Protection")]
    loan = models.ForeignKey(MortgageLoan, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="insurance_policies")
    policy_type = models.CharField(max_length=24, choices=POLICY_TYPES, default="property")
    policy_no = models.CharField(max_length=120, blank=True)
    provider = models.CharField(max_length=200, blank=True)
    premium = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    start_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "mortgage_insurance_policies"
        ordering = ["-id"]

    def __str__(self):
        return self.policy_no or f"Policy #{self.pk}"


class MortgageDocument(TimeStamped):
    """Document metadata only — binary upload/storage is deferred (see plan)."""
    DOC_TYPES = [
        ("id", "ID Document"),
        ("payslip", "Payslip"),
        ("bank_statement", "Bank Statement"),
        ("title_deed", "Title Deed"),
        ("sale_agreement", "Sale Agreement"),
        ("approval_letter", "Approval Letter"),
        ("contract", "Contract"),
        ("other", "Other"),
    ]
    borrower = models.ForeignKey(Borrower, null=True, blank=True, on_delete=models.CASCADE,
                                 related_name="documents")
    application = models.ForeignKey(MortgageApplication, null=True, blank=True,
                                    on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DOC_TYPES, default="other")
    file_name = models.CharField(max_length=255, blank=True)
    file_url = models.URLField(blank=True)
    uploaded_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="mortgage_documents")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "mortgage_documents"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.file_name or f"Document #{self.pk}"


# ──────────────────────────────────────────────────────────────────────────────
# Leads / field-onboarding CRM
# ──────────────────────────────────────────────────────────────────────────────

class LeadSource(TimeStamped):
    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "mortgage_lead_sources"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Campaign(TimeStamped):
    name = models.CharField(max_length=150)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    target = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "mortgage_campaigns"
        ordering = ["-start_date", "name"]

    def __str__(self):
        return self.name


class FieldAgent(TimeStamped):
    name = models.CharField(max_length=200)
    staff_code = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    team = models.CharField(max_length=120, blank=True)
    branch = models.CharField(max_length=120, blank=True)
    user = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="mortgage_field_agent")
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "mortgage_field_agents"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Lead(TimeStamped):
    STATUS = [
        ("new", "New Lead"),
        ("contacted", "Contacted"),
        ("qualified", "Qualified"),
        ("documents_pending", "Documents Pending"),
        ("application_started", "Application Started"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("converted", "Converted to Customer"),
        ("lost", "Lost"),
    ]
    lead_ref = models.CharField(max_length=40, unique=True, blank=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    source = models.ForeignKey(LeadSource, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="leads")
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="leads")
    field_agent = models.ForeignKey(FieldAgent, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="leads")
    branch = models.CharField(max_length=120, blank=True)
    interested_product = models.ForeignKey(MortgageProduct, null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name="leads")
    estimated_loan_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    property_interest = models.CharField(max_length=255, blank=True)
    income_range = models.CharField(max_length=120, blank=True)
    assigned_to = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="mortgage_leads")
    status = models.CharField(max_length=24, choices=STATUS, default="new")
    converted_application = models.ForeignKey(MortgageApplication, null=True, blank=True,
                                              on_delete=models.SET_NULL, related_name="source_lead")
    history = HistoricalRecords(table_name="mortgage_leads_history")

    class Meta:
        managed = True
        db_table = "mortgage_leads"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.lead_ref:
            self.lead_ref = _ref("LD")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.lead_ref} · {self.full_name}"


class FieldVisit(TimeStamped):
    field_agent = models.ForeignKey(FieldAgent, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="visits")
    team = models.CharField(max_length=120, blank=True)
    visit_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    prospects_reached = models.PositiveIntegerField(default=0)
    leads_collected = models.PositiveIntegerField(default=0)
    qualified_leads = models.PositiveIntegerField(default=0)
    customers_onboarded = models.PositiveIntegerField(default=0)
    applications_started = models.PositiveIntegerField(default=0)
    follow_ups_needed = models.PositiveIntegerField(default=0)
    remarks = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="mortgage_field_visits")

    class Meta:
        managed = True
        db_table = "mortgage_field_visits"
        ordering = ["-visit_date", "-id"]

    def __str__(self):
        return f"{self.location} · {self.visit_date}"


class FollowUp(TimeStamped):
    INTERACTION = [
        ("call", "Call"),
        ("meeting", "Meeting"),
        ("sms", "SMS"),
        ("email", "Email"),
        ("site_visit", "Site Visit"),
        ("documents_requested", "Documents Requested"),
        ("customer_response", "Customer Response"),
    ]
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="follow_ups")
    interaction_type = models.CharField(max_length=24, choices=INTERACTION, default="call")
    notes = models.TextField(blank=True)
    outcome = models.CharField(max_length=255, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    next_action_date = models.DateField(null=True, blank=True)
    done_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="mortgage_follow_ups")

    class Meta:
        managed = True
        db_table = "mortgage_follow_ups"
        ordering = ["-follow_up_date", "-id"]

    def __str__(self):
        return f"{self.lead_id} · {self.interaction_type}"


class CustomerFeedback(TimeStamped):
    borrower = models.ForeignKey(Borrower, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="feedback")
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="feedback")
    rating = models.PositiveSmallIntegerField(null=True, blank=True)  # 1–5
    comments = models.TextField(blank=True)
    challenges = models.TextField(blank=True)
    suggestions = models.TextField(blank=True)
    complaint = models.TextField(blank=True)
    action_taken = models.CharField(max_length=255, blank=True)
    escalated_to = models.CharField(max_length=120, blank=True)

    class Meta:
        managed = True
        db_table = "mortgage_customer_feedback"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Feedback #{self.pk} · {self.rating or '—'}/5"


# ══ Interest Rate Management ═════════════════════════════════════════════════════

class InterestRate(TimeStamped):
    """A named, dated interest rate (e.g. KMRC 9.5%) used to price products/loans."""
    RATE_TYPES = [
        ("kmrc", "KMRC Affordable"),
        ("commercial", "Commercial"),
        ("affordable", "Affordable Housing"),
        ("staff", "Staff Scheme"),
        ("base", "Base Rate"),
    ]
    name = models.CharField(max_length=120)
    rate_type = models.CharField(max_length=16, choices=RATE_TYPES, default="commercial")
    rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)  # annual %
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="mortgage_interest_rates")
    history = HistoricalRecords(table_name="mortgage_interest_rates_history")

    class Meta:
        managed = True
        db_table = "mortgage_interest_rates"
        ordering = ["-effective_date", "-id"]

    def __str__(self):
        return f"{self.name} · {self.rate}%"


# ══ Collections & Recovery ═══════════════════════════════════════════════════════

class CollectionCase(TimeStamped):
    """A recovery case opened against a loan in arrears."""
    STATUS = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("promised", "Promise to Pay"),
        ("recovered", "Recovered"),
        ("legal", "Legal / Recovery"),
        ("written_off", "Written Off"),
    ]
    loan = models.ForeignKey(MortgageLoan, on_delete=models.CASCADE,
                             related_name="collection_cases")
    amount_overdue = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    days_overdue = models.PositiveIntegerField(default=0)
    bucket = models.CharField(max_length=12, blank=True)  # current / 1-30 / 31-60 / 61-90 / 90+
    status = models.CharField(max_length=16, choices=STATUS, default="pending")
    assigned_to = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="mortgage_collection_cases")
    action_taken = models.CharField(max_length=255, blank=True)
    promised_date = models.DateField(null=True, blank=True)
    promised_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        managed = True
        db_table = "mortgage_collection_cases"
        ordering = ["-days_overdue", "-id"]

    def __str__(self):
        return f"Case #{self.pk} · loan {self.loan_id} · {self.status}"


# ══ Notifications ════════════════════════════════════════════════════════════════

class Notification(TimeStamped):
    """A per-user in-app notification raised on key mortgage events."""
    TYPES = [
        ("info", "Info"),
        ("approval", "Approval"),
        ("disbursement", "Disbursement"),
        ("repayment_due", "Repayment Due"),
        ("assignment", "Assignment"),
        ("collection", "Collection"),
        ("lead", "Lead"),
    ]
    user = models.ForeignKey(USER, on_delete=models.CASCADE,
                             related_name="mortgage_notifications")
    type = models.CharField(max_length=16, choices=TYPES, default="info")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        managed = True
        db_table = "mortgage_notifications"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} · {self.title}"
