"""Adopt ``operating_expense_mapping`` rather than assume it is new.

Finance's GL-to-expense-line mapping has lived in a spreadsheet, so on most
databases this table does not exist and is created here. But the last mapping
table this repo added (``premium_types_mapping``, migration 0019) died on the
host with ``relation ... already exists``, because an ETL had built it first.
The same thing can be true of an expense mapping, so this migration looks
before it writes: it creates the table when absent, adds only the columns a
present table is missing, and never drops or retypes anything.

The guard is deliberately asymmetric about ``gl``. A table that exists without
a ``gl`` column is not this mapping, and inventing the key column on somebody
else's table is not a call a migration gets to make — so it stops with the real
column list, which is recoverable, instead of leaving a screen that 500s.

The unique index on ``gl`` is created only when the existing data allows it.
Finance's own sheet already contains one GL twice (230000023, both rows
identical); duplicates in a table this migration did not fill are Finance's to
reconcile, not a reason to fail a release. The API upserts on ``gl`` either way.

The historical table is new on every database — simple_history owns it — so it
is created normally.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import simple_history.models

TABLE = "operating_expense_mapping"

# Every column NOT NULL DEFAULT '' so it can be added to a table that already
# has rows, matching the model's blank=True, default="".
COLUMNS = {
    "gl":                "varchar(32) NOT NULL DEFAULT ''",
    "expense_type":      "varchar(120) NOT NULL DEFAULT ''",
    "operating_expense": "varchar(160) NOT NULL DEFAULT ''",
    "outflow_type":      "varchar(40) NOT NULL DEFAULT ''",
    "actual_gl_name":    "varchar(160) NOT NULL DEFAULT ''",
    "updated_by":        "varchar(150) NOT NULL DEFAULT ''",
}

CREATE = f"""
    CREATE TABLE {TABLE} (
        id bigserial NOT NULL PRIMARY KEY,
        gl varchar(32) NOT NULL,
        expense_type varchar(120) NOT NULL DEFAULT '',
        operating_expense varchar(160) NOT NULL DEFAULT '',
        outflow_type varchar(40) NOT NULL DEFAULT '',
        actual_gl_name varchar(160) NOT NULL DEFAULT '',
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by varchar(150) NOT NULL DEFAULT ''
    )
