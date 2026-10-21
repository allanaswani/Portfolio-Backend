"""Put the six banca split targets on the MODEL, not in the database again.

Migration 0043 added these columns to ``branch_employee_dmc_data`` itself,
with raw ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``. The card reads that
table by asking the database what columns it has, so the targets worked from
the moment 0043 ran - and nobody could ever SET one.

The reason is that the model did not declare them. ``BranchEmployeeDmcData``
is served by a ``ModelSerializer`` with ``fields = "__all__"``, so a column
the model does not know about is invisible to the API, absent from the
sales-staff CSV template and silently dropped by the uploader. Reported as
"the sales staff template haina the new insurance targets".

So this is STATE ONLY. The columns are already on every database that ran
0043 - production, and a fresh test database too, because 0043 creates them
after Django has built the table - and issuing ``ADD COLUMN`` a second time
would fail the deploy. ``SeparateDatabaseAndState`` with no database
operations tells Django the model and the table already agree.

Only the per-person table. ``branch_final_employee_dmc_data`` is one row per
BRANCH and 0043 did not touch it; lending a branch's figure to an RM is a
mistake this codebase has already made once and reverted.
"""

from django.db import migrations, models

#: Nullable with no default, matching the DDL 0043 issued. A column full of
#: noughts would read as "the plan is nought", which is a target; NULL reads
#: as "no plan set", which is what an unfilled column means.
FIELDS = {
    "target_life_excl_ni": models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True),
    "target_life_ni": models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True),
    "target_life_elimu_gi": models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True),
    "target_non_life_gi": models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True),
    "target_non_life_medical": models.DecimalField(
        max_digits=18, decimal_places=2, blank=True, null=True),
    "target_life_volume": models.IntegerField(blank=True, null=True),
}


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0047_income_base_is_last_years_target"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="branchemployeedmcdata",
                    name=name,
                    field=field,
                )
                for name, field in FIELDS.items()
            ],
        ),
    ]
