"""Put back the Loan Loss line 0054 deleted. It is on the sheet and the card.

Migration 0054 removed ``reduce_p_l_provisions_nill_provisions_loan_loss``
from pb_rm, pb_arm and pb_bbc, on the claim that

    the sheet has 18 lines, the seed has 19 ... The sheet's eighteen lines
    are [...] and none of them is a provisions line.

That is false, and the error was in how the sheet was counted, not in the
seed. The counting rule dropped any row whose WEIGHT was falsy - and the
provisions row's weight is exactly 0.0, which is the one row the check was
being written to find. It counted 18 rows, concluded the nineteenth did not
exist, and deleted it.

Read again, counting every row that carries a feed key whatever its weight,
``Personal_Banking`` has NINETEEN lines totalling 1.0250:

    16  r20  w=0.0  Reduce  P&L provisions / Nill provisions   PL_Charge

and the second piece of evidence is a signed card. Lydia Apanja's
``Q3_Sep_26`` Personal Banking ARM scorecard prints the line in full:

    NPL ( 5% ) | Reduce  P&L provisions / Nill provisions (Loan Loss)
               | By Assigned Amount | 0.0% | .11m | .00m | .00m | .00m
               | -.03m | 3.4% | 0.0% | PL_Charge

Weight 0.0%, a real actual of -.03m against it, and a score of 3.4% that
carries no weight into the total. Her weights sum to 100.0% without it and
102.5% with PAR, exactly as the sheet does.

So a weight of nought is NOT the proof of a phantom line that 0054 took it
for. The bank prints this line at nought deliberately: the person is shown
their provisions position and is not scored on it. Removing it took that off
a document people sign.

0054's own reasoning is worth keeping, inverted: "the line prints on the card
as a row, under its own heading, and is counted among the lines a person is
measured on". It does print as a row, under ``NPL ( 5% )`` - which is also
the heading 0054's reverse got wrong, restoring it under "Portfolio
Management". This restores it where the sheet puts it.

Only the three roles 0054 touched, and only where the line is now absent, so
a role that has since been given a real weight is not overwritten.
"""

from django.db import migrations

CODE = "reduce_p_l_provisions_nill_provisions_loan_loss"
ROLES = ("pb_rm", "pb_arm", "pb_bbc")

#: Where the sheet puts it: row 20 of 24, the sixteenth line that carries a
#: feed key, under its own perspective heading.
ORDER = 16
CATEGORY = "NPL (5%)"
DESCRIPTION = "By Assigned Amount"


def put_the_line_back(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    restored = []
    for role in ROLES:
        if Mapping.objects.filter(kpi_code=CODE, role_code=role).exists():
            continue
        Mapping.objects.create(
            role_code=role, kpi_order=ORDER, kpi_code=CODE,
            mapping_category=CATEGORY, kpi_description=DESCRIPTION,
            kpi_weight=0)
        restored.append(role)

    if restored:
        print(f"  Personal Banking: restored the Loan Loss line on "
              f"{', '.join(restored)} - 0054 deleted it after a count that "
              f"skipped zero-weight rows. The sheet has 19 lines and Lydia "
              f"Apanja's signed Q3_Sep_26 card prints it at 0.0%.")
    else:
        print("  Personal Banking: the Loan Loss line is already there.")


def take_it_away_again(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")
    removed, _ = Mapping.objects.filter(
        kpi_code=CODE, role_code__in=ROLES, kpi_weight=0).delete()
    print(f"  Personal Banking: Loan Loss line removed again ({removed}).")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0055_income_and_operating_profit_grow_the_actual"),
    ]

    operations = [
        migrations.RunPython(put_the_line_back, take_it_away_again),
    ]
