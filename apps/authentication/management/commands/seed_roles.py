"""
Ensure every legacy HF Group role (auth.Group) exists in the new default DB.

Idempotent — safe to run repeatedly. Run this BEFORE migrate_legacy_auth so
group rows are present, though migrate_legacy_auth also self-heals missing groups.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from core.roles import ALL_ROLE_DESCRIPTIONS, ALL_ROLES


class Command(BaseCommand):
    help = "Create the canonical HF roles (Django Groups) in the default database."

    def handle(self, *args, **options):
        created, existing = 0, 0
        for name in ALL_ROLES:
            _, was_created = Group.objects.get_or_create(name=name)
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + created group '{name}'"))
            else:
                existing += 1
                self.stdout.write(f"  = group '{name}' already present")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {created} created, {existing} already existed, "
                f"{len(ALL_ROLES)} total roles."
            )
        )
        # Surface descriptions for operator clarity.
        for name in ALL_ROLES:
            self.stdout.write(f"    {name}: {ALL_ROLE_DESCRIPTIONS.get(name, '')}")
