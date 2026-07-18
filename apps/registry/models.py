"""Records & Registry — Phase 1: the physical-file custody loop.

Digitises §3 of the CPC Procedures manual (Records Management):
new-file indexing, issue/return via digital movement cards, the
50-file-per-officer cap, and the >4-week overdue clock.

Greenfield, all ``managed=True`` so it lives entirely in the default
application DB — the two-DB router never touches it, and nothing here reads
or writes core-banking (Profits) data.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

# §3.2 policy: "Files issued to an officer will be held for a maximum period of
# four weeks, after which they become overdue."
OVERDUE_DAYS = 28

# §3.2 policy: "no single officer holds many files at a time (maximum 50 files
# per person)."
MAX_OPEN_FILES_PER_BORROWER = 50

# §3.5 retention: "seven years but for mortgage documents and account opening
# forms/cards entire life."
RETENTION_YEARS = 7


def _add_years(d, years):
    """Add whole years to a date, clamping 29 Feb → 28 Feb in non-leap years."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + years)


class FileRecord(models.Model):
    """One physical file held in the registry (§3.1)."""

    TYPE_GENERAL = "general"
    TYPE_LOAN = "loan"
    TYPE_MORTGAGE = "mortgage"
    TYPE_AOF = "aof"  # Account Opening Form / card
    TYPE_CHOICES = [
        (TYPE_GENERAL, "General"),
        (TYPE_LOAN, "Loan"),
        (TYPE_MORTGAGE, "Mortgage"),
        (TYPE_AOF, "Account Opening"),
    ]

    # §3.5 retention: "seven years but for mortgage documents and account
    # opening forms/cards entire life."
    RETENTION_SEVEN_YEAR = "seven_year"
    RETENTION_LIFE = "life"
    RETENTION_CHOICES = [
        (RETENTION_SEVEN_YEAR, "Seven years"),
        (RETENTION_LIFE, "Entire life"),
    ]
    LIFE_RETENTION_TYPES = {TYPE_MORTGAGE, TYPE_AOF}

    STATUS_ACTIVE = "active"        # in the registry, available
    STATUS_ON_LOAN = "on_loan"      # issued to an officer
    STATUS_REDEEMED = "redeemed"    # loan redeemed, pending archive (§3.5)
    STATUS_ARCHIVED = "archived"    # transferred to archives (Phase 2)
    STATUS_DESTROYED = "destroyed"  # pulped per retention policy (Phase 2)
    STATUS_MISSING = "missing"      # not traced at stock-take (Phase 3)
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active — in registry"),
        (STATUS_ON_LOAN, "On loan — issued"),
        (STATUS_REDEEMED, "Redeemed"),
        (STATUS_ARCHIVED, "Archived"),
        (STATUS_DESTROYED, "Destroyed"),
        (STATUS_MISSING, "Missing"),
    ]

    file_no = models.CharField(max_length=64, unique=True, db_index=True)
    customer_name = models.CharField(max_length=255)
    account_no = models.CharField(max_length=64, blank=True, db_index=True)
    file_type = models.CharField(
        max_length=16, choices=TYPE_CHOICES, default=TYPE_GENERAL,
    )
    retention_class = models.CharField(
        max_length=16, choices=RETENTION_CHOICES, blank=True,
        help_text="Auto-set from file type when blank: mortgage/AOF = life, else seven years.",
    )
    opened_on = models.DateField(default=timezone.now)

    # Physical location within the registry.
    current_volume = models.PositiveIntegerField(default=1)
    pocket = models.CharField(
        max_length=64, blank=True,
        help_text="Shelf / pocket location code where the file lives.",
    )

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True,
    )
    notes = models.TextField(blank=True)

    # §3.5: loan redemption starts the retention/archive clock. Redeemed files
    # are separated from active ones before transfer to archives.
    redeemed_on = models.DateField(null=True, blank=True)

    # Archive placement (set when a transfer consignment is received).
    archive_box = models.ForeignKey(
        "ArchiveBox", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="files",
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    # §3.7: set when the original could not be traced and a skeleton file was
    # reconstructed from copies to stand in for it.
    is_skeleton = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_files_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "registry_file"
        ordering = ["file_no"]

    def __str__(self):
        return f"{self.file_no} — {self.customer_name}"

    def save(self, *args, **kwargs):
        if not self.retention_class:
            self.retention_class = (
                self.RETENTION_LIFE
                if self.file_type in self.LIFE_RETENTION_TYPES
                else self.RETENTION_SEVEN_YEAR
            )
        super().save(*args, **kwargs)

    @property
    def open_card(self):
        """The current outstanding movement card, if the file is out."""
        return self.movement_cards.filter(returned_at__isnull=True).first()

    @property
    def retention_base(self):
        """Date the retention clock starts — redemption if known, else opening."""
        return self.redeemed_on or self.opened_on

    @property
    def retention_due_on(self):
        """Date the file becomes eligible for destruction (None = keep for life)."""
        if self.retention_class == self.RETENTION_LIFE:
            return None
        return _add_years(self.retention_base, RETENTION_YEARS)

    @property
    def is_destruction_due(self):
        due = self.retention_due_on
        if due is None or self.status == self.STATUS_DESTROYED:
            return False
        return timezone.now().date() >= due


class MovementCard(models.Model):
    """A digital file-movement card — one issue/return cycle (§3.2 / §3.3).

    Replaces the paper card the borrower signs. ``borrower_ack`` is the digital
    signature captured at issue; ``returned_at`` discharges the borrower.
    """

    CONDITION_OK = "ok"
    CONDITION_TORN = "torn"
    CONDITION_DAMAGED = "damaged"
    CONDITION_CHOICES = [
        (CONDITION_OK, "Good"),
        (CONDITION_TORN, "Torn — repair"),
        (CONDITION_DAMAGED, "Damaged"),
    ]

    file = models.ForeignKey(
        FileRecord, on_delete=models.CASCADE, related_name="movement_cards",
    )
    # The action officer taking custody of the file.
    borrower = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="registry_files_held",
    )
    department = models.CharField(max_length=128, blank=True)
    purpose = models.CharField(max_length=255, blank=True)

    issued_at = models.DateTimeField(default=timezone.now, db_index=True)
    issued_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_files_issued",
    )
    due_at = models.DateTimeField(db_index=True)
    # Digital signature — the borrower acknowledges custody at issue (§3.2:
    # "Users must fill and sign cards before file is issued out.").
    borrower_ack = models.BooleanField(default=False)

    returned_at = models.DateTimeField(null=True, blank=True)
    returned_condition = models.CharField(
        max_length=16, choices=CONDITION_CHOICES, blank=True,
    )
    return_note = models.CharField(max_length=255, blank=True)

    # Escalation bookkeeping (§3.4): stamped when the fortnightly report emails
    # Head of Ops + the requesting unit's HOD so we don't re-escalate endlessly.
    escalated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "registry_movement_card"
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["returned_at", "due_at"]),
        ]

    def __str__(self):
        who = self.borrower.get_full_name().strip() or self.borrower.username
        return f"{self.file.file_no} → {who}"

    def save(self, *args, **kwargs):
        if not self.due_at:
            self.due_at = (self.issued_at or timezone.now()) + timedelta(days=OVERDUE_DAYS)
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.returned_at is None

    @property
    def is_overdue(self):
        return self.is_open and timezone.now() > self.due_at

    @property
    def days_out(self):
        end = self.returned_at or timezone.now()
        return (end - self.issued_at).days

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (timezone.now() - self.due_at).days


