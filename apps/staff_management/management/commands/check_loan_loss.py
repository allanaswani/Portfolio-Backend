"""Compare the Loan Loss line against Finance's own workbook.

    manage.py check_loan_loss "3. FS_MOM_IFRS_MOVEMENT ... (1).xlsb"
    manage.py check_loan_loss <workbook> --sales-code AKL3116,LJB1656

Needs the worked example - the 13-sheet file with ``rm_summary`` in it, not the
10-sheet monthly file. Run it on the host, where the warehouse is.

This changes nothing. The card's Loan Loss line has always been
``SUM(P&L charge) - SUM(interest adjustment)`` over the customers an RM
manages, which is the workbook's arithmetic exactly; what this answers is the
other half of the question - whether the same customers are in the same book.
``apps.staff_management.loan_loss`` has the detail.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Reconcile the Loan Loss line against the IFRS movement workbook."

    def add_arguments(self, parser):
        parser.add_argument("workbook", help="The worked example .xlsb.")
        parser.add_argument(
            "--sales-code", default="",
            help="Only these codes, comma separated. Start here: the full "
                 "compare is one query per RM.")
        parser.add_argument(
            "--tolerance", type=float, default=0.01,
            help="Proportion of the workbook figure to treat as agreement. "
                 "Default 0.01 - 1%%.")

    def handle(self, **options):
        from apps.staff_management import loan_loss

        write = self.stdout.write
        only = [part.strip() for part in options["sales_code"].split(",")
                if part.strip()]

        try:
            result = loan_loss.reconcile(options["workbook"], only=only)
        except FileNotFoundError as exc:
            raise CommandError(
                f"{options['workbook']} is not there.") from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        write("")
        write(f"  {result['rm_count']} RM(s) in the workbook's rm_summary")
        if result["workbook_grand_total"] is not None:
            write(f"  workbook Grand Total   "
                  f"{result['workbook_grand_total']:>18,.2f}")
        write(f"  on an RM label         "
              f"{result['workbook_attributed']:>18,.2f}")

        # What the workbook itself cannot put on anybody. Said first, because
        # it is the larger finding: a difference on one RM is a mapping to
        # chase, and a tenth of the group's loan loss attributable to nobody
        # is a conversation with Finance.
        if result["markers"]:
            write("")
            write(self.style.WARNING(
                f"  attributable to nobody in the workbook "
                f"{result['marker_total']:,.2f}:"))
            for label, amount in result["markers"]:
                reason = {
                    "unmanaged": "no RM on the customer - chiefly Special "
                                 "Assets, which is nobody's card",
                }.get(label.strip().lower(),
                      "the workbook's own RM lookup failed on these rows")
                write(f"      {label:<14} {amount:>18,.2f}   {reason}")
            if result["workbook_unattributed"] is not None:
                gap = result["workbook_unattributed"] - result["marker_total"]
                if abs(gap) > 1:
                    write(self.style.ERROR(
                        f"      the Grand Total leaves {gap:,.2f} that is "
                        f"neither on an RM nor on a marker - this read is "
                        f"wrong, not the workbook"))

        write("")
        write(f"  {'sales code':<12} {'workbook':>18} {'platform':>18} "
              f"{'difference':>18}   ")
        agree = differ = unreadable = 0
        for row in result["rows"]:
            ours = row["platform"]
            if ours is None:
                unreadable += 1
                write(f"  {row['sales_code']:<12} {row['workbook']:>18,.2f} "
                      f"{'-':>18} {'-':>18}   nothing read here")
                continue
            close = (row["difference_pct"] is not None
                     and abs(row["difference_pct"]) <= options["tolerance"])
            if close or (not row["workbook"] and not ours):
                agree += 1
                continue
            differ += 1
            pct = ("" if row["difference_pct"] is None
                   else f"  {row['difference_pct'] * 100:+.1f}%")
            write(f"  {row['sales_code']:<12} {row['workbook']:>18,.2f} "
                  f"{ours:>18,.2f} {row['difference']:>18,.2f}{pct}")

        write("")
        write(f"  {agree} agree within {options['tolerance'] * 100:g}%, "
              f"{differ} differ, {unreadable} could not be read")
        if differ:
            write("")
            write("  A difference here is WHOSE CUSTOMER a loan is, not the "
                  "arithmetic - both sides compute P&L charge less interest "
                  "adjustment. This platform maps a customer to an RM through "
                  "retail_allocated_portfolio; the workbook uses its own "
                  "lookup, which fails on the rows above.")
        write("")