"""


def _columns(cur):
    """Columns the table really has, or None when it is absent.

    pg_attribute via to_regclass rather than information_schema.columns, which
    does not list materialized views - the same call the data-health check uses.
    """
    cur.execute("SELECT to_regclass(%s)", [TABLE])
    if cur.fetchone()[0] is None:
        return None
    cur.execute(
        "SELECT attname FROM pg_attribute "
        "WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped",
        [TABLE],
    )
    return {r[0].lower() for r in cur.fetchall()}


def adopt(apps, schema_editor):
    cur = schema_editor.connection.cursor()
    found = _columns(cur)

    if found is None:
        print(f"\n  {TABLE}: not present - creating it.")
        cur.execute(CREATE)
        found = set(COLUMNS) | {"id", "updated_at"}
    else:
        print(f"\n  {TABLE}: already exists with columns: {', '.join(sorted(found))}")

    if "gl" not in found:
        raise RuntimeError(
            f'"{TABLE}" has no "gl" column, which is the key this mapping is '
            f'identified by. Columns present: {", ".join(sorted(found))}. '
            "Either that table is something else, or the model needs "
            "re-pointing at whatever names a GL account in it."
        )

    # auto_now writes updated_at on every save, so a pre-existing table without
    # it would break the first edit. Added with a default so existing rows are
    # valid; Django still supplies the value from then on.
    if "updated_at" not in found:
        cur.execute(
            f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS "
            f"updated_at timestamptz NOT NULL DEFAULT now()"
        )
        found.add("updated_at")

    added = []
    for column, ddl in COLUMNS.items():
        if column not in found:
            cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {column} {ddl}")
            added.append(column)
    print(f"  {TABLE}: added missing column(s): {', '.join(added)}" if added
          else f"  {TABLE}: every column the model needs is already there.")

    # The model marks expense_type and outflow_type db_index=True. Creating
    # them here keeps the database matching the migration state; at 249 rows
    # neither index earns its keep, but a state/schema divergence is the kind
    # of thing a later migration trips over.
    for column in ("expense_type", "outflow_type"):
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_operating_expense_mapping_{column} "
            f"ON {TABLE} ({column})")

    cur.execute(f"""
        SELECT count(*), string_agg(DISTINCT gl, ' | ')
        FROM {TABLE} GROUP BY gl HAVING count(*) > 1
    """)
    clashes = cur.fetchall()
    if clashes:
        print(f"  {TABLE}: NOT adding the unique index - these GLs already "
              f"appear more than once:")
        for n, spellings in clashes:
            print(f"    {n}x  {spellings}")
        print("  Correct them on the Operating Expense Mapping tab, then ask "
              "for the index in a follow-up migration.")
        return
    cur.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uniq_operating_expense_mapping_gl "
        f"ON {TABLE} (gl)")


def unadopt(apps, schema_editor):
    """Reverse leaves the table alone - dropping a populated table somebody
    else may own, to undo a model definition, is not a trade worth making."""
    print(f"\n  {TABLE}: left in place - this migration may not have created it.")


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('staff_management', '0021_ensure_scorecard_tables'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='OperatingExpenseMapping',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('gl', models.CharField(db_index=True, help_text='General ledger account code, e.g. 170150001.', max_length=32, unique=True, verbose_name='GL')),
                        ('expense_type', models.CharField(db_index=True, help_text='Roll-up line, e.g. "Staff costs", "ICT Expense".', max_length=120, verbose_name='Expense type')),
                        ('operating_expense', models.CharField(help_text='The expense line as Finance names it, e.g. "Software".', max_length=160, verbose_name='Operating expense')),
                        ('outflow_type', models.CharField(blank=True, db_index=True, default='', help_text='Observed values: "Controllable", "Installed", or blank.', max_length=40, verbose_name='Outflow type')),
                        ('actual_gl_name', models.CharField(blank=True, default='', help_text="The GL's own name, where it differs from the expense line.", max_length=160, verbose_name='Actual GL name')),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        ('updated_by', models.CharField(blank=True, default='', max_length=150)),
                    ],
                    options={
                        'verbose_name': 'Operating expense mapping',
                        'verbose_name_plural': 'Operating expense mappings',
                        'db_table': 'operating_expense_mapping',
                        'ordering': ['gl'],
                        'managed': True,
                    },
                ),
            ],
            database_operations=[migrations.RunPython(adopt, unadopt)],
        ),
        migrations.CreateModel(
            name='HistoricalOperatingExpenseMapping',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('gl', models.CharField(db_index=True, help_text='General ledger account code, e.g. 170150001.', max_length=32, verbose_name='GL')),
                ('expense_type', models.CharField(db_index=True, help_text='Roll-up line, e.g. "Staff costs", "ICT Expense".', max_length=120, verbose_name='Expense type')),
                ('operating_expense', models.CharField(help_text='The expense line as Finance names it, e.g. "Software".', max_length=160, verbose_name='Operating expense')),
                ('outflow_type', models.CharField(blank=True, db_index=True, default='', help_text='Observed values: "Controllable", "Installed", or blank.', max_length=40, verbose_name='Outflow type')),
                ('actual_gl_name', models.CharField(blank=True, default='', help_text="The GL's own name, where it differs from the expense line.", max_length=160, verbose_name='Actual GL name')),
                ('updated_at', models.DateTimeField(blank=True, editable=False)),
                ('updated_by', models.CharField(blank=True, default='', max_length=150)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical Operating expense mapping',
                'verbose_name_plural': 'historical Operating expense mappings',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
