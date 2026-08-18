"""Seed the initial DSR role → team-leader mappings.

- BANCA DSR → David Wambugu
- SME DSR (referred to by the business as DPA) → Eva Kabiwa, Luke Njagi

Idempotent (update_or_create), so re-running is safe. Add more via the same
table (``dsr_role_team_leaders``) as roles/leaders change.
"""

from django.db import migrations

# (role, team_leader, sort_order)
MAPPINGS = [
    ("BANCA DSR", "David Wambugu", 10),
    ("SME DSR", "Eva Kabiwa", 10),
    ("SME DSR", "Luke Njagi", 20),
]


def seed(apps, schema_editor):
    Model = apps.get_model("staff_management", "DSRRoleTeamLeader")
    for role, tl, order in MAPPINGS:
        Model.objects.update_or_create(
            role=role, team_leader=tl,
            defaults={"sort_order": order, "active": True},
        )


def unseed(apps, schema_editor):
    Model = apps.get_model("staff_management", "DSRRoleTeamLeader")
    for role, tl, _ in MAPPINGS:
        Model.objects.filter(role=role, team_leader=tl).delete()


class Migration(migrations.Migration):
    dependencies = [("staff_management", "0010_dsrroleteamleader_and_more")]
    operations = [migrations.RunPython(seed, unseed)]
