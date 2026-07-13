from django.db import models
from simple_history.models import HistoricalRecords


class RightsIssueApplication(models.Model):
    STATUS_CHOICES = [
        ("Submitted", "Submitted"),
        ("Under Review", "Under Review"),
        ("Allotted", "Allotted"),
        ("Partially Allotted", "Partially Allotted"),
        ("Rejected", "Rejected"),
        ("Refunded", "Refunded"),
    ]
    PAYMENT_STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Received", "Received"),
        ("Bounced", "Bounced"),
    ]

    application_number = models.CharField(max_length=100, unique=True, blank=True, null=True)
    applicant_name = models.CharField(max_length=255)
    national_id = models.CharField(max_length=50, blank=True, null=True)
    cds_account = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    existing_shares = models.BigIntegerField(default=0)
    rights_entitlement = models.BigIntegerField(default=0)
    rights_applied = models.BigIntegerField(default=0)
    additional_shares_applied = models.BigIntegerField(default=0)
    share_price = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    amount_payable = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    amount_paid = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    payment_status = models.CharField(choices=PAYMENT_STATUS_CHOICES, max_length=20, default="Pending")
    payment_reference = models.CharField(max_length=255, blank=True, null=True)
    payment_date = models.DateField(blank=True, null=True)
    shares_allotted = models.BigIntegerField(default=0)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status = models.CharField(choices=STATUS_CHOICES, max_length=20, default="Submitted")
    application_date = models.DateField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)
    input_user = models.CharField(max_length=100, default="me")
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        managed = True
        db_table = "hf_rights_issue_applications"
        ordering = ["-application_date"]

    def __str__(self):
        return f"{self.applicant_name} - {self.application_number}"


