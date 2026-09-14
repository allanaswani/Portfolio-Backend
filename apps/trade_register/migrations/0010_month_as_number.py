"""Repair the month values already written as names.

The register wrote ``SEPTEMBER`` where ``trade_finance_data.month`` is expected
to hold ``09``. The weekly trade finance report parses that column with

    pd.to_datetime(month + '-' + year, format='%m-%Y')

so one row of it failed the entire report:

    ValueError: time data 'SEPTEMBER-2026' does not match format '%m-%Y'

The report is triggered from the desk's Send Report button, and the script runs
on the host — so the failure never reaches the application, and the desk simply
never receives the report it asked for.

The model now writes ``%m``. This fixes what the old code already put in both
tables. It converts **only** values that are month names: anything already
numeric, and anything unrecognised, is left exactly as it is. A migration that
guesses at data it does not understand is worse than one that skips it.
"""

from django.db import migrations

MONTHS = {
    "JANUARY": "01", "FEBRUARY": "02", "MARCH": "03", "APRIL": "04",
    "MAY": "05", "JUNE": "06", "JULY": "07", "AUGUST": "08",
    "SEPTEMBER": "09", "OCTOBER": "10", "NOVEMBER": "11", "DECEMBER": "12",
}
# The three-letter forms too, in case anything wrote those.
MONTHS.update({name[:3]: number for name, number in MONTHS.items()})


def to_number(value):
    """``'SEPTEMBER'`` → ``'09'``. Anything else comes back unchanged."""
    key = str(value or "").strip().upper()
    return MONTHS.get(key)


def forwards(apps, schema_editor):
    Entry = apps.get_model("trade_register", "TradeRegisterEntry")
    TradeFinance = apps.get_model("staff_management", "TradeFinanceData")

    for model in (Entry, TradeFinance):
        # One UPDATE per distinct name rather than a row-by-row walk: there are
        # at most twelve, and trade_finance_data holds years of rows.
        for name, number in MONTHS.items():
            model.objects.filter(month__iexact=name).update(month=number)


def backwards(apps, schema_editor):
    """Deliberately does nothing.

    Turning the numbers back into names would re-break the report, and there is
    no way to tell a number this migration wrote from one that was always
    there.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("trade_register", "0009_seed_categories_products_and_tariff"),
        ("staff_management", "0014_alter_merchantbanktillmanualdata_table"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
