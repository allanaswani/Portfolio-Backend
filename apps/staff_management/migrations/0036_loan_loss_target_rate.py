"""The Loan Loss line gets a target, from the person's own prior year.

Until now this line had none. The card said:

    branch_employee_dmc_data has no target_loan_provisions column, your
    role's card carries no target for this line either, and nobody has
    allocated you one. It is a column for the DMC load to add.

which was true and also the wrong conclusion. **The target was never meant to
be a DMC column.** Reading the four cards that carry the line with numbers on
it shows the desk derives it, and derives it the same way every time:

=================  ===============  ==============  ===============  ======
card               prior year       growth          this year        rate
=================  ===============  ==============  ===============  ======
Commercial          -9,245,965.64   +1,849,193.13   -7,396,772.51     80%
Commercial_trade   -20,053,060.49   +4,010,612.10  -16,042,448.39     80%
Ultimate_RM         -4,537,193.86   +3,024,795.91   -1,512,397.95   33.3%
Personal_Banking    -5,031,576.71     -670,876.89   -5,702,453.60   113.3%
=================  ===============  ==============  ===============  ======

``prior year + growth = this year`` on all four, to the cent. So the year's
target is **the person's own prior-year provision times a rate the role sets**:
Commercial and Commercial-Trade are told to cut provisions by a fifth, Ultimate
by two thirds, and Personal Banking is allowed 13.3% more.

That is exactly the shape Asset Growth already uses - ``target_basis =
"rate_on_base"`` with the rate in ``kpi_target`` - so this migration seeds the
same thing against a new base, ``last_year_loan_loss``, which
``services.portfolio_service.rm_loan_loss`` reads from
``loans_mom_ifrs_movement`` for the year before.

Two things deliberately NOT done
--------------------------------

**The branch table's column is not used.** ``target_loan_provisions`` does
exist - on ``branch_final_employee_dmc_data``, which is one row per BRANCH.
Handing an RM the whole branch's provision allowance would be a target an
order of magnitude too loose, and this line is scored smaller-is-better, so
the error flatters: it would show as full marks. The branch row is still read
whole for somebody who has no per-person row at all (a BBM), where it is
genuinely their own target.

**No rate is invented for a role whose card does not state one.** Business
Banking, Diaspora and Mortgage Business carry no numbered Loan Loss line
among the eight calibration cards, so they get nothing here and keep saying
so. A rate guessed from a neighbouring role is somebody's bonus.

The Ultimate card's own YTD slice is 0.2 of the year where its other lines
are at 8/12; that is a hand-entered figure on one card and is not reproduced -
the platform pro-rates every line to the date its own actual is as at.
"""

from django.db import migrations

#: ``(role_code, kpi_code) -> rate on the person's own prior-year provision``.
#: Read off the cards named in this module's docstring, not chosen.
RATES = {
    "commercial_rm": 0.80,
    "commercial_rm_trade": 0.80,
    "ultimate_rm": 1.0 / 3.0,
    "pb_rm": 1.0 + (0.670876894266751 / 5.031576707000633),
}

#: Every spelling of the line across the cards. The codes are slugs of each
#: card's own wording, so one measure has several.
LOAN_LOSS_CODES = (
    "loan_loss",
    "reduce_p_l_provisions_nil_provisions_loan_loss",
    "reduce_p_l_provisions_nill_provisions_loan_loss",
)

BASE = "last_year_loan_loss"


def seed(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    touched = []
    for role_code, rate in RATES.items():
        rows = Mapping.objects.filter(role_code=role_code,
                                      kpi_code__in=LOAN_LOSS_CODES)
        for row in rows:
            row.kpi_target = rate
            row.target_basis = "rate_on_base"
            row.target_base = BASE
            row.save(update_fields=["kpi_target", "target_basis",
                                    "target_base"])
            touched.append(f"{role_code}/{row.kpi_code} at {rate * 100:.1f}%")

    if touched:
        print(f"\n  Loan Loss targets: {len(touched)} mapping(s) now a rate on "
              f"the person's own prior-year provision - "
              f"{', '.join(touched)}.")
    else:
        print("\n  Loan Loss targets: no mapping matched, nothing changed.")


def unseed(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")
    Mapping.objects.filter(kpi_code__in=LOAN_LOSS_CODES,
                           target_base=BASE).update(
        kpi_target=None, target_basis="", target_base="")


class Migration(migrations.Migration):

    dependencies = [("staff_management", "0035_cx_metrics")]

    operations = [migrations.RunPython(seed, unseed)]
