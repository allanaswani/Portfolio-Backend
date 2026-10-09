"""Separate a ROLE target from one person's figure that got scraped into it.

``ScRoleKpiMapping.kpi_target`` is per ROLE. Migration 0027 filled it from the
eight calibration cards, which means that for the FINANCIAL lines it holds one
named RM's own closing balance:

    sme_rm        asset_growth      14,729,931.79   <- Charles Muchiri's book
    pb_rm         asset_growth    2,009,063,440.79  <- Vincent Ogare's book
    commercial_rm asset_growth    1,752,701,010.45  <- Juspher Muriithi's book

Read as a role target, every SME RM in the bank would be scored against Charles
Muchiri's balance. Those are cleared here.

What is left is the targets that genuinely ARE one number for everybody on the
card, and they are worth keeping, because they are the only place several KPIs
have a target at all:

    PAR 2.5%   NPS 60%   coverage 80%   audit 1.65   errors 5%
    TAT 7 days   weighted TAT 100%   training 48/60 h
    property 2/3/1.25 units and 16.4m/24.6m/10.25m   covenants 12   tooling 12

Asset Growth keeps a target, as a RATE on the person's own base
──────────────────────────────────────────────────────────────
Every card states it in the RM's own measure of success - "Grow by 43% of the
Dec book Balance" - and the December book is in the warehouse, per RM. So the
rate goes in ``kpi_target`` with ``target_basis = "rate_on_base"`` and
``target_base = "december_loan_book"``, and the card works it out from the
person's own opening balance instead of from a column that is not on the
per-person DMC table.

The rates are the ones the eight cards state: 43% Business Banking, 38%
Personal Banking, 36% Ultimate, 21% Commercial, 100% Diaspora.

**Worth knowing before trusting it:** on three of those five cards the desk's
own assigned figure does NOT equal the stated rate times the stated base
(Personal Banking's works out at 3.1%, Ultimate's at 23%, Commercial's at 10%).
The stated rate is what the card tells the RM they are measured on, so that is
what is used - and a ``target_asset_growth_value`` on the per-person DMC load
overrides it the moment one exists, because an explicit figure always beats a
derived one.

Seed-only-if-unset for the new columns, like 0020, 0023 and 0027: a target the
desk has since tuned by hand is left alone.
"""

from django.db import migrations, models

#: Targets that are one number for everybody on the card. Anything not in here
#: and not given a rate below is cleared.
ROLE_WIDE = {
    "par", "nps", "portfolio_nps", "portfolo_nps",
    "portfolio_coverage_engagement", "audit", "errors", "leave_management",
    "tat_loan", "weigted_tat",
    "weigted_tat_sla_service_standards_query_response_time",
    "weighted_sales_dashboard", "weighted_sales",
    "business_banking_training", "personal_banking_training",
    "banking_covenant_tracking_should_be_in_iapply",
    "tooling_and_account_planning_all_customers",
    "number_of_property", "value_of_property_sales",
    "new_customer_min_turnover_of_10m", "new_customer_min_turnover_of_50m",
    "ultimate_rm_new_customers",
}

#: (role_code, kpi_code) -> (rate, base). The rate each card states.
RATES = {
    ("sme_rm", "asset_growth"): (0.43, "december_loan_book"),
    ("sme_arm", "asset_growth"): (0.43, "december_loan_book"),
    ("sme_bbc", "asset_growth"): (0.43, "december_loan_book"),
    ("pb_rm", "asset_growth"): (0.38, "december_loan_book"),
    ("pb_arm", "asset_growth"): (0.38, "december_loan_book"),
    ("pb_bbc", "asset_growth"): (0.38, "december_loan_book"),
    ("ultimate_rm", "asset_growth"): (0.36, "december_loan_book"),
    ("commercial_rm", "asset_growth"): (0.21, "december_loan_book"),
    ("commercial_rm_trade", "asset_growth"): (0.21, "december_loan_book"),
    ("diaspora_rm", "asset_growth"): (1.00, "december_loan_book"),
    ("diaspora_arm", "asset_growth"): (1.00, "december_loan_book"),
}


def apply(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    rated = cleared = kept = 0
    for mapping in Mapping.objects.all():
        key = (mapping.role_code, mapping.kpi_code)
        if key in RATES:
            rate, base = RATES[key]
            # Only if nobody has set a basis already - a desk that has tuned
            # this must not have it overwritten.
            if not mapping.target_basis:
                mapping.kpi_target = rate
                mapping.target_basis = "rate_on_base"
                mapping.target_base = base
                mapping.save(update_fields=["kpi_target", "target_basis",
                                            "target_base"])
                rated += 1
            continue
        if mapping.kpi_code in ROLE_WIDE:
            kept += 1
            continue
        if mapping.kpi_target is not None:
            mapping.kpi_target = None
            mapping.save(update_fields=["kpi_target"])
            cleared += 1

    print(f"\n  role targets: {kept} kept as role-wide, {rated} turned into a "
          f"rate on the person's own base, {cleared} cleared because they were "
          f"one named RM's own figure.")


def unapply(apps, schema_editor):
    """Nothing to restore: the cleared values were one person's balance and
    putting them back would re-create the bug."""


class Migration(migrations.Migration):

    dependencies = [("staff_management", "0028_scorecard_signoff")]

    operations = [
        migrations.AddField(
            model_name="scrolekpimapping",
            name="target_basis",
            field=models.CharField(
                blank=True, default="", max_length=20,
                choices=[("", "An absolute figure"),
                         ("rate_on_base", "A rate on the person's own base")],
                help_text="How kpi_target is to be read. Blank means it is the "
                          "target itself; rate_on_base means multiply it by "
                          "the base named in target_base."),
        ),
        migrations.AddField(
            model_name="scrolekpimapping",
            name="target_base",
            field=models.CharField(
                blank=True, default="", max_length=40,
                help_text="Which of the person's own figures the rate applies "
                          "to, e.g. december_loan_book."),
        ),
        migrations.AddField(
            model_name="historicalscrolekpimapping",
            name="target_basis",
            field=models.CharField(
                blank=True, default="", max_length=20,
                choices=[("", "An absolute figure"),
                         ("rate_on_base", "A rate on the person's own base")],
                help_text="How kpi_target is to be read. Blank means it is the "
                          "target itself; rate_on_base means multiply it by "
                          "the base named in target_base."),
        ),
        migrations.AddField(
            model_name="historicalscrolekpimapping",
            name="target_base",
            field=models.CharField(
                blank=True, default="", max_length=40,
                help_text="Which of the person's own figures the rate applies "
                          "to, e.g. december_loan_book."),
        ),
        migrations.RunPython(apply, unapply),
    ]
