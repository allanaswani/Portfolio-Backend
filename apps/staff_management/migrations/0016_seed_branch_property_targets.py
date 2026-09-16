"""The 2026 branch property plan, loaded from branch_properties_targets.xlsx.

22 branches. The targets sum to exactly 340.00000000, which is the check to run
if anyone edits this list: a plan that no longer adds up to the bank number is
the first thing a reviewer will spot.

Shipped as a migration rather than left to a manual upload so the Property
Holdings page has something to measure against the moment it deploys. The
loader command (`manage.py load_branch_property_targets`) exists for the NEXT
plan year; it is not needed for this one.
"""
from decimal import Decimal

from django.db import migrations

YEAR = 2026

# (brn_code, staff_branch, staff_zone, target_properties) — verbatim from the
# workbook, at the 8dp scale the column stores.
ROWS = [
    (16,  "KITENGELA BRANCH",            "Zone A", "14.26573427"),
    (17,  "NAIVASHA BRANCH",             "Zone A", "14.26573427"),
    (19,  "HURLINGHAM BRANCH",           "Zone B", "16.64335664"),
    (20,  "RIVERROAD BRANCH",            "Zone A", "19.02097902"),
    (22,  "NANYUKI BRANCH",              "Zone A", "11.88811189"),
    (23,  "KOMAROCK BRANCH",             "Zone A", "9.51048951"),
    (24,  "MACHAKOS BRANCH",             "Zone A", "14.26573427"),
    (25,  "EMBU BRANCH",                 "Zone A", "7.13286713"),
    (200, "REHANI BRANCH",               "Zone C", "35.66433566"),
    (220, "HARAMBEE AVE BRANCH",         "Zone B", "21.39860140"),
    (230, "BURUBURU BRANCH",             "Zone A", "14.26573427"),
    (250, "RONGAI BRANCH",               "Zone A", "14.26573427"),
    (260, "THIKA ROAD MALL-TRM BRANCH",  "Zone A", "7.13286713"),
    (270, "SAMEER BUSINESS PARK BRANCH", "Zone B", "16.64335664"),
    (280, "WESTLANDS BRANCH",            "Zone B", "16.64335664"),
    (300, "MOMBASA BRANCH",              "Zone B", "16.64335664"),
    (400, "NAKURU BRANCH",               "Zone B", "14.26573427"),
    (410, "ELDORET BRANCH",              "Zone A", "19.02097902"),
    (500, "THIKA BRANCH",                "Zone A", "16.64335664"),
    (510, "NYERI BRANCH",                "Zone A", "11.88811189"),
    (520, "MERU BRANCH",                 "Zone A", "9.51048951"),
    (600, "KISUMU BRANCH",               "Zone A", "19.02097902"),
]

EXPECTED_TOTAL = Decimal("340.00000000")


def load(apps, schema_editor):
    Target = apps.get_model("staff_management", "BranchPropertyTarget")

    total = sum(Decimal(t) for _, _, _, t in ROWS)
    if total != EXPECTED_TOTAL:
        raise ValueError(
            f"Branch property targets sum to {total}, expected {EXPECTED_TOTAL}. "
            "The plan must add up to the bank figure."
        )

    for brn, branch, zone, target in ROWS:
        Target.objects.update_or_create(
            brn_code=brn, year=YEAR,
            defaults={
                "staff_branch": branch,
                "staff_zone": zone,
                "target_properties": Decimal(target),
                "updated_by": "migration 0016",
            },
        )


def unload(apps, schema_editor):
    Target = apps.get_model("staff_management", "BranchPropertyTarget")
    Target.objects.filter(
        year=YEAR, brn_code__in=[r[0] for r in ROWS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0015_branchpropertytarget_historicalbranchpropertytarget_and_more"),
    ]

    operations = [migrations.RunPython(load, unload)]
