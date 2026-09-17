"""Adopt ``premium_types_mapping`` — it already exists in production.

The first version of this migration created the table and died on the host with
``relation "premium_types_mapping" already exists``. The second one adopted it
but still assumed Django's implicit ``id``, and its own guard stopped the
deploy to say so. The real table is five text columns and no surrogate key::

    product | vic_check | life_policy_check | premium_type | policy_category

So the model now matches the table: ``product`` is the primary key, and the
``updated_at`` / ``updated_by`` columns of the earlier draft are gone rather
than being bolted onto somebody else's table.

What is left for the database to do is only the difference. On a fresh database
(a developer's, the test runner's) the table is created. On production it
already exists with exactly the right columns, so nothing happens at all —
which is checked, reported, and never assumed.

The historical table is new either way; simple_history owns it, so it is
created normally.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import simple_history.models

TABLE = "premium_types_mapping"

# What the model needs. Every column is NOT NULL DEFAULT '' so it can be added
# to a table that already has rows, matching CharField(blank=True, default="").
COLUMNS = {
    "product":           "varchar(255) NOT NULL DEFAULT ''",
    "vic_check":         "varchar(100) NOT NULL DEFAULT ''",
    "life_policy_check": "varchar(100) NOT NULL DEFAULT ''",
    "premium_type":      "varchar(100) NOT NULL DEFAULT ''",
    "policy_category":   "varchar(100) NOT NULL DEFAULT ''",
}

CREATE = f"""
    CREATE TABLE {TABLE} (
        product varchar(255) NOT NULL PRIMARY KEY,
        vic_check varchar(100) NOT NULL DEFAULT '',
        life_policy_check varchar(100) NOT NULL DEFAULT '',
        premium_type varchar(100) NOT NULL DEFAULT '',
        policy_category varchar(100) NOT NULL DEFAULT ''
    )
"""


def _columns(cur):
    """Columns the table really has, or None when it is absent.

    pg_attribute via to_regclass rather than information_schema.columns, which
    does not list materialized views — the same call the data-health check uses.
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
        print(f"\n  {TABLE}: not present — creating it.")
        cur.execute(CREATE)
        # Fall through to the index. The PRIMARY KEY above makes `product`
        # unique EXACTLY; the case-insensitive index below is a separate thing,
        # and returning here left a fresh database able to hold "ipp" and "IPP"
        # side by side — the very pair this table must not contain.
        found = set(COLUMNS)
    else:
        print(f"\n  {TABLE}: already exists with columns: {', '.join(sorted(found))}")

    # `product` is the model's primary key. Without it there is nothing to
    # adopt — and inventing a key column on a table somebody else's loader
    # writes is not a call this migration gets to make. Fail with the real
    # column list: a stopped migrate is recoverable, a screen that 500s on a
    # missing column is a support ticket.
    if "product" not in found:
        raise RuntimeError(
            f'"{TABLE}" has no "product" column, which is this model\'s primary '
            f'key. Columns present: {", ".join(sorted(found))}. '
            "The model needs to be re-pointed at whatever identifies a product "
            "in that table."
        )

    added = []
    for column, ddl in COLUMNS.items():
        if column not in found:
            cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {column} {ddl}")
            added.append(column)
    print(f"  {TABLE}: added missing column(s): {', '.join(added)}" if added
          else f"  {TABLE}: every column the model needs is already there.")

    # Django treats `product` as the pk whether or not the database agrees, so
    # a duplicate would make .get() ambiguous. Add the unique index when the
    # data allows it; report and carry on when it does not, because existing
    # rows are Bancassurance's to reconcile, not a reason to fail a release.
    # The API refuses new duplicates either way.
    cur.execute(f"""
        SELECT count(*), string_agg(DISTINCT product, ' | ')
        FROM {TABLE} GROUP BY lower(product) HAVING count(*) > 1
    """)
    clashes = cur.fetchall()
    if clashes:
        print(f"  {TABLE}: NOT adding the unique index — these products already "
              f"appear more than once:")
        for n, spellings in clashes:
            print(f"    {n}x  {spellings}")
        print("  Merge them on the Insurance Policies screen, then ask for the "
              "index in a follow-up migration.")
        return
    cur.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uniq_premium_types_mapping_product "
        f"ON {TABLE} (lower(product))")


def unadopt(apps, schema_editor):
    """Reverse leaves the table alone — it was not created here in the case
    that matters, and dropping somebody else's populated table to undo a model
    definition is not a trade this migration gets to make."""
    print(f"\n  {TABLE}: left in place — this migration did not create it.")


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('staff_management', '0018_fill_dmc_target_properties'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='PremiumTypeMapping',
                    fields=[
                        ('product', models.CharField(help_text='Product name as it appears on the policy, e.g. WHOLE LIFE.', max_length=255, primary_key=True, serialize=False, verbose_name='Product')),
                        ('vic_check', models.CharField(blank=True, default='', help_text='Observed value: "vic".', max_length=100)),
                        ('life_policy_check', models.CharField(blank=True, default='', help_text='Observed value: "life".', max_length=100)),
                        ('premium_type', models.CharField(blank=True, default='', help_text='Observed value: "non-motor".', max_length=100)),
                        ('policy_category', models.CharField(blank=True, default='', help_text='Observed value: "Life".', max_length=100)),
                    ],
                    options={
                        'verbose_name': 'Premium type mapping',
                        'verbose_name_plural': 'Premium type mappings',
                        'db_table': 'premium_types_mapping',
                        'ordering': ['product'],
                        'managed': True,
                    },
                ),
            ],
            database_operations=[migrations.RunPython(adopt, unadopt)],
        ),
        migrations.CreateModel(
            name='HistoricalPremiumTypeMapping',
            fields=[
                ('product', models.CharField(db_index=True, help_text='Product name as it appears on the policy, e.g. WHOLE LIFE.', max_length=255, verbose_name='Product')),
                ('vic_check', models.CharField(blank=True, default='', help_text='Observed value: "vic".', max_length=100)),
                ('life_policy_check', models.CharField(blank=True, default='', help_text='Observed value: "life".', max_length=100)),
                ('premium_type', models.CharField(blank=True, default='', help_text='Observed value: "non-motor".', max_length=100)),
                ('policy_category', models.CharField(blank=True, default='', help_text='Observed value: "Life".', max_length=100)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical Premium type mapping',
                'verbose_name_plural': 'historical Premium type mappings',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
