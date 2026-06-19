from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from simple_history.models import HistoricalRecords


BRANCH_CHOICES = [
    ("KISII BRANCH", "KISII BRANCH"),
    ("NYERI BRANCH", "NYERI BRANCH"),
    ("BURUBURU BRANCH", "BURUBURU BRANCH"),
    ("NYALI BRANCH", "NYALI BRANCH"),
    ("GILL HOUSE BRANCH", "GILL HOUSE BRANCH"),
    ("NANYUKI BRANCH", "NANYUKI BRANCH"),
    ("SAMEER BRANCH", "SAMEER BRANCH"),
    ("NAKURU BRANCH", "NAKURU BRANCH"),
    ("HEAD OFFICE BRANCH", "HEAD OFFICE BRANCH"),
    ("MACHAKOS BRANCH", "MACHAKOS BRANCH"),
    ("NAIVASHA BRANCH", "NAIVASHA BRANCH"),
    ("KISUMU BRANCH", "KISUMU BRANCH"),
    ("HURLINGHAM BRANCH", "HURLINGHAM BRANCH"),
    ("TRM BRANCH", "TRM BRANCH"),
    ("KITENGELA BRANCH", "KITENGELA BRANCH"),
    ("ELDORET BRANCH", "ELDORET BRANCH"),
    ("KENYATTA BRANCH", "KENYATTA BRANCH"),
    ("REHANI BRANCH", "REHANI BRANCH"),
    ("HF WHIZZ BRANCH", "HF WHIZZ BRANCH"),
    ("MOMBASA BRANCH", "MOMBASA BRANCH"),
    ("RIVERROAD BRANCH", "RIVERROAD BRANCH"),
    ("EMBU BRANCH", "EMBU BRANCH"),
    ("MERU BRANCH", "MERU BRANCH"),
    ("THIKA BRANCH", "THIKA BRANCH"),
    ("KOMAROCK BRANCH", "KOMAROCK BRANCH"),
    ("WESTLANDS BRANCH", "WESTLANDS BRANCH"),
    ("RONGAI BRANCH", "RONGAI BRANCH"),
]

SEGMENT_CHOICES = [
    ("FINANCIAL INSTITUTIONS", "FINANCIAL INSTITUTIONS"),
    ("INSTITUTIONAL BANKING", "INSTITUTIONAL BANKING"),
    ("INTERNAL ACCOUNTS", "INTERNAL ACCOUNTS"),
    ("PB", "PB"),
    ("SCHEME", "SCHEME"),
    ("BUSINESS BANKING", "BUSINESS BANKING"),
    ("COMMERCIAL", "COMMERCIAL"),
    ("ULTIMATE", "ULTIMATE"),
    ("PROJECT FINANCE", "PROJECT FINANCE"),
    ("VIRTUAL", "VIRTUAL"),
    ("STAFF", "STAFF"),
    ("DIASPORA", "DIASPORA"),
    ("unsegmented", "unsegmented"),
]


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    sales_code = models.TextField(blank=True, null=True)
    branch = models.CharField(choices=BRANCH_CHOICES, max_length=32, blank=True, null=True)
    segment = models.CharField(choices=SEGMENT_CHOICES, max_length=32, blank=True, null=True)

    def __str__(self):
        return str(self.user.username)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        p = Profile.objects.create(user=instance)
        message = (
            f"Hi {p.user.first_name},\n\nBelow are the login details:\n\n"
            f"\t Username: {p.user.username}\n\n"
            f"\t Password: NenosirI@39HATAri\n\n"
            f"To access the site click http://128.2.1.25:5400/login."
        )
        html_message = f"""
        <p>Hi {p.user.first_name},</p>
        <p>Below are the login details:</p>
        <p><strong>Username</strong>: {p.user.username}</p>
        <p><strong>Password</strong>: NenosirI@39HATAri</p>
        <p>To access the site click <a href="http://128.2.1.25:5400/login">Portfolio Tool</a></p>
        """
        try:
            send_mail(
                subject="Account Creation",
                message=message,
                from_email="reports.analytics@hfgroup.co.ke",
                recipient_list=[p.user.email],
                html_message=html_message,
            )
        except Exception:
            pass


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, "profile"):
        instance.profile.save()


