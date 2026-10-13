"""Loan loss: what the card scores, and how it ties to Finance's workbook.

Nothing here changes how the card is scored. This module exists because the
Loan Loss line is 5–10% of every RM card and the question "where does that
number come from" deserves an answer that can be checked rather than asserted.

The workbook
────────────
Finance maintain ``3. FS_MOM_IFRS_MOVEMENT_Branch & TREND (with Special
Assets).xlsb``: one sheet per month, 36 columns, a row per loan account. The
worked example adds four sheets that turn those months into a per-RM figure,
and the whole chain is three steps:

1. **On a monthly sheet, ``NET`` = ``P&L_Charge`` − ``Int. Adj``.** Exactly -
   checked on every row of the example: 7,180,415.670671493 −
   213,299.13991357503 = 6,967,116.530757918.
2. **``CUSTOMER SUMMARY_2026`` pivots that by customer and month**, as
   ``<Mon> P&L Charge``, ``<Mon> Int. Adj`` and ``<Mon> Loan Loss``, and the
   third is again the first minus the second - 12,058 customers times eight
   months with **no exceptions** - then totals them into ``YTD Loan Loss``.
3. **``rm_summary`` pivots THAT by ``rm_code``** into "Sum of YTD Loan Loss",
   which is the figure a card carries.

So the measure is ``SUM(P&L charge) - SUM(interest adjustment)`` over the
customers a person manages, for the year to date. Which is, to the character,
what this platform has always computed::

    -SUM(COALESCE(pl_charge, 0) - COALESCE(int_adj, 0))
    FROM loans_mom_ifrs_movement

in ``services.portfolio_service`` - negated there because that query returns
income categories, where a provision charge is a negative contribution, and
negated back for the card. **The scorecard needed no change for this line.**

Where the two will disagree, and why that is not a fault
───────────────────────────────────────────────────────
The difference is not the arithmetic, it is **who the customer belongs to**.

The workbook carries an ``rm_code`` per customer, filled by a lookup. In the
example, of 361,605,835.99 for the year:

* **300,924,353.02** sits on a label that is a sales code,
* **18,513,091.47** on a bare number (a code written without its letters),
* **19,929,220.94** on the literal text ``Unmanaged`` - chiefly SPECIAL
  ASSETS, which is nobody's book and must not be put on anybody's card,
* **27,477,075.10** on ``#N/A`` and **−5,237,904.52** on ``#VALUE!`` - rows
  where the lookup itself failed.

That is **42,168,391.51, 11.7% of the group's loan loss, attributable to
nobody** in the workbook. This platform maps a customer to an RM through
``retail_allocated_portfolio`` instead, which is the allocation the business
maintains, so it will attribute some of what the workbook leaves on ``#N/A``
and will never attribute the Special Assets book to an RM.

:func:`reconcile` is how to see that difference per RM rather than argue about
it, and ``manage.py check_loan_loss`` is its command line.
"""

from __future__ import annotations

import re

#: The months the workbook names its columns after.
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
          "Oct", "Nov", "Dec")

#: Labels in ``rm_summary`` that are not an RM.
#:
#: ``Unmanaged`` is the workbook's own word for a customer with no RM, and the
#: bulk of it is SPECIAL ASSETS - 7.7m on one customer in January alone. The
#: two error strings are a failed lookup. None of the three may be charged to
#: a person, and each is reported on its own rather than lumped into "other":
#: a failed lookup is somebody's job to fix, and an unmanaged book is not.
NOT_AN_RM = ("unmanaged", "#n/a", "#value!", "#ref!", "grand total", "")


def monthly_loss(pl_charge, int_adj):
    """One month's loan loss for one account or customer.

    ``P&L_Charge`` − ``Int. Adj``, which is the workbook's ``NET`` column and
    its ``<Mon> Loan Loss`` column. A blank is a nought: the workbook leaves
    the cell empty where there was no adjustment, and treating that as missing
    would drop the charge with it.
    """
    return float(pl_charge or 0) - float(int_adj or 0)


def is_an_rm(label):
    """Is this ``rm_code`` a person, or one of the workbook's own markers?"""
    text = str(label or "").strip()
    if text.lower() in NOT_AN_RM:
        return False
    # pyxlsb renders an Excel error cell as the number 42, so a label that is
    # not a code or a number at all is treated as a marker rather than guessed
    # at. An RM code is letters then digits, or digits alone.
    return bool(re.fullmatch(r"[A-Za-z]{0,6}\d{2,8}", text))


