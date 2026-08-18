"""Seed the canonical trade products with their codes and reference families.

Derived from the distinct product types in Esther's Weekly Trade Transactions
workbook. Amendment/action variants (SETTLEMENT, EXT, BILL, CANCELLATION …) are
NOT separate products — they are captured on the entry as an amendment action,
so only the base products live here.
"""

from django.db import migrations

# (code, name, ref_family, sort_order)
PRODUCTS = [
    # Guarantees → HFCB/GTE/YYMMDD/NN
    ("GTE-BID", "BID BOND", "guarantee", 10),
    ("GTE-APG", "ADVANCE PAYMENT GUARANTEE", "guarantee", 20),
    ("GTE-PBG", "PERFORMANCE BOND", "guarantee", 30),
    ("GTE-CPG", "CREDIT PAYMENT GUARANTEE", "guarantee", 40),
    ("GTE-BG", "BANK GUARANTEE", "guarantee", 50),
    ("GTE-PG", "PAYMENT GUARANTEE", "guarantee", 60),
    ("GTE-SBLC", "SBLC", "guarantee", 70),
    ("GTE-GEN", "GENERAL GUARANTEE", "guarantee", 80),
    ("GTE-RET", "RETENTION GUARANTEE", "guarantee", 90),
    # Import LC → HF#####
    ("ILC-SIGHT", "IMPORT SIGHT LC", "import_lc", 100),
    ("ILC-USANCE", "IMPORT USANCE LC", "import_lc", 110),
    ("ILC-SIGHT-BILL", "IMPORT SIGHT LC BILL", "import_lc", 120),
    ("ILC-USANCE-BILL", "IMPORT USANCE LC BILL", "import_lc", 130),
    # Export LC → HFCB/ELC/YYMMDD/NN
    ("ELC-SIGHT", "EXPORT SIGHT LC", "export_lc", 140),
    ("ELC-SIGHT-BILL", "EXPORT SIGHT LC BILL", "export_lc", 150),
]


def seed(apps, schema_editor):
    TradeProduct = apps.get_model("trade_register", "TradeProduct")
    for code, name, family, order in PRODUCTS:
        TradeProduct.objects.update_or_create(
            code=code,
            defaults={"name": name, "ref_family": family, "sort_order": order, "is_active": True},
        )


def unseed(apps, schema_editor):
    TradeProduct = apps.get_model("trade_register", "TradeProduct")
    TradeProduct.objects.filter(code__in=[p[0] for p in PRODUCTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("trade_register", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
