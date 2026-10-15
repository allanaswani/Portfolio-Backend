"""The Branch Audit line was carrying a target of 1.0 where its own
description says 1.65.

Spotted on a real card. Antony Siajabu's branch operations manager card
printed:

    Branch Audit   8.0%   target 1

against a measure of success that reads "Annual audit score of 1.65". The
seeded figure came from a cell the BO workbook left at 1.0, and the sentence
beside it is the authority.

It matters more than a cosmetic wrong number, because the audit score is
**lower-is-better**: scored against 1.0, a branch achieving the 1.65 the bank
actually asks of it would read as a 65% overshoot and score nought. Against
1.65 it scores full marks. The same cell is on six back-office cards at 8%
each.

The two lines beside it were already right - resolution at 0.85 ("Achieve 85%
audit implementation score") and compliance at 0.9 ("Annual Compliance score of
90% and above") - so only the score line is touched here.
"""

from django.db import migrations

#: kpi_code -> the target its own description states.
CORRECTIONS = {
    "bo_branch_audit_branch_audit": 1.65,
}


def fix(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    changed = []
    for code, target in CORRECTIONS.items():
        for row in Mapping.objects.filter(kpi_code=code):
            if row.kpi_target is not None and abs(
                    float(row.kpi_target) - target) < 0.0001:
                continue
            was = row.kpi_target
            row.kpi_target = target
            row.save(update_fields=["kpi_target"])
            changed.append(f"{row.role_code}/{code} {was} -> {target}")

    if changed:
        print(f"\n  Audit score target: {len(changed)} mapping(s) corrected to "
              f"the figure their own description states - "
              f"{', '.join(changed)}.")
    else:
        print("\n  Audit score target: already correct, nothing changed.")


def unfix(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")
    Mapping.objects.filter(kpi_code__in=CORRECTIONS).update(kpi_target=1.0)


class Migration(migrations.Migration):

    dependencies = [("staff_management", "0039_audit_returns")]

    operations = [migrations.RunPython(fix, unfix)]
