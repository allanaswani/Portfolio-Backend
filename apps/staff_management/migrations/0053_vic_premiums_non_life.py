"""Four KPIs are named after a group header. They are VIC Premiums (non-life).

A scorecard row carries its GROUP only on the first line of that group, and
its KPI name only on the first line of that KPI. A row stating a SECOND
MEASURE of the same KPI leaves the KPI column blank. VIC Premiums is always
two such rows:

    Ultimate_RM
      ... | VIC Premiums | life policies as per assigned Target | 0.05
      ... |              | non-life as per assigned Target      | 0.05

Whatever seeded these read the second row on its own, found the KPI column
empty, and fell back to the column beside it - which holds the group. So the
non-life half of VIC Premiums was named "Group Synergies (23.0%)" and has
been printing on cards, under its own weight, as though the perspective
heading were a measure.

Only the NAME was ever wrong. Every one of these codes is registered against
``target_banca_non_life`` and ``banca_non_life``, so the target and the
figure have always been the non-life premiums - which is why this never
showed up as a scoring error, only as a line nobody could account for.

Four codes, eleven roles:

    commercial_trade_group_synergies_23_0   commercial_rm_trade
    group_synergies_20_0                    sme_arm, sme_bbc, sme_rm
    group_synergies_25_0                    mortgage_business_arm
    personal_banking_group_synergies_23_0   diaspora_arm, diaspora_rm,
                                            pb_arm, pb_bbc, pb_rm,
                                            ultimate_rm

The codes are left alone. They are referenced by the source registry and by
seeded mappings, and renaming a key to fix a label would be a much larger
change for no gain.
"""

from django.db import migrations

NAME = "VIC Premiums (non-life)"

#: Every code whose name was taken from the group header above it.
CODES = (
    "commercial_trade_group_synergies_23_0",
    "group_synergies_20_0",
    "group_synergies_25_0",
    "personal_banking_group_synergies_23_0",
)


def name_them_for_what_they_measure(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")

    renamed = []
    for row in Kpi.objects.filter(kpi_code__in=CODES):
        was = row.kpi_name or ""
        if was == NAME:
            continue
        row.kpi_name = NAME
        row.save(update_fields=["kpi_name"])
        renamed.append(f"{row.kpi_code} ({was})")

    if renamed:
        print(f"  VIC Premiums: {len(renamed)} line(s) were named after the "
              f"group above them and now say what they measure - "
              f"{', '.join(renamed)}")
    else:
        print("  VIC Premiums: nothing to rename; already correct.")


def put_the_group_names_back(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")

    # The group each one was wrongly named after, so the reverse is exact.
    was = {
        "commercial_trade_group_synergies_23_0": "Group Synergies (23.0%)",
        "group_synergies_20_0": "Group Synergies (20.0%)",
        "group_synergies_25_0": "Group Synergies (25.0%)",
        "personal_banking_group_synergies_23_0": "Group Synergies (23.0%)",
    }
    for code, name in was.items():
        Kpi.objects.filter(kpi_code=code).update(kpi_name=name)
    print("  VIC Premiums: group headings put back.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0052_actual_source"),
    ]

    operations = [
        migrations.RunPython(name_them_for_what_they_measure,
                             put_the_group_names_back),
    ]
