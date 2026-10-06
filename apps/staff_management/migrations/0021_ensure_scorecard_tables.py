"""Create the scorecard tables that 0003 is recorded as having created.

On 6 Oct 2026 production returned 500 on
``/staff_management/monthly-performance-detail/self/`` and
``.../monthly-performance-summary/rm/`` with
``relation "sc_employee_monthly_performance" does not exist`` - while
``staff_management.0003`` was recorded as applied. This repo's migrations are
shadowed by legacy ``django_migrations`` rows from the old project, so a
migration can be marked applied without its DDL ever having run (the same trap
as the ``0001_initial`` rows).

Re-running 0003 is not an option: most of its tables do exist, so it would fail
on the first one. This asks the database which tables are actually there and
creates only the missing ones, using the historical model state so the result is
identical to what 0003 would have produced - same columns, indexes and
constraints - with no hand-written DDL to drift from the models.

Idempotent: on an environment where the tables exist, it does nothing. The
reverse is deliberately a no-op; dropping tables to undo a repair would destroy
data this migration never created.
"""
from django.db import migrations

# Everything staff_management.0003 creates, including the simple_history tables.
# Named rather than discovered so this migration cannot grow new side effects as
# the app gains models.
MODELS = (
    "ScKpi",
    "ScRole",
    "ScRoleKpiMapping",
    "ScEmployeeMonthlyPerformance",
    "ScEmployeePerformanceActual",
    "HistoricalScRole",
    "HistoricalScRoleKpiMapping",
    "HistoricalScEmployeePerformanceActual",
)


def create_missing(apps, schema_editor):
    existing = set(schema_editor.connection.introspection.table_names())
    for name in MODELS:
        try:
            model = apps.get_model("staff_management", name)
        except LookupError:
            continue
        if model._meta.db_table in existing:
            continue
        schema_editor.create_model(model)
        print(f"  created missing table {model._meta.db_table}")


def noop(apps, schema_editor):
    """Nothing to undo - see the module docstring."""


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0020_seed_premium_type_mappings"),
    ]

    operations = [
        migrations.RunPython(create_missing, noop),
    ]
