"""Find the two people the first match missed.

Migration 0008 matched a roster row to a login on first-name-plus-LAST-name.
Kenyan names carry three parts, and the surname on the roster is often not the
one the account uses: *Stacy Kendi Mwenda* signs in as **Stacy Kendi**, *Bryan
Mwaura Kanyigi* as **Bryan Mwaura**. Both were quietly left off the desk and
out of the "who should handle this" list.

``roster.apply()`` now tries every name part as a candidate surname, and falls
back to "the login mentions their first name and one other part of it" — always
requiring a unique match, because adding the wrong colleague to a desk is worse
than leaving somebody off it.

The matching lives in ``apps/service_desk/roster.py`` rather than in here, so
that correcting it again is re-running a command rather than writing a third
migration. Adds only; never removes.
"""

from django.db import migrations


def rematch(apps, schema_editor):
    from apps.service_desk import roster

    # The live DeskRecipient: apply() only reads and upserts ordinary fields,
    # and the historical model cannot be handed to the live User's group m2m
    # anyway — the mistake that broke migration 0004.
    roster.apply()


def noop(apps, schema_editor):
    """The team is edited from the Team screen. A migration must not undo that."""


class Migration(migrations.Migration):
    dependencies = [
        ("service_desk", "0008_seed_strategy_team"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(rematch, noop)]
