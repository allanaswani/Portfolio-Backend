"""Put the actual desk team on the desk, and add two more query types.

**The team.** The first cut treated every superuser as a member of this desk,
on the reasoning that the Strategy people who run it are platform superusers.
That is true and incomplete: there are superusers who have nothing to do with
Strategy, and they were receiving the queue. Membership is now explicit, and
this seeds the people who are actually on it.

Matched on email, falling back to username, and **skipped silently when the
account does not exist** — this migration must not fail a deploy because
somebody has not been created yet. Anyone missed is added from Administration,
or by re-running this migration after the account exists.

**The categories.** WHIZZ loan limit and Commission are two of the things the
desk is asked about most, and neither was on the list. A query type that does
not exist is a query that gets filed under "Something else", where it cannot be
counted, or sent as an email instead.
"""

from django.db import migrations

MANAGER_GROUP = "service_desk_manager"
AGENT_GROUP = "service_desk_agent"

#: The Strategy & Business Performance service desk.
TEAM = [
    "trevor.william@hfcb.co.ke",
    "arthur.nyota@hfcb.co.ke",
    "jewell.karani@hfcb.co.ke",
]

#: Removed from the desk groups — not on this team. Nothing else about these
#: accounts is touched: no role, no access, no data.
NOT_ON_THE_DESK = ["benson", "clinton", "tony", "antony"]

# (slug, name, description, response hours, resolution hours)
NEW_CATEGORIES = [
    ("whizz-loan-limit", "WHIZZ loan limit",
     "A customer's WHIZZ limit — how it was arrived at, why it changed, or a "
     "request to have it looked at.", 4, 18),
    ("commission", "Commission",
     "Commission figures — how a payment was calculated, what was paid, or an "
     "amount you believe is wrong.", 4, 18),
]


def seed(apps, schema_editor):
    # Live models for BOTH sides of the membership, deliberately.
    #
    # ``user.groups`` is a descriptor on the live User model and it validates
    # what it is given: handing it a historical Group raises
    # "Cannot query Group object: Must be a Group instance". Mixing the two is
    # the whole bug this comment exists to prevent a repeat of. Nothing here
    # touches schema or a field a historical model would protect, so the live
    # pair is both correct and simpler than resolving the swappable User by hand.
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    manager, _ = Group.objects.get_or_create(name=MANAGER_GROUP)
    agent, _ = Group.objects.get_or_create(name=AGENT_GROUP)
    User = get_user_model()

    for address in TEAM:
        person = (User.objects.filter(email__iexact=address).first()
                  or User.objects.filter(username__iexact=address.split("@")[0]).first())
        if person is None:
            # Not created yet. Not a reason to fail a deployment.
            continue
        person.groups.add(manager)

    for name in NOT_ON_THE_DESK:
        for person in User.objects.filter(username__istartswith=name):
            person.groups.remove(manager)
            person.groups.remove(agent)
        for person in User.objects.filter(email__istartswith=f"{name}."):
            person.groups.remove(manager)
            person.groups.remove(agent)

    Category = apps.get_model("service_desk", "TicketCategory")
    for slug, name, description, response_h, resolution_h in NEW_CATEGORIES:
        Category.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "queue": "strategy",
                "response_minutes": response_h * 60,
                "resolution_minutes": resolution_h * 60,
                "is_active": True,
            },
        )


def unseed(apps, schema_editor):
    """Only the two new categories, and only while nothing points at them.

    Group membership is left alone: by the time anyone reverses this, the team
    may have been edited from Administration, and undoing that would be this
    migration overruling a person.
    """
    Category = apps.get_model("service_desk", "TicketCategory")
    Category.objects.filter(
        slug__in=[slug for slug, *_ in NEW_CATEGORIES],
        tickets__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("service_desk", "0003_broaden_categories"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
