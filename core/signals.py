"""Shared signal helpers."""

from contextlib import contextmanager

from django.contrib.auth.models import User
from django.db.models.signals import post_save


@contextmanager
def muted_profile_signals():
    """Temporarily disconnect the apps.portfolio User post_save handlers.

    Those handlers auto-create a Profile and email the new user a HARDCODED
    password. Both are wrong for programmatic user creation (bulk migration or
    admin-created users): callers create the Profile themselves and send (or
    suppress) their own notifications.
    """
    from apps.portfolio import models as pm

    handlers = []
    for fn in ("create_user_profile", "save_user_profile"):
        handler = getattr(pm, fn, None)
        if handler is not None:
            post_save.disconnect(handler, sender=User)
            handlers.append(handler)
    try:
        yield
    finally:
        for handler in handlers:
            post_save.connect(handler, sender=User)
