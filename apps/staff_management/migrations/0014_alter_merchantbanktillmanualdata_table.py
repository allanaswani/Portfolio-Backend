"""Point the merchant bank tills model at the renamed warehouse table.

The warehouse dropped the "_manual" suffix. The model is ``managed = False``,
so this records the new name in migration state and emits NO SQL — confirmed
with ``sqlmigrate``, which prints "(no-op)". It must stay that way: an
``ALTER TABLE ... RENAME`` here would be this application reaching into a table
the ETLs own.

The old table still exists and is no longer filled, which is why data health
reported it empty rather than missing.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('staff_management', '0013_historicalteamleaderbranch_historicaldsrsalescode_and_more'),
    ]

    operations = [
        migrations.AlterModelTable(
            name='merchantbanktillmanualdata',
            table='weighted_sales_seller_bank_till_data_dump',
        ),
    ]
