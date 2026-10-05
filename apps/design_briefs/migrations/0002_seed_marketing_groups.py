"""Seed the two design-board RBAC groups so their names resolve on a fresh database.

``marketing_admin`` (assigns designers, reopens archived briefs, sees the
reports) and ``marketing_designer`` (works the briefs allocated to them and
sees the whole board). Members are assigned from the existing Users admin
screen; this migration only guarantees the groups exist, exactly as
``apps.referrals.migrations.0002_seed_telesales_groups`` does.

Reversing it removes the groups. It does not remove anybody's other roles.
"""

from django.db import migrations

GROUPS = ["marketing_admin", "marketing_designer"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("design_briefs", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_groups, remove_groups),
    ]