class RetailAllocatedPortfolio(models.Model):
    cust_id = models.IntegerField(blank=True, null=True)
    customer_name = models.TextField(blank=True, null=True)
    sales_code = models.TextField(blank=True, null=True)
    rm_name = models.TextField(blank=True, null=True)
    email = models.TextField(blank=True, null=True)
    branch = models.IntegerField(blank=True, null=True)
    main_segment = models.CharField(max_length=100, blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "retail_allocated_portfolio"


class HfCustomer(models.Model):
    cust_id = models.DecimalField(primary_key=True, max_digits=65535, decimal_places=65535)
    latin_surname = models.TextField(blank=True, null=True)
    mobile_tel = models.TextField(blank=True, null=True)
    id_no = models.TextField(blank=True, null=True)
    e_mail = models.TextField(blank=True, null=True)
    fd = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    ca = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    internal = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    mobile = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    mortagage = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    sa = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    product_map = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    asset_finance = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    cash_cover = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    ipf = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    overdraft = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    project = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    staff = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    trade = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    unsecured = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    registered_mobile = models.BooleanField(blank=True, null=True)
    total_depost_balance = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    total_loans = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    total_revenue = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    segment = models.TextField(blank=True, null=True)
    active = models.BooleanField(blank=True, null=True)
    branch = models.TextField(blank=True, null=True)
    banking_segment = models.TextField(blank=True, null=True)
    branch_code = models.TextField(blank=True, null=True)
    date_time_created = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "hf_customer"


class Prospects(models.Model):
    PRODUCT_CHOICES = [("Deposit", "Deposit"), ("Loan", "Loan")]
    STATUS_CHOICES = [("Work in Progress", "Work in Progress"), ("Hot Lead", "Hot Lead")]

    national_Id = models.CharField(max_length=32)
    firstName = models.TextField(blank=True, null=True)
    lastName = models.TextField(blank=True, null=True)
    booked = models.DateField(default=date.today)
    product = models.CharField(choices=PRODUCT_CHOICES, max_length=32)
    status = models.CharField(choices=STATUS_CHOICES, max_length=32)
    sales_code = models.TextField(blank=True, null=True)

    def __str__(self):
        return str(self.national_Id)

    class Meta:
        managed = True
        db_table = "portfolio_management_prospects"


class Feedback(models.Model):
    CONTACT_CHOICES = [
        ("Customer Visit", "Customer Visit"),
        ("Product Inquiry", "Product Inquiry"),
        ("Sales", "Sales"),
        ("Complaint", "Complaint"),
        ("NPL", "NPL"),
        ("NPS", "NPS"),
    ]
    PRODUCT_TYPE_CHOICES = [("Deposit", "Deposit"), ("Loan", "Loan"), ("Both", "Both")]
    LEAD_CHOICES = [("Active", "Active"), ("Closed", "Closed")]

    cust_id = models.BigIntegerField()
    sales_code = models.TextField(blank=True, null=True)
    date = models.DateField(default=date.today)
    category = models.CharField(choices=CONTACT_CHOICES, max_length=32)
    product_type = models.CharField(choices=PRODUCT_TYPE_CHOICES, max_length=32)
    lead = models.CharField(choices=LEAD_CHOICES, max_length=32)
    verbatim = models.TextField(max_length=1000)
    history = HistoricalRecords()

    def __str__(self):
        return str(self.category)

    class Meta:
        managed = True
        db_table = "portfolio_management_feedback"


class PortfolioRmDepositTrends(models.Model):
    id = models.IntegerField(blank=True, primary_key=True)
    product_type = models.CharField(max_length=100, blank=True, null=True)
    sales_code = models.TextField(blank=True, null=True)
    dates_eom = models.DateTimeField(blank=True, null=True)
    volume = models.BigIntegerField(blank=True, null=True)
    number_of_customers = models.BigIntegerField(blank=True, null=True)
    value = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "portfolio_rm_deposit_trends"


class PortfolioRmRevenue(models.Model):
    sales_code = models.TextField(blank=True, null=True)
    income_category = models.CharField(max_length=100, blank=True, null=True)
    value = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "portfolio_rm_revenue"
        unique_together = (("sales_code", "income_category", "value"),)


class Accounts(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField()
    account_no = models.CharField(max_length=100)
    account_name = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    current_balance = models.FloatField(blank=True, null=True)
    open_date = models.DateTimeField()
    close_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    opening_branch = models.CharField(max_length=100)
    opened_by = models.CharField(max_length=100, blank=True, null=True)
    current_branch = models.CharField(max_length=100, blank=True, null=True)
    changed_by = models.CharField(max_length=100, blank=True, null=True)
    interest_rate = models.FloatField(blank=True, null=True)
    account_status = models.CharField(max_length=100, blank=True, null=True)
    is_transacting_account = models.BooleanField()
    last_transaction_date = models.DateTimeField(blank=True, null=True)
    product_type = models.CharField(max_length=100)
    interest = models.FloatField(blank=True, null=True)
    interest_start_date = models.DateTimeField(blank=True, null=True)
    interest_end_date = models.DateTimeField(blank=True, null=True)
    eom_date = models.DateTimeField(blank=True, null=True)
    date_created = models.DateTimeField(blank=True, null=True)
    account_type = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "accounts"


class AccountsHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField()
    account_no = models.CharField(max_length=100)
    account_name = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    current_balance = models.FloatField(blank=True, null=True)
    open_date = models.DateField()
    close_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    opening_branch = models.CharField(max_length=100)
    opened_by = models.CharField(max_length=100, blank=True, null=True)
    current_branch = models.CharField(max_length=100, blank=True, null=True)
    changed_by = models.CharField(max_length=100, blank=True, null=True)
    interest_rate = models.FloatField(blank=True, null=True)
    account_status = models.CharField(max_length=100, blank=True, null=True)
    is_transacting_account = models.BooleanField()
    last_transaction_date = models.DateField(blank=True, null=True)
    product_type = models.CharField(max_length=100)
    interest = models.FloatField(blank=True, null=True)
    interest_start_date = models.DateField(blank=True, null=True)
    interest_end_date = models.DateField(blank=True, null=True)
    eom_date = models.DateField(blank=True, null=True)
    date_created = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "accounts_history"


class Loans(models.Model):
    id = models.BigAutoField(primary_key=True)
    cust_id = models.BigIntegerField()
    loan_account_no = models.CharField(max_length=20)
    loan_open_date = models.DateTimeField(blank=True, null=True)
    account_no = models.CharField(max_length=20)
    loan_product = models.CharField(max_length=20)
    currency = models.CharField(max_length=20)
    euro_book_balance = models.FloatField()
    interest = models.FloatField()
    facility_fees = models.FloatField()
    first_drawn_down_amount = models.FloatField(blank=True, null=True)
    first_drawn_down_date = models.DateTimeField(blank=True, null=True)
    capital_balance_amount = models.FloatField(blank=True, null=True)
    previous_installment_date = models.DateTimeField(blank=True, null=True)
    next_installment_date = models.DateTimeField(blank=True, null=True)
    last_transaction_date = models.DateTimeField(blank=True, null=True)
    total_commisions = models.FloatField(blank=True, null=True)
    total_penalties = models.FloatField(blank=True, null=True)
    total_interest_collected = models.FloatField(blank=True, null=True)
    open_date = models.DateTimeField(blank=True, null=True)
    close_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, blank=True, null=True)
    penalty_interest_rate = models.FloatField(blank=True, null=True)
    branch = models.IntegerField(blank=True, null=True)
    sector = models.CharField(max_length=100, blank=True, null=True)
    total_arrears = models.FloatField(blank=True, null=True)
    days_in_arrears = models.IntegerField(blank=True, null=True)
    capital_balance = models.FloatField(blank=True, null=True)
    interest_arrears = models.FloatField(blank=True, null=True)
    account_officer = models.CharField(max_length=20, blank=True, null=True)
    delay_officer = models.CharField(max_length=30, blank=True, null=True)
    last_month_interest_debit_amount = models.FloatField(blank=True, null=True)
    insurance = models.FloatField(blank=True, null=True)
    installment_amount = models.FloatField(blank=True, null=True)
    frequency_in_months = models.IntegerField(blank=True, null=True)
    total_capital_balance = models.FloatField(blank=True, null=True)
    charges = models.FloatField(blank=True, null=True)
    interest_on_capital = models.FloatField(blank=True, null=True)
    interest_on_arrears = models.FloatField(blank=True, null=True)
    total_capital_debited = models.FloatField(blank=True, null=True)
    interest_credit = models.FloatField(blank=True, null=True)
    principle = models.FloatField(blank=True, null=True)
    total_interest_credited = models.FloatField(blank=True, null=True)
    overdue_days = models.IntegerField(blank=True, null=True)
    eom_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "loans"


class OTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def is_expired(self):
        return self.expires_at < timezone.now()

    def __str__(self):
        return f"{self.user.username} OTP ({self.otp}) - Expires at: {self.expires_at}"

    class Meta:
        managed = True
        db_table = "auth_otp"


class LoansMomIFRSMovement(models.Model):
    lns_account = models.CharField(max_length=100)
    prev_gross = models.FloatField(blank=True, null=True)
    current_gross = models.FloatField(blank=True, null=True)
    prev_ifrs = models.FloatField(blank=True, null=True)
    current_ifrs = models.FloatField(blank=True, null=True)
    prev_grade = models.CharField(max_length=50, blank=True, null=True)
    current_grade = models.CharField(max_length=50, blank=True, null=True)
    movt_in_gross = models.FloatField(blank=True, null=True)
    movt_in_ifrs = models.FloatField(blank=True, null=True)
    narration_status = models.CharField(max_length=255, blank=True, null=True)
    write_off_amount = models.FloatField(blank=True, null=True)
    adjusted_opening_ifrs = models.FloatField(blank=True, null=True)
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    pl_charge = models.FloatField(blank=True, null=True)
    cust_code = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    segment = models.CharField(max_length=100, blank=True, null=True)
    int_adj = models.FloatField(blank=True, null=True)
    cust_code_strategy = models.CharField(max_length=100, blank=True, null=True)
    new_segmentation = models.CharField(max_length=100, blank=True, null=True)
    branch = models.CharField(max_length=100, blank=True, null=True)
    branch2 = models.CharField(max_length=100, blank=True, null=True)
    comments = models.TextField(blank=True, null=True)
    increase_writeback = models.CharField(max_length=100, blank=True, null=True)
    product = models.CharField(max_length=100, blank=True, null=True)
    product_desc = models.CharField(max_length=255, blank=True, null=True)
    eom_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "loans_mom_ifrs_movement"
        indexes = [
            models.Index(fields=["lns_account"], name="idx_lns_account"),
            models.Index(fields=["eom_date"], name="idx_eom_date"),
        ]
