"""Put the Strategy & Business Performance team on the desk.

From the HR roster for the department, minus Benson Mbugua, who is on the
roster but not on this desk.

Accounts are matched on email, then username, then the local part of the
address — the roster address and the portfolio login are not always the same
string, and several of these differ by domain alone (``@hfgroup.co.ke`` on the
roster, ``@hfcb.co.ke`` since the rebrand).

**Somebody with no account is added as an email recipient instead**, so they
still hear about every query rather than being silently dropped. That is the
fallback the first attempt at this lacked: migration 0004 matched nothing and
left the desk empty, which meant every query was raised into silence while the
requester still got their confirmation.

Nothing here is destructive. It only adds people to two groups and adds
addresses to the notify list; it never removes anybody, because by the time
this runs a manager may already have edited the team from the Team screen, and
a migration overruling a person is worse than one that does too little.
"""

from django.db import migrations

MANAGER_GROUP = "service_desk_manager"
AGENT_GROUP = "service_desk_agent"

# (full name, roster email, role)
#
# Managers are the ones who lead the function — they can edit the team, the
# query types and the targets. Everybody else works the queue.
TEAM = [
    ("Allan Ademba Aswani",     "Allan.Aswani@hfgroup.co.ke",      "manager"),
    ("Eileen Regina Ndegwa",    "Eileen.Ndegwa@hfgroup.co.ke",     "manager"),
    ("Andrew Sero",             "andrew.young@hfcb.co.ke",         "manager"),
    ("Washingtone Amollo",      "Washingtone.Amolo@hfgroup.co.ke", "manager"),
    ("Stacy Kendi Mwenda",      "Stacy.Mwenda@hfgroup.co.ke",      "agent"),
    ("Shekinah Wangui Mwangi",  "Shekinah.Mwangi@hfgroup.co.ke",   "agent"),
    # The roster spells this one "hfgoup.co.ke" — a typo in the source, not
    # here. It is matched on the local part so the account is still found, and
    # the address is NOT used as a fallback recipient, because mail to a
    # misspelt domain bounces silently.
    ("Bryan Mwaura Kanyigi",    "Bryan.Kanyigi@hfgoup.co.ke",      "agent"),
]

#: Roster addresses that are known to be wrong, so never used to send mail.
UNUSABLE = {"bryan.kanyigi@hfgoup.co.ke"}


def find_account(User, email, name):
    """Match a roster row to a portfolio login, or return None.

    Tried in order of confidence: the exact address, the exact username, then
    the local part against either — which is what bridges the rebrand, since
    ``first.last`` survives a domain change.
    """
    local = email.split("@")[0].strip().lower()
    for lookup in (
        {"email__iexact": email},
        {"username__iexact": local},
        {"email__istartswith": f"{local}@"},
    ):
        found = User.objects.filter(is_active=True, **lookup)
        if found.count() == 1:
            return found.first()

    # Last resort: first and last name together, which catches a login built
    # from the name rather than the address.
    parts = [p for p in name.split() if len(p) > 2]
    if len(parts) >= 2:
        found = User.objects.filter(
            is_active=True,
            first_name__iexact=parts[0], last_name__iexact=parts[-1])
        if found.count() == 1:
            return found.first()
    return None


def seed(apps, schema_editor):
    # Live models: this only reads users and edits group membership. Mixing a
    # historical Group with the live User is what broke migration 0004.
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    User = get_user_model()
    manager = Group.objects.get_or_create(name=MANAGER_GROUP)[0]
    agent = Group.objects.get_or_create(name=AGENT_GROUP)[0]
    Recipient = apps.get_model("service_desk", "DeskRecipient")

    for name, email, role in TEAM:
        person = find_account(User, email, name)
        if person is not None:
            person.groups.add(manager if role == "manager" else agent)
            continue
        # No login. Make sure they are at least emailed — being unreachable is
        # the failure mode that makes this desk look like it is ignoring people.
        if email.strip().lower() in UNUSABLE:
            continue
        Recipient.objects.update_or_create(
            email=email,
            defaults={"name": name, "queue": True, "escalations": role == "manager",
                      "is_active": True},
        )


def unseed(apps, schema_editor):
    """Deliberately does nothing.

    The team is edited from the Team screen. Reversing this would undo a
    person's decision with a deployment.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("service_desk", "0007_historicalticket_resolved_by_ticket_resolved_by"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
