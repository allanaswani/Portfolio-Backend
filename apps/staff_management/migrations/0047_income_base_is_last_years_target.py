"""The income lines grow last year's TARGET, not last year's actual.

"Operating Profit ... Growth on Growth" and the three income-contribution
lines beside it were pointed at ``TOTAL INCOME CONTRIBUTION/2024
(Income+(FTP-LoanLoss))`` - what the person actually earned last year. The
card grows last year's TARGET, which is the column beside it, plainly
labelled ``2024.0``.

Juspher Muriithi settles it. His printed card reads:

    2025 FY  231,547,094.69
    GROWTH    46,309,418.94      (20% of 231,547,094.69)
    2026 FY  277,856,513.63

The allocation sheet holds 231,547,094.69 in ``2024.0`` and 88,324,015.96 in
the actual column, with 17,664,803.19 of growth - a flat 20%, of the ACTUAL.
Pointed at the actual, his target came out at 105,988,819; pointed at the
target with the same rate, it comes out at 277,856,513.63, which is the
figure on his card.

The rate itself is not written down here. ``scorecard_ingest`` reads it off
the sheet - uniform at 20% across all 88 rows today - so a year when it
changes follows by itself.
"""

from django.db import migrations

GROUP = "TOTAL INCOME CONTRIBUTION"
WAS = f"{GROUP}/2024 (Income+(FTP-LoanLoss))"
NOW = f"{GROUP}/2024.0"

#: Every line that grows the income contribution.
CODES = (
    "direct_portfolio_contribution",
    "income_contribution",
    "income_contribution_portfolio_ntb",
    "operating_profit",
)


def point_at_the_target(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")

    moved = []
    for row in Kpi.objects.filter(kpi_code__in=CODES):
        if (row.allocation_base_column or "").strip() != WAS:
            continue
        row.allocation_base_column = NOW
        row.save(update_fields=["allocation_base_column"])
        moved.append(row.kpi_code)

    if moved:
        print(f"  Income base: {len(moved)} line(s) now grow last year's "
              f"TARGET rather than last year's actual - {', '.join(moved)}")
    else:
        print("  Income base: nothing to move; they already point at the "
              "target, or the seed has changed.")


def point_back(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")

    for row in Kpi.objects.filter(kpi_code__in=CODES):
        if (row.allocation_base_column or "").strip() == NOW:
            row.allocation_base_column = WAS
            row.save(update_fields=["allocation_base_column"])
    print("  Income base: pointed back at last year's actual.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0046_account_opening_targets"),
    ]

    operations = [
        migrations.RunPython(point_at_the_target, point_back),
    ]
