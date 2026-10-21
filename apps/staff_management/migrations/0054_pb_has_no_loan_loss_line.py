"""Personal Banking carries no Loan Loss line. Three seeded ones say it does.

Every sales role sheet was read back and diffed against what is seeded for
it - line count, order, weight and wording. Eleven of the twelve agree
exactly. Personal Banking does not: the sheet has 18 lines, the seed has 19.

The extra one is ``reduce_p_l_provisions_nill_provisions_loan_loss`` at
order 16 with a weight of ZERO, on pb_rm, pb_arm and pb_bbc. The sheet's
eighteen lines are

    Active Customers, Digital Adoption, New Customers, Portfolio Coverage,
    Income Contribution, Number of Property, Value of Property Sales,
    VIC Premiums (life), VIC Premiums (non-life), Bancassurance Premiums,
    Drawdowns, Asset Growth, Deposit Growth, NPS, Weigted TAT, Training,
    Leave management, PAR

and none of them is a provisions line. The weights already total 1.025
without it, which is the other half of the proof: if the line belonged
there, the sheet would be short by its weight, and it is not.

A zero weight is not harmless. The line prints on the card as a row, under
its own heading, and is counted among the lines a person is measured on -
so a Personal Banking card has been showing a measure the bank's own card
does not have, on a document people sign. Scoring is unaffected, because
nought times anything is nought; what is affected is what the card says a
person is accountable for.

Only these three. The same KPI is legitimately seeded with a real weight on
the roles whose sheets do carry it, and those are left exactly as they are.
"""

from django.db import migrations

CODE = "reduce_p_l_provisions_nill_provisions_loan_loss"
ROLES = ("pb_rm", "pb_arm", "pb_bbc")


def drop_the_phantom_line(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    # Weight nought AND these roles AND this code - all three, so a mapping
    # that has since been given a real weight is never silently deleted.
    doomed = Mapping.objects.filter(
        kpi_code=CODE, role_code__in=ROLES, kpi_weight=0)
    found = sorted(doomed.values_list("role_code", flat=True))
    removed, _ = doomed.delete()

    if removed:
        print(f"  Personal Banking: removed {len(found)} zero-weight Loan "
              f"Loss line(s) the sheet does not carry - {', '.join(found)}")
    else:
        print("  Personal Banking: no zero-weight Loan Loss line to remove.")


def put_it_back(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    for role in ROLES:
        if Mapping.objects.filter(kpi_code=CODE, role_code=role).exists():
            continue
        Mapping.objects.create(
            role_code=role, kpi_order=16, kpi_code=CODE,
            mapping_category="Portfolio Management", kpi_weight=0)
    print("  Personal Banking: zero-weight Loan Loss line restored.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0053_vic_premiums_non_life"),
    ]

    operations = [
        migrations.RunPython(drop_the_phantom_line, put_it_back),
    ]
