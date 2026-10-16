"""Active Customers and Digital Adoption: a rate on the person's own base.

The signed Q3 cards state both targets as a growth rate, not an absolute:

    Alice Kamau  (SME ARM)  Active Customers (2 months active)
                            "Increase by active customers 20%"
                            2025 FY 42  ->  2026 FY 50.4
    Lydia Apanja (PB ARM)   Active Customers
                            "2 month active(increase by 20%)"
                            2025 FY 102 ->  2026 FY 120.7
    Lydia Apanja (PB ARM)   Digital Adoption
                            "Increase portfolio by 50%"
                            2025 FY 197 ->  2026 FY 287.29

So the rate belongs to the role and the base belongs to the person, which is
the ``rate_on_base`` basis migration 0029 already introduced for "grow by 43%
of the Dec book balance". The base is read by ``live_scorecard`` as the same
count for the PRIOR year - see ``_two_month_active`` - so nobody has to type
one in.

Why a rate and not the absolute off the card
────────────────────────────────────────────
0027 seeded absolutes from the calibration cards, and 0029 had to clear them
because for a per-person line the absolute was one named RM's own figure.
Read as a role target, every PB ARM in the bank would have been measured
against Lydia Apanja's 120.7. The rate is the part that is genuinely shared.

Lydia's 120.7 is not exactly 102 x 1.2
──────────────────────────────────────
It is 118.3 % of her base, not 120 %. Alice's 50.4 is exactly 42 x 1.2, and
both cards say 20 %, so 20 % is the rule and Lydia's cell carries a rounding
or a hand adjustment of about two customers. The stated rule is used rather
than the arithmetic of one cell, because the rule is what applies to
everybody.
"""

from django.db import migrations

#: kpi_code -> the rate its own card states.
RATES = {
    "active_customers": 0.20,
    "digital_adoption": 0.50,
}

#: kpi_code -> the base ``live_scorecard`` puts in ``bases`` for it.
BASES = {
    "active_customers": "last_year_active_customers",
    "digital_adoption": "last_year_digital_customers",
}


def set_rates(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    touched = []
    for code, rate in RATES.items():
        rows = Mapping.objects.filter(kpi_code=code)
        for row in rows:
            was = (row.kpi_target, getattr(row, "target_basis", ""))
            row.kpi_target = rate
            row.target_basis = "rate_on_base"
            row.target_base = BASES[code]
            row.save(update_fields=["kpi_target", "target_basis",
                                    "target_base"])
            touched.append(f"{row.role_code}/{code} {was[0]} -> {rate} "
                           f"on {BASES[code]}")

    if touched:
        print(f"  Active / Digital targets: {len(touched)} mapping(s) now a "
              f"rate on the person's own prior-year count - "
              f"{'; '.join(touched[:6])}"
              + (f"; and {len(touched) - 6} more" if len(touched) > 6 else ""))
    else:
        print("  Active / Digital targets: no mapping carries those lines.")


def leave_them(apps, schema_editor):
    """Not reversed to an absolute.

    There is nothing correct to go back to: the absolutes 0027 seeded were one
    named RM's own figures, which is why 0029 cleared them.
    """
    print("  Active / Digital targets: left as a rate - the absolute they "
          "replaced was one named RM's own count.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0043_banca_split_targets"),
    ]

    operations = [
        migrations.RunPython(set_rates, leave_them),
    ]
