"""Seed the desk so it is usable the moment it is deployed.

Three things, none of which anyone should have to key in by hand before the
first ticket can be raised:

* the two groups the RBAC checks by name, so the gates resolve on a fresh
  database rather than silently refusing everybody;
* a starting set of categories, each with an SLA, because a ticket with no
  category has no promise attached and is exactly the ticket that goes unhandled;
* the settings row and the public-holiday calendar the SLA clock runs on.

**The holiday list is fixed-date only.** Eid al-Fitr and Eid al-Adha follow the
lunar calendar and any day may be gazetted at short notice, so those are added
from the Administration screen. Guessing them here would put a wrong date in
version control and quietly shift every SLA that crosses it.
"""

from datetime import date

from django.db import migrations

CATEGORIES = [
    # (slug, name, description, response hrs, resolution hrs)
    ("data-request", "Data or report request",
     "A figure, extract or report that does not exist on a page yet.", 4, 18),
    ("data-quality", "Data looks wrong",
     "A number on a dashboard that does not match the source, or a table that "
     "has stopped loading.", 2, 9),
    ("system-issue", "System or dashboard not working",
     "A page that errors, will not load, or shows nothing where it used to "
     "show something.", 1, 9),
    ("targets", "Targets and scorecards",
     "Queries about allocated targets, scorecard weighting or performance "
     "figures.", 4, 27),
    ("access", "Access or permissions",
     "Cannot reach a page or a module that the job requires.", 2, 9),
    ("other", "Something else",
     "Anything that does not fit the categories above.", 4, 27),
]

# Fixed-date Kenyan public holidays, plus Easter, which is computable and which
# I have stated explicitly rather than derived, so a wrong year is visible.
FIXED = [
    ((1, 1), "New Year's Day"),
    ((5, 1), "Labour Day"),
    ((6, 1), "Madaraka Day"),
    ((10, 10), "Huduma Day"),
    ((10, 20), "Mashujaa Day"),
    ((12, 12), "Jamhuri Day"),
    ((12, 25), "Christmas Day"),
    ((12, 26), "Boxing Day"),
]
EASTER = {
    2026: (date(2026, 4, 3), date(2026, 4, 6)),
    2027: (date(2027, 3, 26), date(2027, 3, 29)),
}


def seed(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ("service_desk_manager", "service_desk_agent"):
        Group.objects.get_or_create(name=name)

    Settings = apps.get_model("service_desk", "DeskSettings")
    Settings.objects.get_or_create(singleton=1)

    Category = apps.get_model("service_desk", "TicketCategory")
    for slug, name, description, response_h, resolution_h in CATEGORIES:
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

    Holiday = apps.get_model("service_desk", "Holiday")
    for year in (2026, 2027):
        for (month, day), name in FIXED:
            Holiday.objects.get_or_create(day=date(year, month, day),
                                          defaults={"name": name})
        good_friday, easter_monday = EASTER[year]
        Holiday.objects.get_or_create(day=good_friday, defaults={"name": "Good Friday"})
        Holiday.objects.get_or_create(day=easter_monday, defaults={"name": "Easter Monday"})


def unseed(apps, schema_editor):
    # Categories and holidays are left alone: by the time anyone reverses this,
    # tickets point at those categories and reversing would take their promise
    # with them. The groups go, since nothing references them by id.
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(
        name__in=["service_desk_manager", "service_desk_agent"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("service_desk", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
