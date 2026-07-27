"""Align portfolio_profile with the model: branch/segment are nullable.

The model (and 0001_initial) already declare Profile.branch and Profile.segment
as null=True, but the PORTED prod DB was created via `--fake-initial` against the
old backend's table, which had NOT NULL on both columns. That drift made admin/
programmatic user creation 500 (auth_user row committed, then the Profile insert
failed on the NOT NULL branch/segment). This drops the constraints to match the
model. Idempotent: DROP NOT NULL on an already-nullable column is a no-op, so this
is safe on fresh DBs where the columns are created nullable.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0003_retailallocatedportfolioupload"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE portfolio_profile "
                "ALTER COLUMN branch DROP NOT NULL, "
                "ALTER COLUMN segment DROP NOT NULL, "
                "ALTER COLUMN sales_code DROP NOT NULL;"
            ),
            # Reverse is a no-op: re-adding NOT NULL could fail if null rows exist,
            # and the model says these are nullable anyway.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