def read_rm_summary(path):
    """The example workbook's ``rm_summary`` pivot → what it says, as data.

    Returns ``(by_rm, markers, grand_total)``: the labels that are an RM code
    folded to upper case, the ones that are not kept separately with their
    amounts, and the sheet's own Grand Total so the read can be checked
    against it rather than trusted.
    """
    from pyxlsb import open_workbook

    by_rm, markers, grand = {}, {}, None
    with open_workbook(str(path)) as book:
        if "rm_summary" not in book.sheets:
            raise ValueError(
                "That workbook has no rm_summary sheet. The per-RM pivot is "
                "in the worked example, not in the monthly file Finance "
                "circulate - the one with 13 sheets rather than 10.")
        with book.get_sheet("rm_summary") as sheet:
            rows = [[cell.v for cell in row] for row in sheet.rows()]

    started = False
    for row in rows:
        if not row or row[0] is None:
            continue
        label = str(row[0]).strip()
        if not started:
            # The pivot does not start at A1 - there are blank rows above it.
            started = label.lower() in ("row labels", "rm_code", "rm code")
            continue
        value = row[1] if len(row) > 1 else None
        if value is None:
            continue
        value = float(value)
        if label.lower() == "grand total":
            grand = value
        elif is_an_rm(label):
            code = label.upper()
            by_rm[code] = by_rm.get(code, 0.0) + value
        else:
            markers[label] = markers.get(label, 0.0) + value
    if grand is None and not by_rm:
        raise ValueError(
            "rm_summary was read but held no 'Row Labels' pivot. Refresh the "
            "pivot in Excel and save again.")
    return by_rm, markers, grand


def platform_by_rm(codes):
    """This platform's YTD loan loss for each sales code → ``{code: amount}``.

    The same statement the card scores, run once per code. Signed as the
    workbook signs it: a positive number is a provision CHARGED.
    """
    from services import portfolio_service as svc

    out = {}
    for code in codes:
        rows = svc.rm_revenue(code)
        found = None
        for row in rows:
            if (row.get("income_category") or "").strip().lower() == "loan_loss":
                found = float(row.get("value") or 0)
        # rm_revenue negates it (a charge is a negative contribution to
        # income), so negating back gives the workbook's own sign.
        out[code.upper()] = None if found is None else -found
    return out


def reconcile(path, only=()):
    """Compare this platform against the workbook, RM by RM.

    ``only`` limits it to a few sales codes, which is what to do on a first
    run - the full compare is one query per RM across 90-odd RMs.

    Returns a dict with ``rows`` (one per RM, with both figures and the
    difference), ``markers`` (what the workbook could not attribute), and the
    totals, so a reader can see both that the lines agree and how much of the
    group's figure never reaches a line at all.
    """
    by_rm, markers, grand = read_rm_summary(path)

    wanted = {code.strip().upper() for code in only if str(code).strip()}
    if wanted:
        by_rm = {code: value for code, value in by_rm.items()
                 if code in wanted}
        # A code asked for that the workbook has no row for is still worth
        # showing: nil in the workbook against a figure here is exactly the
        # kind of difference this is for.
        for code in wanted - set(by_rm):
            by_rm[code] = 0.0

    mine = platform_by_rm(sorted(by_rm))

    rows = []
    for code in sorted(by_rm):
        theirs = by_rm[code]
        ours = mine.get(code)
        rows.append({
            "sales_code": code,
            "workbook": theirs,
            "platform": ours,
            "difference": None if ours is None else ours - theirs,
            # A proportion is what tells a 3-shilling rounding difference from
            # a customer sitting in the wrong book.
            "difference_pct": (
                None if ours is None or not theirs
                else (ours - theirs) / abs(theirs)),
        })

    attributed = sum(value for value in by_rm.values())
    return {
        "rows": rows,
        "markers": sorted(markers.items(), key=lambda item: -abs(item[1])),
        "workbook_grand_total": grand,
        "workbook_attributed": attributed,
        # Both of these are reported, because they are the same number by two
        # routes: what the Grand Total has left over after the RM labels, and
        # what the markers themselves carry. They differing means the read is
        # wrong, not that the workbook is.
        "workbook_unattributed": (
            None if grand is None else grand - attributed),
        "marker_total": sum(markers.values()),
        "rm_count": len(by_rm),
    }