class SecurityDetail(models.Model):
    """
    Model representing detailed information about a security account.

    This model stores detailed information about an account holder's security, including personal details,
    investment information, and relationship manager details.
    
    Attributes:
        security (str): Name of the security.
        shareholders_no (int): Number of shareholders associated with the security.
        account_number (str): Unique identifier for the account (account number).
        investor_category (str): Category/type of the investor (e.g., individual, corporate).
        tax_category (str): Tax category associated with the account (e.g., resident, non-resident).
        account_name (str): Name of the account holder.
        id_passport_customer_number (str): ID, Passport, or Customer number associated with the account.
        telephone_number (str): Contact telephone number for the account holder.
        statement_email_address (str): Email address used to send account statements.
        country (str): Country of the account holder.
        instrument_type (str): Type of financial instrument (e.g., equity, bond).
        quantity (Decimal): Quantity of the instrument held.
        allocation_rm (str): Relationship manager responsible for the account.
        pf_number_rm_code_name (str): PF number or RM code/name for the relationship manager.
        role (str): Role of the account holder within the organization (e.g., investor, admin).
        hf_customer (bool): Whether the account is held by a high-frequency customer.
        cif (str): Customer Information File (CIF) associated with the account.
        hf_segmentation (str): Segmentation category for high-frequency customers.
        hf_phone_number (str): Phone number specific for high-frequency customer contact.
        hf_email (str): Email address specific for high-frequency customer contact.
        location (str): Location of the account holder.
        rm_managed (str): Indicates if the account is managed by an RM.
        matrix_criteria (str): Criteria for inclusion in a specific matrix.
    """
    
    # Fields
    security = models.CharField(
        max_length=100, 
        null=True, 
        blank=False, 
        help_text="Name of the security (e.g., stock name, bond name)."
    )
    shareholders_no = models.CharField(
        max_length=100,
        null=True, 
        blank=True, 
        help_text="Number of shareholders linked to the security."
    )
    account_number = models.CharField(
        max_length=50, 
        null=False, 
        blank=False, 
        #unique=True,  # Ensure uniqueness of account numbers
        help_text="Unique account number assigned to the account holder."
    )
    investor_category = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Investor category (e.g., individual, corporate, institutional)."
    )
    tax_category = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Tax category of the account holder (e.g., resident, non-resident)."
    )
    account_name = models.CharField(
        max_length=255, 
        null=False, 
        blank=False, 
        help_text="Name of the account holder (person or entity)."
    )
    id_passport_customer_number = models.CharField(
        max_length=100, 
        null=False, 
        blank=False, 
        help_text="ID/Passport/Customer number used for identification."
    )
    telephone_number = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        help_text="Telephone number for communication with the account holder."
    )
    statement_email_address = models.EmailField(
        null=True, 
        blank=True, 
        help_text="Email address where account statements are sent."
    )
    country = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Country where the account holder is based."
    )
    instrument_type = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Type of financial instrument associated with the account (e.g., equity, bond)."
    )
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        help_text="Quantity of the financial instrument held by the account holder."
    )
    allocation_rm = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Name or code of the relationship manager responsible for the account."
    )
    pf_number_rm_code_name = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="PF number or RM code/name assigned to the relationship manager."
    )
    role = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="Role of the account holder (e.g., investor, admin, beneficiary)."
    )
    hf_customer = models.BooleanField(
        default=False, 
        help_text="Indicates if the account belongs to a high-frequency customer (True/False)."
    )
    cif = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Customer Information File (CIF) identifier associated with the account."
    )
    # New fields
    hf_segmentation = models.CharField(max_length=100, null=True, blank=True, help_text="Segmentation category for high-frequency customers.")
    hf_phone_number = models.CharField(max_length=100, null=True, blank=True, help_text="Phone number specific for high-frequency customer contact.")
    hf_email = models.EmailField(null=True, blank=True, help_text="Email address specific for high-frequency customer contact.")
    location = models.CharField(max_length=100, null=True, blank=True, help_text="Location of the account holder.")
    rm_managed = models.CharField(max_length=100, null=True, blank=True, help_text="Indicates if the account is managed by an RM.")
    matrix_criteria = models.CharField(max_length=100, null=True, blank=True, help_text="Criteria for inclusion in a specific matrix.")
    # New fields post rights issue closure
    branch = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Branch of the account."
    )
    segment = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Segment category."
    )
    stock_broker_agent_name = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        help_text="Name of the stock broker or agent."
    )
    pal_no = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="PAL number associated with the account."
    )
    current_shares = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        help_text="Current number of shares held."
    )
    rights = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        help_text="Rights associated with the account."
    )
    mobile_no = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="Primary mobile number."
    )
    additional_mobile_no = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="Additional mobile number."
    )
    additional_hfc_phone = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="Additional phone number for HFC contacts."
    )
    other_alternate_phone = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="Other alternate phone number."
    )
    additional_email_1 = models.EmailField(
        null=True, 
        blank=True, 
        help_text="Additional email address 1."
    )
    other_additional_email_2 = models.EmailField(
        null=True, 
        blank=True, 
        help_text="Other additional email address 2."
    )
    other_additional_email_3 = models.EmailField(
        null=True, 
        blank=True, 
        help_text="Other additional email address 3."
    )
    other_additional_email_4 = models.EmailField(
        null=True, 
        blank=True, 
        help_text="Other additional email address 4."
    )
    names = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        help_text="Full names associated with the account."
    )
    mobile = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="Mobile contact number."
    )
    rights_taken = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        help_text="Details of rights taken."
    )
    due = models.DecimalField(
        max_digits=50, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        help_text="Amount due."
    )
    paid = models.DecimalField(
        max_digits=50, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        help_text="Amount paid."
    )
    balance = models.DecimalField(
        max_digits=50, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        help_text="Remaining balance."
    )
    email = models.EmailField(
        null=True, 
        blank=True, 
        help_text="Primary email address."
    )


    # Metadata
    class Meta:
        db_table = 'security_detail'  # Explicit table name
        verbose_name = 'Security Detail'
        verbose_name_plural = 'Security Details'
        managed = False  # Existing shared table — read via ORM, write via raw SQL

    def __str__(self):
        """
        String representation of the SecurityDetail object.

        Returns:
            str: Account name followed by the account number.
        """
        return f"{self.account_name} - {self.account_number}"
