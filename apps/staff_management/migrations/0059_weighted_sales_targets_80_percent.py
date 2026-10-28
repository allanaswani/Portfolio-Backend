"""Weighted Sales is scored against 80%. Three of the four cards had no target.

The workbook's own cards state it. Business_Banking:

    Weighted Sales   As per assigned 80% target   0.05   >80%   0.8
                     ACTUAL 0.2633   % SCORE 0.3291

and Ultimate_RM carries the same 0.8 as "As per Targets". 0027 seeded the
0.8 on ultimate_rm and left sme_rm, sme_arm and sme_bbc at None, so once the
score is readable those three would show a figure and still dash for want of
a target - the KPI's own description is "As per assigned 80% target".

Seed-only-if-unset, like 0027 and 0029: a target the desk has since set by
hand is left alone, and a per-person target loaded under Figures to load
still overrides this one.
"""

from django.db import migrations

CODES = ("weighted_sales", "weighted_sales_dashboard")
TARGET = 0.8


def seed(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")
    unset = Mapping.objects.filter(kpi_code__in=CODES, kpi_target__isnull=True)
    roles = sorted(unset.values_list("role_code", flat=True))
    unset.update(kpi_target=TARGET)
    print(f"  Weighted Sales: 80% target set on {len(roles)} card(s)"
          + (f" - {', '.join(roles)}" if roles else ""))


def unseed(apps, schema_editor):
    # Only the three this put it on. Ultimate RM had 0.8 from 0027.
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")
    Mapping.objects.filter(
        kpi_code="weighted_sales", kpi_target=TARGET,
        role_code__in=("sme_rm", "sme_arm", "sme_bbc")).update(kpi_target=None)


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0058_customer_last_transaction"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
