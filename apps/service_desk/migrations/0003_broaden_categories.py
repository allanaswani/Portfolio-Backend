"""Widen the desk beyond the tool.

The first set of categories was written as if every query were about this
application — a broken page, a table that stopped loading. That is a fraction of
what Strategy & Business Performance are actually asked. Most of it is about the
reports and scorecards they publish, and a great deal of it is somebody wanting
a number explained rather than fixed.

A category list that does not describe the query somebody has means they pick
"Something else" or, worse, go back to sending an email — which is the behaviour
this desk exists to replace. So the list now covers the work, not the software.

Existing categories keep their slugs, so tickets already raised keep their
category, their promise and their reporting line. Two are added and several are
renamed to say what they actually mean.
"""

from django.db import migrations

# (slug, name, description, response hours, resolution hours)
CATEGORIES = [
    ("report-request", "Report or data request",
     "A report, extract or figure you need that you do not already have.", 4, 18),
    ("clarification", "Clarification or explanation",
     "A number, definition or methodology you want explained — what it means, "
     "where it comes from, why it moved.", 4, 18),
    ("scorecard", "Scorecard query",
     "Your scorecard score, how a measure was weighted or calculated, or "
     "something on it you believe is wrong.", 4, 27),
    ("targets", "Targets and performance",
     "Allocated targets, performance figures, or how an achievement was "
     "arrived at.", 4, 27),
    ("data-quality", "A figure looks wrong",
     "A number on a report or dashboard that does not match the source, or a "
     "table that has stopped updating.", 2, 9),
    ("system-issue", "System or dashboard problem",
     "A page that errors, will not load, or shows nothing where it used to "
     "show something.", 1, 9),
    ("access", "Access or permissions",
     "You cannot reach a page, report or module that your job requires.", 2, 9),
    ("other", "Something else",
     "Anything else you need from Strategy & Business Performance. Use this "
     "rather than not raising it at all.", 4, 27),
]

#: Renamed, not replaced. The old slug keeps every ticket raised under it.
RENAMED = {"data-request": "report-request"}


def widen(apps, schema_editor):
    Category = apps.get_model("service_desk", "TicketCategory")

    # Carry the old slug over first, so its tickets follow the rename rather
    # than being orphaned next to a new, empty category that means the same.
    for old, new in RENAMED.items():
        row = Category.objects.filter(slug=old).first()
        if row and not Category.objects.filter(slug=new).exists():
            row.slug = new
            row.save(update_fields=["slug"])

    for order, (slug, name, description, response_h, resolution_h) in enumerate(CATEGORIES):
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


def narrow(apps, schema_editor):
    """Only the two genuinely new ones go.

    The rest are left as they are: by the time anyone reverses this, tickets
    point at them, and reversing would take their promise and their reporting
    line with it.
    """
    Category = apps.get_model("service_desk", "TicketCategory")
    Category.objects.filter(
        slug__in=["clarification", "scorecard"], tickets__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("service_desk", "0002_seed_desk")]
    operations = [migrations.RunPython(widen, narrow)]