# ── Archives: transfer & storage (§3.5) ──────────────────────────────────────

class ArchiveBox(models.Model):
    """A physical storage carton at the archives holding transferred files."""

    code = models.CharField(max_length=64, unique=True, db_index=True)
    location = models.CharField(max_length=128, blank=True)
    consignment = models.ForeignKey(
        "ArchiveConsignment", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="boxes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "registry_archive_box"
        ordering = ["code"]

    def __str__(self):
        return self.code


class ArchiveConsignment(models.Model):
    """A batch of records transferred from a unit/branch to the archives (§3.5).

    Created by the registry when a unit asks to transfer due records; the
    archives officer confirms and *receives* it, which boxes the files and marks
    them archived.
    """

    STATUS_REQUESTED = "requested"
    STATUS_RECEIVED = "received"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_RECEIVED, "Received & archived"),
    ]

    source_unit = models.CharField(max_length=128)
    files = models.ManyToManyField(FileRecord, related_name="consignments", blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_REQUESTED, db_index=True,
    )
    notes = models.TextField(blank=True)

    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_consignments_requested",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_consignments_received",
    )
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "registry_archive_consignment"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Consignment #{self.pk} from {self.source_unit}"


# ── Archives: destruction of records (§3.6) ──────────────────────────────────

class DestructionBatch(models.Model):
    """A list of records due for destruction, gated by three sign-offs (§3.6).

    Originating unit → Head of Operations → COO must all approve before the
    batch can be destroyed (pulped by an authorised vendor), after which the
    vendor's acknowledgement is recorded as a destruction certificate.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DESTROYED = "destroyed"
    STATUS_CERTIFIED = "certified"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending approval"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DESTROYED, "Destroyed"),
        (STATUS_CERTIFIED, "Certified"),
    ]

    reference = models.CharField(max_length=64, blank=True, db_index=True)
    files = models.ManyToManyField(FileRecord, related_name="destruction_batches", blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_destructions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Three-tier sign-off (§3.6 step 1).
    unit_ack_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    unit_ack_at = models.DateTimeField(null=True, blank=True)
    head_ops_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    head_ops_at = models.DateTimeField(null=True, blank=True)
    coo_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    coo_at = models.DateTimeField(null=True, blank=True)

    # Destruction + certificate (§3.6 steps 2–3).
    vendor = models.CharField(max_length=128, blank=True)
    destruction_location = models.CharField(max_length=128, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)
    certificate_ref = models.CharField(max_length=128, blank=True)
    certificate_note = models.TextField(blank=True)

    class Meta:
        managed = True
        db_table = "registry_destruction_batch"
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference or f"Destruction #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.reference:
            # Assign a human reference once the pk exists (persist + reflect it
            # on the instance so the create response carries it).
            self.reference = f"DST-{self.pk:04d}"
            super().save(update_fields=["reference"])

    @property
    def is_fully_approved(self):
        return bool(self.unit_ack_at and self.head_ops_at and self.coo_at)


# ── Stock-take & missing files (§3.7) ────────────────────────────────────────

class StockTake(models.Model):
    """A physical count of the registry against the register (§3.7).

    The registry periodically verifies that every file the register says it
    holds is physically present. A stock-take opens with a scope (which files
    should be on the shelf), officers mark each as sighted, and on close any
    file never sighted is flagged missing and raises an incident.
    """

    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "In progress"),
        (STATUS_CLOSED, "Closed"),
    ]

    title = models.CharField(max_length=128)
    location = models.CharField(
        max_length=128, blank=True,
        help_text="Optional pocket/shelf filter — blank counts the whole registry.",
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True,
    )
    notes = models.TextField(blank=True)

    opened_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_stocktakes_opened",
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_stocktakes_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "registry_stock_take"
        ordering = ["-opened_at"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    # Scope: every file the register still accounts for — on the shelf (active
    # or redeemed) *and* issued out. §3.7 counts issued files too ("the exercise
    # to start with the files being issued on the day the exercise begins"), so
    # a file marked to an officer is verified with that officer rather than
    # assumed present. Archived/destroyed/missing are excluded: they have
    # legitimately left the registry.
    def scope_queryset(self):
        qs = FileRecord.objects.filter(
            status__in=[
                FileRecord.STATUS_ACTIVE,
                FileRecord.STATUS_REDEEMED,
                FileRecord.STATUS_ON_LOAN,
            ],
        )
        if self.location:
            qs = qs.filter(pocket=self.location)
        return qs


class StockTakeItem(models.Model):
    """One file's line in a stock-take — sighted or not (§3.7)."""

    stock_take = models.ForeignKey(
        StockTake, on_delete=models.CASCADE, related_name="items",
    )
    file = models.ForeignKey(
        FileRecord, on_delete=models.CASCADE, related_name="stock_take_items",
    )
    sighted = models.BooleanField(default=False)
    sighted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    sighted_at = models.DateTimeField(null=True, blank=True)
    remark = models.CharField(max_length=255, blank=True)
    # Custody at the moment the count opened. §3.7 step 3 splits untraced files
    # into "marked to officers" vs "not marked to any officer", so the holder is
    # snapshotted here rather than read back later (the card may be returned
    # mid-count). Null = it should have been on the shelf.
    marked_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Officer holding the file when the count opened, if issued out.",
    )

    class Meta:
        managed = True
        db_table = "registry_stock_take_item"
        ordering = ["file__file_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock_take", "file"], name="uniq_stocktake_file",
            ),
        ]

    def __str__(self):
        return f"{self.file.file_no} — {'seen' if self.sighted else 'unseen'}"


