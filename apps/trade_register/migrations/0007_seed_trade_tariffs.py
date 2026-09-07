"""Seed the tariff book with one line per product family, and map products to it.

**These are structural placeholders, not the bank's published rates.** Every
line is seeded on ``none`` — the basis that calculates nothing — so no
transaction is priced by this migration and nothing that exists today changes
value. What it creates is the mapping: each product points at the tariff line it
is charged under, so when the desk supplies the real rates, one edit per tariff
prices every product on it.

The excise rate carries the statutory default (see ``DEFAULT_EXCISE_RATE``);
confirm it with the trade desk before relying on the figures.
"""

from django.db import migrations
from decimal import Decimal

EXCISE = Decimal("20")

# (code, name, description, [product codes it covers], sort_order)
TARIFFS = [
    ("TRF-GTE", "Guarantees & Bonds",
     "Bid bonds, advance payment, performance, credit payment, bank, payment, "
     "SBLC, general and retention guarantees.",
     ["GTE-BID", "GTE-APG", "GTE-PBG", "GTE-CPG", "GTE-BG", "GTE-PG",
      "GTE-SBLC", "GTE-GEN", "GTE-RET"], 10),
    ("TRF-ILC", "Import Letters of Credit",
     "Import LCs at sight and usance, and their bills.",
     ["ILC-SIGHT", "ILC-USANCE", "ILC-SIGHT-BILL", "ILC-USANCE-BILL"], 20),
    ("TRF-ELC", "Export Letters of Credit",
     "Export LCs at sight and their bills.",
     ["ELC-SIGHT", "ELC-SIGHT-BILL"], 30),
]


def seed(apps, schema_editor):
    Tariff = apps.get_model("trade_register", "TradeTariff")
    Product = apps.get_model("trade_register", "TradeProduct")

    for code, name, description, products, order in TARIFFS:
        tariff, _ = Tariff.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "sort_order": order,
                "is_active": True,
                # Deliberately not priced: seeding a made-up rate would put
                # wrong money on real transactions.
                "commission_basis": "none",
                "commission_rate": Decimal("0"),
                "minimum_commission": Decimal("0"),
                "excise_rate": EXCISE,
            },
        )
        # Map only products that have not already been pointed somewhere else.
        Product.objects.filter(code__in=products, tariff__isnull=True).update(tariff=tariff)


def unseed(apps, schema_editor):
    Tariff = apps.get_model("trade_register", "TradeTariff")
    Product = apps.get_model("trade_register", "TradeProduct")
    codes = [c for c, _, _, _, _ in TARIFFS]
    Product.objects.filter(tariff__code__in=codes).update(tariff=None)
    Tariff.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("trade_register", "0006_tradetariff_historicaltraderegisterentry_excise_duty_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
