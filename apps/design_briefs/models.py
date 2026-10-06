"""Design Briefs — what Marketing has been asked to make, who is making it, and when it lands.

The ask behind this module: the design team wants a board on the office screen
that answers, without anybody having to be asked, "what is on my pipeline
today?". So the design is shaped around three questions:

* **Who asked, and who for?** A brief records the person who raised it
  (``raised_by``) and who it is addressed to (``addressed_to``) separately. The
  requester signs in; the addressee is frequently a team, a branch or an
  external party, so it is text rather than a foreign key.
* **Who is making it, and by when?** One designer and one ``release_date`` at
  all times. A brief with no designer sits in ``new`` and is visible as such —
  the queue is not where work goes to become invisible.
* **Did it satisfy the person who asked?** The designer submits; the requester
  approves or sends it back. ``rework_count`` lives on the brief rather than
  being counted from the timeline, because how often work comes back is the
  number the department reviews, and it must survive archiving.

Closing archives, never deletes: ``archived_at`` is stamped and the row stays.
What the department has produced is its own record.

RBAC is in ``rbac.py``. Every state change goes through ``workflow.py``, so no
transition can happen without an event recorded against it.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

USER = settings.AUTH_USER_MODEL


def _ref() -> str:
    """Short business reference, e.g. ``DB-7C1F9A24``.

    Random rather than sequential, for the same reason as the service desk's:
    a sequential number publishes how much work the department has ever taken
    on, and a gap in it invites a question whose answer is a rolled-back
    transaction.
    """
    return f"DB-{uuid.uuid4().hex[:8].upper()}"


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DesignBriefQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(status__in=DesignBrief.CLOSED_STATUSES)

    def closed(self):
        return self.filter(status__in=DesignBrief.CLOSED_STATUSES)

    def for_designer(self, user):
        return self.filter(assigned_designer=user)

    def overdue(self, today=None):
        """Open, has a release date, and that date has already passed."""
        today = today or timezone.localdate()
        return self.open().filter(release_date__lt=today)


class DesignBrief(TimeStamped):
    """One design request, from raising to release."""

    # -- Workflow ------------------------------------------------------------
    STATUS_NEW = "new"                  # raised, no designer yet
    STATUS_ASSIGNED = "assigned"        # a designer has it, not started
    STATUS_IN_PROGRESS = "in_progress"  # being worked
    STATUS_SUBMITTED = "submitted"      # designer says done, awaiting the requester
    STATUS_REWORK = "rework"            # requester not satisfied; back to the designer
    STATUS_APPROVED = "approved"        # the requester accepted it. Closed.
    STATUS_CANCELLED = "cancelled"      # withdrawn. Closed, and not a failure.

    STATUS = [
        (STATUS_NEW, "Awaiting designer"),
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_SUBMITTED, "Submitted for review"),
        (STATUS_REWORK, "Rework"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    #: Closed means archived. Both are kept; nothing here deletes a brief.
    CLOSED_STATUSES = {STATUS_APPROVED, STATUS_CANCELLED}
    #: The statuses where the ball is in the designer's court.
    DESIGNER_STATUSES = {STATUS_ASSIGNED, STATUS_IN_PROGRESS, STATUS_REWORK}

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"
    PRIORITY = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    # The kinds of work the team actually produces. A closed list rather than
    # free text so the board can group by it and the department can count what
    # it makes in a year.
    ITEM_TYPES = [
        ("poster", "Poster"),
        ("flyer", "Flyer / leaflet"),
        ("banner", "Banner / backdrop"),
        ("social", "Social media post"),
        ("video", "Video / motion"),
        ("brochure", "Brochure"),
        ("email", "Email / newsletter artwork"),
        ("branding", "Branding / identity"),
        ("signage", "Branch signage"),
        ("presentation", "Presentation / deck"),
        ("print", "Print production"),
        ("other", "Other"),
    ]

    reference = models.CharField(max_length=20, unique=True, blank=True, db_index=True)

    # -- The brief itself ----------------------------------------------------
    #: What is being asked for, in the requester's words. The board's headline.
    design_item = models.CharField(
        max_length=200,
        help_text="The design item requested, e.g. 'Diaspora mortgage flyer'.")
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES, default="other")
    brief = models.TextField(
        blank=True,
        help_text="The briefing: what it is for, the message, sizes, copy, references.")

    #: The department the request comes FROM. Free text, because the bank's
    #: department names change more often than a lookup table gets maintained,
    #: and a brief must never be unraisable because a name is missing from one.
    department = models.CharField(max_length=120, db_index=True)

    # "From" and "to" are deliberately different shapes — see the module docstring.
    raised_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_briefs_raised",
        help_text="Who the brief is from. Taken from the signed-in user.")
    raised_by_name = models.CharField(
        max_length=150, blank=True,
        help_text="Snapshot of the requester's name, so a removed account does "
                  "not erase who asked.")
    addressed_to = models.CharField(
        max_length=150,
        help_text="Who the brief is to — a person, team or audience.")

    priority = models.CharField(max_length=10, choices=PRIORITY, default=PRIORITY_NORMAL)
    status = models.CharField(
        max_length=15, choices=STATUS, default=STATUS_NEW, db_index=True)

    #: When the finished item is needed. The single date the board sorts on.
    release_date = models.DateField(
        null=True, blank=True, db_index=True,
        help_text="Target release date for the finished item.")

    # -- Assignment ----------------------------------------------------------
    # Only a marketing admin sets this (``rbac.can_assign``). A designer cannot
    # take work for themselves or hand it to a colleague: who is doing what is
    # the department's decision, and that is the whole point of the board.
    assigned_designer = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_briefs_assigned")
    assigned_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_briefs_allocated")
    assigned_at = models.DateTimeField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # -- Rework --------------------------------------------------------------
    # Kept on the row, not counted from the events, because this is the figure
    # the department reviews and it has to survive archiving.
    rework_count = models.PositiveSmallIntegerField(default=0)
    last_rework_at = models.DateTimeField(null=True, blank=True)
    last_rework_reason = models.TextField(blank=True)

    # -- Closure -------------------------------------------------------------
    # Recorded so that "the designer says it is done" and "the person who asked
    # agrees" can never be the same fact. ``workflow.approve`` enforces it.
    approved_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_briefs_approved")
    approved_at = models.DateTimeField(null=True, blank=True)
    satisfaction = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="1-5, given by whoever raised the brief.")
    closing_note = models.TextField(blank=True)

    #: Stamped when the brief closes. The presence of this is what "archived"
    #: means; nothing in this module deletes a brief.
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    history = HistoricalRecords(table_name="design_brief_history")
    objects = DesignBriefQuerySet.as_manager()

    class Meta:
        db_table = "design_brief"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["assigned_designer", "status"]),
            models.Index(fields=["raised_by", "-created_at"]),
            models.Index(fields=["release_date"]),
            models.Index(fields=["department", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} - {self.design_item}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = _ref()
        if self.raised_by_id and not self.raised_by_name:
            self.raised_by_name = (
                self.raised_by.get_full_name() or self.raised_by.username)
        return super().save(*args, **kwargs)

    # -- Derived state the board reads ---------------------------------------

    @property
    def is_closed(self) -> bool:
        return self.status in self.CLOSED_STATUSES

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def days_to_release(self):
        """Whole days until the release date. Negative once it has passed.

        ``None`` when no date was given, which the board shows as "no date" —
        never as zero, because a brief with no deadline is not a brief due today.
        """
        if not self.release_date:
            return None
        return (self.release_date - timezone.localdate()).days

    @property
    def is_overdue(self) -> bool:
        d = self.days_to_release
        return (not self.is_closed) and d is not None and d < 0

    @property
    def was_reworked(self) -> bool:
        return self.rework_count > 0


class BriefEvent(models.Model):
    """One step in a brief's life. Written only by ``workflow``.

    The timeline exists so that "nobody told me" and "it was never assigned"
    are answerable questions rather than arguments.
    """

    KIND_RAISED = "raised"
    KIND_ASSIGNED = "assigned"
    KIND_REASSIGNED = "reassigned"
    KIND_STARTED = "started"
    KIND_SUBMITTED = "submitted"
    KIND_REWORK = "rework"
    KIND_APPROVED = "approved"
    KIND_CANCELLED = "cancelled"
    KIND_REOPENED = "reopened"
    KIND_NOTE = "note"
    KIND_EDITED = "edited"
    KIND_PROOF = "proof"
    KIND_COMMENT = "comment"

    KIND = [
        (KIND_RAISED, "Raised"),
        (KIND_ASSIGNED, "Designer assigned"),
        (KIND_REASSIGNED, "Reassigned"),
        (KIND_STARTED, "Work started"),
        (KIND_SUBMITTED, "Submitted for review"),
        (KIND_REWORK, "Rework requested"),
        (KIND_APPROVED, "Approved"),
        (KIND_CANCELLED, "Cancelled"),
        (KIND_REOPENED, "Reopened from archive"),
        (KIND_NOTE, "Note"),
        (KIND_EDITED, "Brief edited"),
        (KIND_PROOF, "Artwork uploaded"),
        (KIND_COMMENT, "Comment"),
    ]

    brief = models.ForeignKey(
        DesignBrief, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=15, choices=KIND)
    actor = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_brief_events")
    actor_name = models.CharField(max_length=150, blank=True)
    note = models.TextField(blank=True)
    # The status either side of the step, so the timeline reads without having
    # to be replayed from the start.
    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15, blank=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "design_brief_event"
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["brief", "at"])]

    def __str__(self):
        return f"{self.brief_id} {self.kind} @ {self.at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.actor_id and not self.actor_name:
            self.actor_name = self.actor.get_full_name() or self.actor.username
        return super().save(*args, **kwargs)


class BriefProof(models.Model):
    """One version of the artwork, as submitted for review.

    This is what turns the board from a list of titles into a design board: the
    card shows the work, not just its name. A design team recognises artwork
    faster than it reads a heading.

    **Only a downscaled preview and a thumbnail are stored, never the original.**
    See ``images.py`` for why — there is no volume for uploads and the database
    is not an asset manager. ``source_url`` is where the full-resolution file
    actually lives.

    One row per round, never overwritten: v1 and v2 both stay, so "what did we
    change after they sent it back" is answerable rather than argued about.
    """

    #: Per brief, so a long rework history cannot grow without limit.
    MAX_PER_BRIEF = 24

    brief = models.ForeignKey(
        DesignBrief, on_delete=models.CASCADE, related_name="proofs")
    #: 1, 2, 3 … assigned by ``workflow.add_proof`` inside the transaction.
    version = models.PositiveSmallIntegerField()

    preview = models.BinaryField(editable=False)
    preview_content_type = models.CharField(max_length=40, default="image/jpeg")
    thumbnail = models.BinaryField(editable=False)
    thumbnail_content_type = models.CharField(max_length=40, default="image/jpeg")
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)

    #: What was uploaded, kept so the record is honest about what the preview
    #: was made from.
    original_name = models.CharField(max_length=200, blank=True)
    original_bytes = models.PositiveIntegerField(default=0)

    #: Where the print/production file lives. The point of not storing it here.
    source_url = models.URLField(max_length=500, blank=True)
    note = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_proofs")
    uploaded_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "design_brief_proof"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["brief", "version"], name="design_proof_version_unique"),
        ]
        indexes = [models.Index(fields=["brief", "-version"])]

    def __str__(self):
        return f"{self.brief_id} proof v{self.version}"

    def save(self, *args, **kwargs):
        if self.uploaded_by_id and not self.uploaded_by_name:
            self.uploaded_by_name = (
                self.uploaded_by.get_full_name() or self.uploaded_by.username)
        return super().save(*args, **kwargs)


class BriefComment(models.Model):
    """Feedback on a brief, and optionally on one version of the artwork.

    Separate from ``BriefEvent``: an event is a step the system recorded, a
    comment is something a person chose to say. Mixing them means a timeline
    where "assigned to Grace" and "the logo is the old mark" carry the same
    weight.

    ``proof`` pins a comment to the version it is about, so feedback given on v1
    still reads correctly after v2 lands. With ``x``/``y`` set it is pinned to a
    *place* on that version as well - the markup every proofing tool has, and
    the difference between "the logo is wrong" and an arrow on the logo.
    """

    #: Positions are FRACTIONS of the stored preview (0.0 - 1.0), never pixels.
    #: The preview is itself a downscale and the browser renders it at whatever
    #: width the layout gives it, so a pixel offset would land in the wrong
    #: place on every screen but the one it was drawn on. A fraction survives
    #: both the downscale and the viewport.

    brief = models.ForeignKey(
        DesignBrief, on_delete=models.CASCADE, related_name="comments")
    proof = models.ForeignKey(
        BriefProof, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="comments")
    body = models.TextField()

    # ── Markup ───────────────────────────────────────────────────────────────
    #: Top-left of the mark, as a fraction of the preview. Both or neither.
    x = models.FloatField(null=True, blank=True)
    y = models.FloatField(null=True, blank=True)
    #: Optional box. Absent means a point pin, which is most feedback.
    w = models.FloatField(null=True, blank=True)
    h = models.FloatField(null=True, blank=True)

    #: Markup gets answered and closed off, the way it does in a proofing tool.
    #: A general comment can be resolved too - there is no reason it cannot be.
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_comments_resolved")

    author = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_brief_comments")
    author_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "design_brief_comment"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["brief", "created_at"]),
            models.Index(fields=["proof", "created_at"]),
        ]

    def __str__(self):
        where = f" @{self.x:.2f},{self.y:.2f}" if self.is_markup else ""
        return f"{self.brief_id} comment by {self.author_name}{where}"

    @property
    def is_markup(self) -> bool:
        """Pinned to a place on the artwork, rather than to the brief."""
        return self.x is not None and self.y is not None

    def save(self, *args, **kwargs):
        if self.author_id and not self.author_name:
            self.author_name = self.author.get_full_name() or self.author.username
        return super().save(*args, **kwargs)


class BriefDeliverable(models.Model):
    """One item the brief has to produce — a size, a format, a placement.

    A single brief is usually several artefacts: an Instagram square, a story,
    an A4 print, an email header. Modelling those as child briefs would double
    the board's complexity for a team of three designers, so they are a
    checklist on the brief instead: enough that nothing is forgotten, without a
    second workflow to run.
    """

    MAX_PER_BRIEF = 30

    brief = models.ForeignKey(
        DesignBrief, on_delete=models.CASCADE, related_name="deliverables")
    label = models.CharField(max_length=160)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="design_deliverables_done")
    #: Kept explicit so the list reads in the order it was written, not by id.
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "design_brief_deliverable"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["brief", "order"])]

    def __str__(self):
        return f"{self.brief_id} · {self.label}"
