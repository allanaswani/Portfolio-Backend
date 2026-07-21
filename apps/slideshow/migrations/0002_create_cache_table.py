from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    """Create the DatabaseCache table (backs DRF throttling).

    Only runs on the app DB. In dev/tests the cache is LocMem, so
    createcachetable finds no DatabaseCache backend and is a no-op.
    """
    if schema_editor.connection.alias != "default":
        return
    call_command("createcachetable", database="default", verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ("slideshow", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
