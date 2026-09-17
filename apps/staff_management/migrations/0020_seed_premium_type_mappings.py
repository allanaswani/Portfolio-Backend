"""The three product mappings supplied with the table.

Seeded so the screen has rows on the day it deploys rather than an empty table
with an Add button and no example of the shape. Bancassurance extends the list
from the UI or by CSV; this is a starting point, not a closed vocabulary.

Idempotent and case-insensitive on ``product``, matching the table's own unique
constraint — re-running it corrects a row rather than creating "IPP" beside
"ipp".
"""
from django.db import migrations

ROWS = [
    # product,      vic_check, life_policy_check, premium_type, policy_category
    ("ipp",         "vic", "life", "non-motor", "Life"),
    ("WHOLE LIFE",  "vic", "life", "non-motor", "Life"),
    ("IDD",         "vic", "life", "non-motor", "Life"),
]


def load(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "PremiumTypeMapping")
    for product, vic, life, premium_type, category in ROWS:
        existing = Mapping.objects.filter(product__iexact=product).first()
        values = {
            "product": product,
            "vic_check": vic,
            "life_policy_check": life,
            "premium_type": premium_type,
            "policy_category": category,
            "updated_by": "migration 0020",
        }
        if existing:
            for field, value in values.items():
                setattr(existing, field, value)
            existing.save()
        else:
            Mapping.objects.create(**values)


def unload(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "PremiumTypeMapping")
    for product, *_ in ROWS:
        Mapping.objects.filter(product__iexact=product).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0019_historicalpremiumtypemapping_premiumtypemapping_and_more"),
    ]

    operations = [migrations.RunPython(load, unload)]
