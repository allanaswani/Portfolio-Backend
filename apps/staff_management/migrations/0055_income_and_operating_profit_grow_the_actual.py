"""Operating Profit and Income Contribution grow column 18, not column 17.

Migration 0051 moved ``income_contribution_portfolio_ntb`` onto the
allocation sheet's ``2024 (Income+(FTP-LoanLoss))`` column and said plainly
that the other two were left alone because nothing had been seen either way:

    Only ``income_contribution_portfolio_ntb`` is moved back. The other
    three stay on ``2024.0`` because Juspher's card is direct evidence for
    ``direct_portfolio_contribution``, and nothing has been seen either way
    for ``income_contribution`` or ``operating_profit`` - guessing would
    swap one unverified column for another.

Something has now been seen. The workbook's own role sheets were read and
matched against the allocation row of the person each one is made out to.

``TOTAL INCOME CONTRIBUTION`` spans four columns:

    17  2024.0                          last year's TARGET
    18  2024 (Income+(FTP-LoanLoss))    last year's ACTUAL
    19  Growth                          20% of column 18, on every row
    20  2025.0                          18 + 19, the year's target

and the loader turns a base plus that Growth into the year's target by
reading the rate off column 18 (``GROWTH_RATE_OVER``), so the base column
alone decides the answer: base x 1.2.

**Operating Profit - exact, on two people across two role sheets:**

    Business_Banking  Charles Muchiri   card 2026 FY   6,245,102.21
                      col 18 x 1.2                     6,245,102.21   match
                      col 17 x 1.2                     5,161,505.92   no

    Diaspora          Edward Kosgei     card 2026 FY  15,032,536.72
                      col 18 x 1.2                    15,032,536.72   match
                      col 17 x 1.2                     4,836,000.54   no

**Income Contribution - by sign and magnitude, on Personal_Banking:**

    Vincent Ogare     card 2026 FY  -146,594,390.60
                      col 17            15,394,657.91   wrong sign
                      col 18          -169,147,373.77   right family
                      col 18 x 0.8   -135,317,899.02    the sheet's own col 20

Column 17 is POSITIVE where his card is negative and two orders of magnitude
away, so it cannot be the base whatever the exact arithmetic. The loader
lands on -135,317,899.02, which is the allocation sheet's own column 20. His
printed card says -146,594,390.60; the Personal_Banking sheet scales its own
line and the allocation sheet does not, and the allocation sheet is the
authoritative one. That difference is recorded here rather than chased.

``direct_portfolio_contribution`` is NOT moved, and this is the evidence it
stays:

    Commercial        Juspher Muriithi  card 2026 FY 277,856,513.63
                      col 17 x 1.2                   277,856,513.63   match
                      col 18 x 1.2                   105,988,819.15   no

Three of the four income codes grow last year's ACTUAL; Direct Portfolio
Contribution grows last year's TARGET, and now each one is on the column its
own card proves.

**The targets do not change until the allocation sheet is loaded again.**
A target is worked out when the file is read and stored on
``ScEmployeeKpiTarget``; this migration changes where the reader looks, not
the rows it has already written.
"""

from django.db import migrations

GROUP = "TOTAL INCOME CONTRIBUTION"
LAST_YEARS_TARGET = f"{GROUP}/2024.0"
LAST_YEARS_ACTUAL = f"{GROUP}/2024 (Income+(FTP-LoanLoss))"

#: Proven above, each against the card of the person the role sheet is made
#: out to. ``direct_portfolio_contribution`` is deliberately absent.
CODES = ("operating_profit", "income_contribution")


def grow_last_years_actual(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")

    moved = []
    for row in Kpi.objects.filter(kpi_code__in=CODES):
        if (row.allocation_base_column or "").strip() != LAST_YEARS_TARGET:
            continue
        row.allocation_base_column = LAST_YEARS_ACTUAL
        row.save(update_fields=["allocation_base_column"])
        moved.append(row.kpi_code)

    if moved:
        print(f"  Income base: {len(moved)} line(s) now grow last year's "
              f"ACTUAL - {', '.join(sorted(moved))}. Charles Muchiri's card "
              f"says 6,245,102.21 and that column times 1.2 is "
              f"6,245,102.21. Load the allocation sheet again for the "
              f"stored targets to change.")
    else:
        print("  Income base: nothing to move; already on last year's "
              "actual, or the seed has changed.")


def grow_last_years_target(apps, schema_editor):
    Kpi = apps.get_model("staff_management", "ScKpi")
    Kpi.objects.filter(kpi_code__in=CODES,
                       allocation_base_column=LAST_YEARS_ACTUAL).update(
        allocation_base_column=LAST_YEARS_TARGET)
    print("  Income base: pointed back at last year's target.")


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0054_pb_has_no_loan_loss_line"),
    ]

    operations = [
        migrations.RunPython(grow_last_years_actual, grow_last_years_target),
    ]
