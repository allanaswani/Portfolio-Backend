"""The dormancy target was one named person's own figure, read as a role's.

``bo_re_activation`` carried these as ROLE targets:

    bo_bom                  0.3840654055787111
    bo_cso                  0.22342137845645896
    bo_cso_ub               0.13776237623762377
    bo_bom_cso              1.0
    bo_cash_centre_teller   1.0

Sixteen significant figures is not a target anybody set. The two at 1.0 are
the other half of the same problem - a placeholder where the workbook had no
figure, which scores a rate measure against 100%. Each of those is the
figure off the one card the role was seeded from — Joseph Kinuthia's at
Naivasha for the BOM, Janet Nabwire's at Buruburu for the CSO, Anne Muthama's
at Rehani for Ultimate — and read as a role target it scores **every** branch
operations manager in the bank against Naivasha's dormancy.

This is exactly what migration 0029 cleared for the sales roles, where the same
seeding had left every SME RM measured against one named RM's closing balance.
The reasoning is unchanged: a target nobody set, applied to people it was never
about, is worse than no target. The line now says what it needs, and
Administration can allocate a real one per person on the Figures to load
screen.

The figure is not lost — it is in ``docs/bo-scorecard-kpi-map.csv`` against the
card and the person it came from.

Deliberately narrow: only ``bo_re_activation`` is touched. The other BO role
targets were checked against their own descriptions when they were seeded —
PAR 2.5%, the audit score 1.65, 85% implementation, 90% compliance — and those
are genuinely role-wide statements of what the bank asks.
"""

from django.db import migrations

KPI_CODE = "bo_re_activation"


def clear(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    cleared = []
    for row in Mapping.objects.filter(kpi_code=KPI_CODE):
        if row.kpi_target is None:
            continue
        cleared.append(f"{row.role_code} was {float(row.kpi_target):.4f}")
        row.kpi_target = None
        row.save(update_fields=["kpi_target"])

    if cleared:
        print(f"\n  Dormancy target: cleared on {len(cleared)} role(s) - it "
              f"was one named person's own figure, not a role target "
              f"({'; '.join(cleared)}).")
    else:
        print("\n  Dormancy target: nothing to clear.")


def unclear(apps, schema_editor):
    # Deliberately not restored. Putting one branch's figure back as every
    # branch's target is the fault this migration exists to remove, and a
    # reverse that recreates it would be a trap for whoever ran it.
    pass


class Migration(migrations.Migration):

    dependencies = [("staff_management", "0040_audit_score_target")]

    operations = [migrations.RunPython(clear, unclear)]
