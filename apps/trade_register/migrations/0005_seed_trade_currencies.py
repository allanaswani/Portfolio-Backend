"""Seed the currency list the trade desk can write in.

The form used to offer ten currencies hard-coded in the frontend, which is why
the desk found currencies missing — adding one meant a code change and a
deploy. The list below covers what a Kenyan bank's trade desk actually sees:
the local unit, the majors, the Gulf and Asian trade currencies, and the East
African neighbours. It is only a starting point — Administration can add to
``trade_register_currency`` without touching code.

Idempotent, so re-running is safe, and it never deactivates a currency an
administrator has added.
"""

from django.db import migrations

# (code, name, sort_order) — lower sorts first, so the ones actually used lead.
CURRENCIES = [
    ("KES", "Kenyan Shilling", 1),
    ("USD", "US Dollar", 2),
    ("EUR", "Euro", 3),
    ("GBP", "Pound Sterling", 4),

    ("AED", "UAE Dirham", 10),
    ("CHF", "Swiss Franc", 11),
    ("JPY", "Japanese Yen", 12),
    ("CNY", "Chinese Yuan Renminbi", 13),
    ("INR", "Indian Rupee", 14),
    ("ZAR", "South African Rand", 15),
    ("SAR", "Saudi Riyal", 16),
    ("QAR", "Qatari Riyal", 17),
    ("KWD", "Kuwaiti Dinar", 18),
    ("OMR", "Omani Rial", 19),
    ("BHD", "Bahraini Dinar", 20),

    ("AUD", "Australian Dollar", 30),
    ("CAD", "Canadian Dollar", 31),
    ("SEK", "Swedish Krona", 32),
    ("NOK", "Norwegian Krone", 33),
    ("DKK", "Danish Krone", 34),
    ("SGD", "Singapore Dollar", 35),
    ("HKD", "Hong Kong Dollar", 36),
    ("NZD", "New Zealand Dollar", 37),
    ("TRY", "Turkish Lira", 38),
    ("THB", "Thai Baht", 39),
    ("MYR", "Malaysian Ringgit", 40),
    ("KRW", "South Korean Won", 41),

    ("UGX", "Ugandan Shilling", 50),
    ("TZS", "Tanzanian Shilling", 51),
    ("RWF", "Rwandan Franc", 52),
    ("BIF", "Burundian Franc", 53),
    ("SSP", "South Sudanese Pound", 54),
    ("ETB", "Ethiopian Birr", 55),
    ("SOS", "Somali Shilling", 56),
    ("EGP", "Egyptian Pound", 57),
    ("NGN", "Nigerian Naira", 58),
    ("GHS", "Ghanaian Cedi", 59),
    ("ZMW", "Zambian Kwacha", 60),
    ("MUR", "Mauritian Rupee", 61),
    ("MWK", "Malawian Kwacha", 62),
    ("BWP", "Botswana Pula", 63),
    ("XOF", "West African CFA Franc", 64),
    ("XAF", "Central African CFA Franc", 65),
]


def seed(apps, schema_editor):
    Currency = apps.get_model("trade_register", "TradeCurrency")
    for code, name, order in CURRENCIES:
        Currency.objects.update_or_create(
            code=code,
            defaults={"name": name, "sort_order": order, "is_active": True},
        )


def unseed(apps, schema_editor):
    Currency = apps.get_model("trade_register", "TradeCurrency")
    Currency.objects.filter(code__in=[c for c, _, _ in CURRENCIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("trade_register", "0004_tradecurrency_and_more")]
    operations = [migrations.RunPython(seed, unseed)]
