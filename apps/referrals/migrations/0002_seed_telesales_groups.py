"""Seed the two telesales RBAC groups so their names resolve on a fresh database.

``telesales_supervisor`` (allocates + sees all) and ``telesales_agent`` (works an
allocated queue). Members are assigned via the existing Users admin screen; this
migration only guarantees the groups exist. Reversing it removes them.
"""

from django.db import migrations

GROUPS = ["telesales_supervisor", "telesales_agent"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("referrals", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_groups, remove_groups),
    ]
