"""Six banca target columns on the per-person DMC table.

The desk splits bancassurance further than the roster did. It carried
``target_banca_life`` and ``target_banca_non_life``; the plan is actually set
on six lines:

    target_life_excl_ni        life, excluding NI
    target_life_ni             life, NI
    target_life_elimu_gi       Elimu, written through the GI book
    target_non_life_gi         non-life, GI
    target_non_life_medical    non-life, medical
    target_life_volume         the COUNT of life policies, not their value

Added to ``branch_employee_dmc_data``, the per-person table, so each is one
person's own plan. ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``, like
migration 0019 before it: this is a warehouse table the ETL writes and this
repo does not own, so a column is added if it is missing and left alone
otherwise, and nothing is ever dropped.

Lower case, and ``_ni`` not ``_NI``
───────────────────────────────────
Unquoted identifiers in Postgres fold to lower case, so ``target_life_NI``
and ``target_life_ni`` are the same column, but a quoted ``"target_life_NI"``
is a THIRD, different one that only ever matches when quoted. Writing them
lower case is what keeps the ETL, this migration and the scorecard reader all
naming the same column. The card reader picks any ``target_*`` column up
automatically - see ``roster_target_row`` - so nothing else has to change for
these to be readable.

NUMERIC, not bigint
───────────────────
``target_pbt_revenue`` is a bigint and premiums are not whole shillings. These
are money and a count, and the five money columns are NUMERIC(18, 2) so a plan
of 67,190.50 is not silently truncated. ``target_life_volume`` is a policy
count and is an integer.
"""

from django.db import migrations

TABLE = "branch_employee_dmc_data"

#: column → DDL. Nullable with no default on purpose: a column full of
#: noughts would read as "the plan is nought", which is a target, where NULL
#: reads as "no plan set", which is what an unfilled column means. The card
#: already tells those two apart.
COLUMNS = {
    "target_life_excl_ni": "numeric(18,2)",
    "target_life_ni": "numeric(18,2)",
    "target_life_elimu_gi": "numeric(18,2)",
    "target_non_life_gi": "numeric(18,2)",
    "target_non_life_medical": "numeric(18,2)",
    "target_life_volume": "integer",
}


def add_columns(apps, schema_editor):
    cur = schema_editor.connection.cursor()

    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = %s", [TABLE])
    if cur.fetchone() is None:
        # Not a failure. The warehouse tables are absent from a fresh test
        # database and from any host where the ETL has not run yet, and a
        # release must not stop for that.
        print(f"  {TABLE}: not present - nothing to add. The ETL creates it.")
        return

    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s", [TABLE])
    found = {row[0].lower() for row in cur.fetchall()}

    added, already = [], []
    for column, ddl in COLUMNS.items():
        if column in found:
            already.append(column)
            continue
        cur.execute(
            f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {column} {ddl}")
        added.append(column)

    if added:
        print(f"  {TABLE}: added {len(added)} banca target column(s) - "
              f"{', '.join(added)}")
    if already:
        print(f"  {TABLE}: {len(already)} already there - "
              f"{', '.join(already)}")


def leave_them(apps, schema_editor):
    """Deliberately not a drop.

    Reversing this migration must not delete a plan somebody has typed in. The
    columns are nullable and nothing requires them, so leaving them costs
    nothing and dropping them would lose the year's targets.
    """
    print(f"  {TABLE}: columns kept - dropping them would lose the targets.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0042_scscorecarddispatch"),
    ]

    operations = [
        migrations.RunPython(add_columns, leave_them),
    ]
