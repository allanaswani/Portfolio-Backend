"""Put the Strategy team in the group the usage reports leave out.

The people are those HR's Employee Listing (20 Aug 2026) places in the Strategy,
Business Performance & Change division. They are matched on the exact name
before the @ in their address, as a username or an e-mail, because the bank's
addresses have moved between hfgroup.co.ke and hfcb.co.ke. An account that does
not match stays in the report; Administration -> Users can add it.

"Strategy & Business Performance" staff whose division is HFDI are not included:
they are HFDI's project team, not this department.
"""

from django.db import migrations

GROUP = "usage_report_excluded"
STRATEGY = {
    "eileen.ndegwa", "allan.aswani", "bryan.kanyingi", "shekinah.mwangi",
    "stacy.kendi", "andrew.young", "washingtone.amolo",
}


def seed(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Group = apps.get_model("auth", "Group")
    group, _ = Group.objects.get_or_create(name=GROUP)
    for user in User.objects.all().only("id", "username", "email"):
        names = {(user.username or "").strip().lower(),
                 (user.email or "").strip().lower().split("@")[0]}
        if names & STRATEGY:
            user.groups.add(group)


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("observability", "0005_alert_recipient_usage_report"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
