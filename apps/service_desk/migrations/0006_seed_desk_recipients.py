"""Put the desk's actual addresses on the notify list.

Migration 0004 tried to add these three people by finding their accounts, and
found none — they do not have logins on this tool, and do not need them. They
need the mail.

An address needs no account, so this one cannot silently match nothing the way
0004 did. If somebody has a login later, adding them to the
``service_desk_manager`` group makes them a handler as well; the two lists are
added together, never one instead of the other, so nothing has to be undone here
when that happens.
"""

from django.db import migrations

RECIPIENTS = [
    ("trevor.william@hfcb.co.ke", "Trevor William"),
    ("arthur.nyota@hfcb.co.ke", "Arthur Nyota"),
    ("jewell.karani@hfcb.co.ke", "Jewell Karani"),
]


def seed(apps, schema_editor):
    Recipient = apps.get_model("service_desk", "DeskRecipient")
    for email, name in RECIPIENTS:
        Recipient.objects.update_or_create(
            email=email,
            defaults={"name": name, "queue": True, "escalations": True,
                      "is_active": True},
        )


def unseed(apps, schema_editor):
    Recipient = apps.get_model("service_desk", "DeskRecipient")
    Recipient.objects.filter(email__in=[email for email, _ in RECIPIENTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("service_desk", "0005_deskrecipient_historicaldeskrecipient")]
    operations = [migrations.RunPython(seed, unseed)]
