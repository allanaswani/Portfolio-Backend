"""Income Contribution (Portfolio + NTB) grows last year's ACTUAL.

Migration 0047 pointed four income codes at the allocation sheet's ``2024.0``
column, on evidence from ONE of them: Juspher Muriithi's *Direct Portfolio
Contribution*, whose card base of 231,547,094.69 is that column exactly. The
other three were moved with it and never checked.

Faith Muthinja shows that was too broad. Her row on "Summary Allocation" is

    col 17  2024.0                          -44,474,105.67
    col 18  2024 (Income+(FTP-LoanLoss))      9,618,462.69

and her signed Ultimate RM card prints "2025 FY  9,618,462.69" against
*Income Contribution (Portfolio + NTB)*. So that line grows column 18, last
year's ACTUAL - not column 17.

It is not a cosmetic difference. Column 17 is NEGATIVE for her, and a growth
added to it produced a target of -39,917,032.92 on her live card: a target to
earn less than nothing, which cannot be met or missed. The guard added
alongside now refuses it, which is why the line reads "no target set" instead
of scoring against a negative. This gives it a real one.

Only ``income_contribution_portfolio_ntb`` is moved back. The other three stay
on ``2024.0`` because Juspher's card is direct evidence for
``direct_portfolio_contribution``, and nothing has been seen either way for
``income_contribution`` or ``operating_profit`` - guessing would swap one
unverified column for another.

Still not reconciled, and recorded here so nobody thinks it is: her card grows
that base by 8.33% to reach 10,420,001.24, while the sheet's own Growth column
holds 1,923,692.54, a flat 20%, which would give 11,542,155.22. The growth
RATE is per person - 8.33%, 18.33% and 20% across the three signed cards seen
so far - and the allocation sheet does not carry the one her card used. Fixing
the column makes the base right; the rate still has to come from the card
itself.
"""

from django.db import migrations

GROUP = "TOTAL INCOME CONTRIBUTION"
WAS = f"{GROUP}/2024.0"
NOW = f"{GROUP}/2024 (Income+(FTP-LoanLoss))"

#: Only this one. See the module docstring.
CODE = "income_contribution_portfolio_ntb"


def point_at_the_actual(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")

    moved = 0
    for row in Kpi.objects.filter(kpi_code=CODE):
        if (row.allocation_base_column or "").strip() != WAS:
            continue
        row.allocation_base_column = NOW
        row.save(update_fields=["allocation_base_column"])
        moved += 1

    if moved:
        print(f"  Income (NTB) base: {moved} line(s) now grow last year's "
              f"ACTUAL - Faith Muthinja's 2024.0 is -44,474,105.67, and her "
              f"card's base is the 9,618,462.69 beside it.")
    else:
        print("  Income (NTB) base: nothing to move; it already points at "
              "the actual, or the seed has changed.")


def point_back(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")
    Kpi.objects.filter(kpi_code=CODE,
                       allocation_base_column=NOW).update(
        allocation_base_column=WAS)
    print("  Income (NTB) base: pointed back at 2024.0.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0050_role_score_cap"),
    ]

    operations = [
        migrations.RunPython(point_at_the_actual, point_back),
    ]
