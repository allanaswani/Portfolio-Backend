"""Surfaces — a dashboard somebody asked for in plain language.

The bank already has fixed dashboards built by developers. A surface is the
other kind: a person describes the view they need, Claude designs it against
the live warehouse tools, and it is kept so the team can open it again.

The important property is that **Claude designs the layout once**. Every panel
records the tool and arguments that produced it, so refreshing a surface re-runs
those tools directly with no model call. That keeps a surface live and free to
refresh, and stops it redesigning itself into something different each time
somebody looks at it — which would make it useless as a thing a team relies on.
"""

from django.conf import settings
from django.db import models


class Surface(models.Model):
    """A generated, live dashboard: its request, its layout, its owner."""

    class Visibility(models.TextChoices):
        PRIVATE = "private", "Only me"
        SHARED = "shared", "Anyone signed in"

    title = models.CharField(max_length=160)
    # The words the person actually used. Kept verbatim: it is the honest
    # record of what was asked for, and what a regeneration should answer.
    prompt = models.TextField()

    # The layout Claude produced, validated against the render_surface tool
    # schema before it is stored. Shape is documented in views.SURFACE_SCHEMA.
    spec = models.JSONField(default=dict)

    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="surfaces")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Set when a generation partly failed — the surface still renders, and the
    # panel that could not be built says why instead of showing nothing.
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "surface"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["visibility", "-updated_at"])]

    def __str__(self):
        return self.title

    def visible_to(self, user):
        if self.visibility == self.Visibility.SHARED:
            return True
        if user is None or not user.is_authenticated:
            return False
        return self.created_by_id == user.id or user.is_superuser