class MissingFileIncident(models.Model):
    """A file that could not be traced — raised, investigated, resolved (§3.7).

    Opened when a file is found missing (at stock-take or when an issue/return
    can't locate it). Tracks the search, escalation, and outcome: the file is
    either found or a skeleton file is reconstructed to stand in for it.
    """

    STATUS_OPEN = "open"
    STATUS_FOUND = "found"
    STATUS_SKELETON = "skeleton"     # reconstructed from copies (§3.7)
    STATUS_WRITTEN_OFF = "written_off"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open — under search"),
        (STATUS_FOUND, "Found"),
        (STATUS_SKELETON, "Skeleton reconstructed"),
        (STATUS_WRITTEN_OFF, "Written off"),
    ]

    file = models.ForeignKey(
        FileRecord, on_delete=models.CASCADE, related_name="missing_incidents",
    )
    stock_take = models.ForeignKey(
        StockTake, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="incidents",
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True,
    )
    # Where the file was last accounted for — helps the search (§3.7).
    last_seen = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    # §3.7 step 3: untraced files split into those "marked to officers" and
    # those "not marked to any officer". Null = nobody held it, so it should
    # have been on the shelf and there is no trace to follow — the skeleton
    # path. Set = chase the officer per the overdue follow-up procedure (step 4).
    marked_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_incidents_marked_to",
        help_text="Officer the file was issued to, if it was out at the count.",
    )

    reported_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_incidents_reported",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Resolution.
    resolution_note = models.TextField(blank=True)
    skeleton_file = models.ForeignKey(
        FileRecord, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="skeleton_for_incidents",
        help_text="The reconstructed file created when the original is lost.",
    )
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "registry_missing_incident"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Missing {self.file.file_no} ({self.get_status_display()})"

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN
