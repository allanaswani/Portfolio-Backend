"""The desk's product catalogue and the bank's published tariff.

Three things are seeded here, all supplied by the trade desk on 2026-09-08:

1. **Four product categories** — the grouping the desk works in, and the first
   half of the key that finds a charge.
2. **The full product list** with the bank's own codes where the desk has them.
   The guarantees carry codes (14116 = BID BOND GUARANTEE); the letters of
   credit and the bills were supplied without codes, so theirs are left as
   placeholders rather than invented — a made-up product code would be indexed,
   reported on, and eventually believed.
3. **The tariff**, transcribed from the bank's published tariff book.

Existing products are re-pointed at their new category and kept: the register
already has transactions against them, and a product referenced by a
transaction must not be deleted. Products the desk's new list drops are marked
inactive, so they vanish from the dropdown while their history stays readable.

Everything is idempotent (``update_or_create``) so re-running is safe.
"""

from decimal import Decimal

from django.db import migrations

FLAT = "flat"
PER_QUARTER = "per_quarter"
PER_MONTH = "per_month"
PER_INSTANCE = "per_instance"
NONE = "none"

GUARANTEE = "guarantee"
IMPORT_LC = "import_lc"
EXPORT_LC = "export_lc"

# ── Categories ────────────────────────────────────────────────────────────────
CATEGORIES = [
    ("LG", "LETTERS OF GUARANTEE", 10),
    ("LC", "LETTERS OF CREDIT", 20),
    ("BLC", "BILLS UNDER LETTER OF CREDIT", 30),
    ("BDC", "BILLS UNDER DOCUMENTARY COLLECTION", 40),
]

# ── Products: (code, name, category code, ref family, sort) ───────────────────
# Codes come from the desk. Where none was given the code is a placeholder
# prefixed "TR-" so it is obviously not a bank product code.
PRODUCTS = [
    # LETTERS OF GUARANTEE — the desk supplied real codes for these.
    ("14116", "BID BOND GUARANTEE", "LG", GUARANTEE, 10),
    ("14117", "PERFORMANCE BOND GUARANTEE", "LG", GUARANTEE, 20),
    ("14123", "ADVANCE PAYMENT GUARANTEE", "LG", GUARANTEE, 30),
    ("14104", "PAYMENT GUARANTEE", "LG", GUARANTEE, 40),
    ("14110", "IMMIGRATION BOND GUARANTEE", "LG", GUARANTEE, 50),
    ("14107", "CUSTOM BOND GUARANTEE", "LG", GUARANTEE, 60),
    ("14118", "RETENTION MONEY GUARANTEE", "LG", GUARANTEE, 70),
    ("14113", "SHIPPING GUARANTEE", "LG", GUARANTEE, 80),
    ("14103", "SURETY UNDERTAKING GUARANTEE", "LG", GUARANTEE, 90),
    ("14101", "ADVISE OF INCOMING GUARANTEE", "LG", GUARANTEE, 100),
    ("14102", "CONVENTIONAL DEMAND BANK GUARANTEE", "LG", GUARANTEE, 110),

    # LETTERS OF CREDIT — no codes supplied.
    ("TR-LC-SBLC", "STANDBY LETTER OF CREDIT (SBLC)", "LC", GUARANTEE, 200),
    ("TR-LC-IMP-SIGHT", "SIGHT IMPORT LETTER OF CREDIT", "LC", IMPORT_LC, 210),
    ("TR-LC-IMP-USANCE", "USANCE IMPORT LETTER OF CREDIT", "LC", IMPORT_LC, 220),
    ("TR-LC-IMP-REVOLVING", "IMPORT REVOLVING LETTER OF CREDIT", "LC", IMPORT_LC, 230),
    ("TR-LC-EXP-USANCE", "USANCE EXPORT LETTER OF CREDIT", "LC", EXPORT_LC, 240),
    ("TR-LC-EXP-SIGHT", "SIGHT EXPORT LETTER OF CREDIT", "LC", EXPORT_LC, 250),
    ("TR-LC-EXP-TRANSFERABLE", "EXPORT TRANSFERABLE LETTER OF CREDIT", "LC", EXPORT_LC, 260),

    # BILLS UNDER LETTER OF CREDIT — no codes supplied.
    ("TR-BLC-IMP-SIGHT", "IMPORT SIGHT BILL UNDER LC", "BLC", IMPORT_LC, 300),
    ("TR-BLC-IMP-USANCE", "IMPORT USANCE BILL UNDER LC", "BLC", IMPORT_LC, 310),
    ("TR-BLC-EXP-SIGHT", "EXPORT SIGHT BILL UNDER LC", "BLC", EXPORT_LC, 320),
    ("TR-BLC-EXP-USANCE", "EXPORT USANCE BILL UNDER LC", "BLC", EXPORT_LC, 330),

    # BILLS UNDER DOCUMENTARY COLLECTION — no codes supplied.
    ("TR-BDC-IMP-SIGHT", "IMPORT SIGHT BILL UNDER COLLECTION", "BDC", IMPORT_LC, 400),
    ("TR-BDC-IMP-USANCE", "IMPORT USANCE BILL UNDER COLLECTION", "BDC", IMPORT_LC, 410),
    ("TR-BDC-AVALIZED", "AVALIZED IMPORT COLLECTION", "BDC", IMPORT_LC, 420),
    ("TR-BDC-EXP-SIGHT", "EXPORT SIGHT BILL UNDER COLLECTION", "BDC", EXPORT_LC, 430),
    ("TR-BDC-EXP-USANCE", "EXPORT USANCE BILL UNDER COLLECTION", "BDC", EXPORT_LC, 440),
]

# Old seeded products whose names the new list supersedes. Re-pointed at the new
# name where it is the same instrument, so the register's history follows.
RENAMES = {
    "GTE-BID": "14116",
    "GTE-APG": "14123",
    "GTE-PBG": "14117",
    "GTE-PG": "14104",
    "GTE-RET": "14118",
    "GTE-GEN": "14102",
    "GTE-SBLC": "TR-LC-SBLC",
    "ILC-SIGHT": "TR-LC-IMP-SIGHT",
    "ILC-USANCE": "TR-LC-IMP-USANCE",
    "ILC-SIGHT-BILL": "TR-BLC-IMP-SIGHT",
    "ILC-USANCE-BILL": "TR-BLC-IMP-USANCE",
    "ELC-SIGHT": "TR-LC-EXP-SIGHT",
    "ELC-SIGHT-BILL": "TR-BLC-EXP-SIGHT",
}

# ── The tariff, as published ─────────────────────────────────────────────────
# (code, name, category code or None, action or "", product code or None,
#  basis, rate %, fixed amount, minimum, currency, manual note, sort)
#
# Read straight from the bank's tariff book. Where the book gives a percentage
# AND a floor, both are set; where it gives a flat fee, fixed_amount carries it
# and the rate is 0; where it gives neither (a notary's charge), manual_note
# says so and nothing is calculated.
D = Decimal
TARIFFS = [
    # ── Guarantees (Guarantee/SBLC) ─────────────────────────────────────────
    ("TRF-LG-ISSUE", "Issue/Renewal Commission", "LG", "ISSUANCE", None,
     PER_QUARTER, D("0.75"), D("0"), D("2500"), "KES", "", 10),
    # The desk's one stated exception: a bid bond is 1% flat, not 0.75% a quarter.
    ("TRF-LG-ISSUE-BID", "Bid Bond Issue Commission", "LG", "ISSUANCE", "14116",
     FLAT, D("1"), D("0"), D("0"), "KES", "", 5),
    ("TRF-LG-AMEND", "General Amendment", "LG", "AMENDMENT", None,
     PER_INSTANCE, D("0"), D("2000"), D("0"), "KES", "", 20),
    ("TRF-LG-CANCEL", "Cancellation Commission", "LG", "CANCELLATION", None,
     PER_INSTANCE, D("0"), D("500"), D("0"), "KES", "", 30),
    ("TRF-LG-ADVISE", "Advise of Incoming Guarantee", "LG", "ADVISING", None,
     PER_INSTANCE, D("0"), D("2500"), D("0"), "KES", "", 40),
    ("TRF-LG-CLAIM", "Claims Processing Charge", "LG", "SETTLEMENT", None,
     PER_INSTANCE, D("0"), D("3500"), D("0"), "KES", "", 50),

    # ── Letters of Credit ───────────────────────────────────────────────────
    ("TRF-LC-ISSUE", "LC Issuance Charges", "LC", "ISSUANCE", None,
     PER_QUARTER, D("0.75"), D("0"), D("2500"), "KES", "", 110),
    ("TRF-LC-ACCEPT", "LC Acceptance Charges", "LC", "BILL ACCEPTANCE", None,
     PER_QUARTER, D("0.75"), D("0"), D("2500"), "KES", "", 120),
    ("TRF-LC-PAY", "LC Payment Charges", "LC", "SETTLEMENT", None,
     FLAT, D("0.3"), D("0"), D("2500"), "KES", "", 130),
    # The book has two amendment lines: a flat general fee, and a per-quarter
    # charge when the amendment extends the date or raises the amount. The
    # general fee is the default; the extension line is applied by the desk
    # where it applies, which is why both exist as separate, editable lines.
    ("TRF-LC-AMEND", "LC Amendment Charges - General", "LC", "AMENDMENT", None,
     PER_INSTANCE, D("0"), D("2500"), D("0"), "KES", "", 140),
    ("TRF-LC-AMEND-EXT", "LC Amendment Charges - Extension/Amount", "LC", "", None,
     PER_QUARTER, D("0.75"), D("0"), D("2500"), "KES", "", 145),
    ("TRF-LC-INDEMNITY", "Release Against Indemnity Charge", "LC", "", None,
     FLAT, D("0.1"), D("0"), D("2500"), "KES", "", 150),
    ("TRF-LC-DISCREPANCY", "Discrepancy Charges", "LC", "", None,
     PER_INSTANCE, D("0"), D("100"), D("0"), "USD", "", 160),
    ("TRF-LC-ADVISE", "LC Advising Charges", "LC", "ADVISING", None,
     PER_INSTANCE, D("0"), D("2500"), D("0"), "KES",
     "Customers KShs 2,500; non-customers KShs 3,500 — set the amount to 3,500 "
     "for a non-customer.", 170),
    ("TRF-LC-CONFIRM", "LC Confirmation Charges", "LC", "", None,
     PER_QUARTER, D("0.5"), D("0"), D("5000"), "KES", "", 180),

    # ── Bills under letter of credit ────────────────────────────────────────
    ("TRF-BLC-NEGOTIATE", "LC Documents Negotiation/Processing Charges",
     "BLC", "ISSUANCE", None,
     FLAT, D("0.5"), D("0"), D("3000"), "KES", "", 210),
    ("TRF-BLC-ACCEPT", "LC Acceptance Charges", "BLC", "BILL ACCEPTANCE", None,
     PER_QUARTER, D("0.75"), D("0"), D("2500"), "KES", "", 220),
    ("TRF-BLC-DISCOUNT", "LC Documents Discounting Charges", "BLC", "", None,
     PER_QUARTER, D("0.25"), D("0"), D("3000"), "KES", "", 230),
    ("TRF-BLC-PAY", "LC Payment Charges", "BLC", "SETTLEMENT", None,
     FLAT, D("0.3"), D("0"), D("2500"), "KES", "", 240),
    ("TRF-BLC-AMEND", "LC Amendment Charges - General", "BLC", "AMENDMENT", None,
     PER_INSTANCE, D("0"), D("2500"), D("0"), "KES", "", 250),

    # ── Bills under documentary collection ──────────────────────────────────
    # The book calls these Inward and Outward Collections.
    ("TRF-BDC-ADVISE", "Advising Charges", "BDC", "ADVISING", None,
     PER_INSTANCE, D("0"), D("2500"), D("0"), "KES", "", 310),
    ("TRF-BDC-ACCEPT", "Acceptance Charges", "BDC", "BILL ACCEPTANCE", None,
     PER_QUARTER, D("0.3"), D("0"), D("2500"), "KES", "", 320),
    ("TRF-BDC-AVAL", "Availisation Charges", "BDC", "ISSUANCE", None,
     PER_QUARTER, D("0.75"), D("0"), D("2500"), "KES", "", 330),
    ("TRF-BDC-PAY", "Payment Charges", "BDC", "SETTLEMENT", None,
     FLAT, D("0.3"), D("0"), D("2500"), "KES", "", 340),
    ("TRF-BDC-HOLD", "Holding Charges", "BDC", "", None,
     PER_MONTH, D("0"), D("2500"), D("0"), "KES", "", 350),
    ("TRF-BDC-NOTARY", "Noting and Protesting Charges", "BDC", "", None,
     NONE, D("0"), D("0"), D("0"), "KES",
     "As charged by the Notary Public.", 360),
    ("TRF-BDC-HANDLING", "Documents Handling Charges (Outward)", "BDC", "AMENDMENT", None,
     FLAT, D("0.5"), D("0"), D("3000"), "KES", "", 370),
]


def seed(apps, schema_editor):
    Category = apps.get_model("trade_register", "TradeProductCategory")
    Product = apps.get_model("trade_register", "TradeProduct")
    Tariff = apps.get_model("trade_register", "TradeTariff")
    Entry = apps.get_model("trade_register", "TradeRegisterEntry")

    cats = {}
    for code, name, order in CATEGORIES:
        cats[code], _ = Category.objects.update_or_create(
            code=code,
            defaults={"name": name, "sort_order": order, "is_active": True},
        )

    # Re-code the products already carrying transactions, so their history
    # follows them onto the new list instead of being orphaned.
    for old_code, new_code in RENAMES.items():
        Product.objects.filter(code=old_code).exclude(code=new_code).update(code=new_code)

    wanted = set()
    for code, name, cat_code, family, order in PRODUCTS:
        wanted.add(code)
        # Names are unique, so an existing row under this name must be updated
        # rather than duplicated.
        existing = Product.objects.filter(name=name).exclude(code=code).first()
        if existing:
            existing.code = code
            existing.save(update_fields=["code"])
        Product.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": cats[cat_code],
                "ref_family": family,
                "sort_order": order,
                "is_active": True,
            },
        )

    # Anything not on the desk's new list is retired, never deleted: entries
    # point at these products and a register must keep reading.
    Product.objects.exclude(code__in=wanted).update(is_active=False)

    products = {p.code: p for p in Product.objects.all()}
    for (code, name, cat_code, action, product_code, basis, rate, fixed,
         minimum, currency, note, order) in TARIFFS:
        Tariff.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": cats.get(cat_code) if cat_code else None,
                "action": action,
                "product": products.get(product_code) if product_code else None,
                "commission_basis": basis,
                "commission_rate": rate,
                "fixed_amount": fixed,
                "minimum_commission": minimum,
                "charge_currency": currency,
                "manual_note": note,
                "sort_order": order,
                "is_active": True,
            },
        )

    # The three placeholder lines seeded before the tariff was available priced
    # nothing; the real book replaces them.
    Tariff.objects.filter(code__in=["TRF-GTE", "TRF-ILC", "TRF-ELC"]).update(is_active=False)

    # Every transaction that predates the action list was an issuance — that is
    # what "not an amendment" meant. Any other historical value is left exactly
    # as recorded; the register says what happened, and rewriting a settled
    # transaction to fit a new dropdown would falsify it.
    Entry.objects.filter(action="").update(action="ISSUANCE")


def unseed(apps, schema_editor):
    Category = apps.get_model("trade_register", "TradeProductCategory")
    Tariff = apps.get_model("trade_register", "TradeTariff")
    Tariff.objects.filter(code__in=[t[0] for t in TARIFFS]).delete()
    Category.objects.filter(code__in=[c[0] for c in CATEGORIES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("trade_register", "0008_product_categories_actions_and_tariff_lines"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
