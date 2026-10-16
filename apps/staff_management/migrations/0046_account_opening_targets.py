"""The two account-opening targets the seed left empty.

Every role that carries an account-opening line has a target of 1 day on it,
except ``bo_cash_centre_teller``, whose two lines came through with none:

    bo_cash_centre_teller / bo_account_opening_pb    "PB AO TAT OF 1 Day"
    bo_cash_centre_teller / bo_account_opening_sme   "SME AO TAT of 5days"

Both state their target in their own description, and both are now scored
against a real figure - ``account_opening`` reads iApply's accounts trail -
so a line with no target is a line that cannot be scored at all.

Taken from the DESCRIPTION rather than invented, which is what migration
0040 did for the audit score when it found the same shape: the card says
what the number is, and the seed simply did not carry it across.

Five days, not one, for the SME line. That is not a typo in the card: a
cash-centre teller is not the person opening an SME account, so the standard
they are held to is the branch's, and it is laxer.
"""

from django.db import migrations

#: (role, kpi) → the target its own description states.
TARGETS = {
    ("bo_cash_centre_teller", "bo_account_opening_pb"): 1.0,
    ("bo_cash_centre_teller", "bo_account_opening_sme"): 5.0,
}


def set_targets(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    done = []
    for (role, kpi), target in TARGETS.items():
        for row in Mapping.objects.filter(role_code=role, kpi_code=kpi):
            if row.kpi_target is not None:
                continue
            row.kpi_target = target
            row.save(update_fields=["kpi_target"])
            done.append(f"{role}/{kpi} -> {target:g}")

    print(f"  Account-opening targets: {len(done)} set from the line's own "
          f"description" + (f" - {'; '.join(done)}" if done else
                            " (none were missing)"))


def leave_them(apps, schema_editor):
    """Not cleared on the way back.

    Removing a target would leave the line unscorable again, and the figure
    it was taken from is still written on the card.
    """
    print("  Account-opening targets: kept - the card still states them.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0045_customermonthlyactivity_and_more"),
    ]

    operations = [
        migrations.RunPython(set_targets, leave_them),
    ]
