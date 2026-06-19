"""Client Brief — the HFCB memo an RM prepares per client for director sign-off.

Greenfield, ``managed=True`` so it lives entirely in the default application DB
(the two-DB router never touches it). The model captures every field rendered in
the signed Word memo (see ``views.build_brief_docx``) so the document can be
regenerated faithfully on demand.
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class ClientBrief(models.Model):
    """One client brief authored by a Relationship Manager."""

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_SIGNED = "signed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_SIGNED, "Signed"),
    ]

    # Authoring / ownership
    rm = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="client_briefs",
    )

    # Memo header (the 3x2 table at the top of the document)
    client_name = models.CharField(max_length=255)
    from_party = models.CharField(max_length=255, default="DIRECTOR, RETAIL BANKING")
    to_party = models.CharField(max_length=255, default="GROUP CHIEF EXECUTIVE OFFICER")
    subject = models.CharField(
        max_length=255, blank=True,
        help_text="Defaults to 'CLIENT BRIEF – <client_name>' when left blank.",
    )
    brief_date = models.DateField(default=timezone.now)
    contact_persons = models.TextField(
        blank=True,
        help_text="Client-side contacts, e.g. 'Eng. Joseph Kamau - CEO / CPA. Michael Kimotho – Finance Manager'.",
    )

    # Body
    background = models.TextField(
        blank=True,
        help_text="Background narrative. Separate paragraphs with a blank line.",
    )
    key_responsibilities = models.TextField(
        blank=True,
        help_text="One responsibility per line — rendered as a bulleted list.",
    )
    budget_note = models.TextField(
        blank=True,
        help_text="Budget / revenue paragraph.",
    )
    # [{ "title": "i). Institutional Corporate Account", "body": "..." }, ...]
    opportunities = models.JSONField(
        default=list, blank=True,
        help_text="Ordered list of business opportunities, each {title, body}.",
    )

    # Footer
    prepared_by = models.CharField(max_length=255, blank=True)
    rm_designation = models.CharField(
        max_length=255, blank=True, default="Relationship Manager",
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "client_briefs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Client Brief — {self.client_name}"

    @property
    def display_subject(self):
        return self.subject.strip() or f"CLIENT BRIEF – {self.client_name}"
