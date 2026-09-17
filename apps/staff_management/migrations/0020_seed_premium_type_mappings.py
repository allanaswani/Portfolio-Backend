"""The three sample product mappings, for an EMPTY table only.

Production's ``premium_types_mapping`` already exists and this repo has never
seen its rows. Those rows are the real mapping; the three below are the sample
that came with the request. Writing the sample over a populated table would be
this migration inventing data, so it stops the moment it finds anything there.

On a fresh database — a developer's, the test runner's — it gives the screen
something to show and the tests something to assert.
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

    existing = Mapping.objects.count()
    if existing:
        print(f"\n  premium_types_mapping: {existing} row(s) already present — "
              "leaving them alone, not seeding the sample products.")
        return

    for product, vic, life, premium_type, category in ROWS:
        Mapping.objects.create(
            product=product,
            vic_check=vic,
            life_policy_check=life,
            premium_type=premium_type,
            policy_category=category,
        )
    print(f"\n  premium_types_mapping: was empty — seeded {len(ROWS)} sample products.")


def unload(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "PremiumTypeMapping")
    for product, *_ in ROWS:
        Mapping.objects.filter(product__iexact=product).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0019_premiumtypemapping_historicalpremiumtypemapping"),
    ]

    operations = [migrations.RunPython(load, unload)]
