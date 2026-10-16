"""Settle the promises to pay against the repayments feed.

    manage.py settle_ptp                # build from the diary, then settle
    manage.py settle_ptp --no-feedback  # settle only what is already there
    manage.py settle_ptp --dry-run

For the nightly run, after the repayments feed lands. Idempotent: a kept
promise is never revisited, because money that arrived cannot un-arrive, and
building promises out of the diary upserts on (loan, date, officer) so
re-running does not stack duplicates.

ASCII only in the output - a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the whole command down with it.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Settle Promises To Pay against loan_repayments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-feedback", action="store_true",
            help="Do not build promises out of the collections diary.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change, and change nothing.")
        parser.add_argument("--officer", default="",
                            help="Limit to one collection officer code.")

    def handle(self, **options):
        from apps.hf_collections import ptp
        from apps.hf_collections.models import PromiseToPay

        write = self.stdout.write

        rows = PromiseToPay.objects.all()
        if options["officer"]:
            rows = rows.filter(
                collection_officer_code__iexact=options["officer"])

        if options["dry_run"]:
            # Settle in memory and report, writing nothing.
            undecided = rows.exclude(status=PromiseToPay.STATUS_KEPT)
            would = 0
            for promise in undecided:
                was = promise.status
                ptp.settle(promise)
                if promise.status != was:
                    would += 1
                    write(f"      {promise.loan_account_no} "
                          f"{promise.customer_name[:24]:26} "
                          f"{was:9} -> {promise.status}")
            write("")
            write(self.style.WARNING(
                f"  --dry-run: {would} promise(s) would change status. "
                f"Nothing was written."))
            return

        made = read = 0
        if not options["no_feedback"]:
            made, read = ptp.from_feedback()
            write(f"  from the diary    {made} new promise(s) out of {read} "
                  f"entr(ies) carrying a PTP amount and a date")

        moved = ptp.settle_all(
            rows.exclude(status=PromiseToPay.STATUS_KEPT))
        write(f"  settled           {moved} promise(s) changed status")

        summary = ptp.kept_rate(rows)
        write("")
        write(f"  kept              {summary['kept']}")
        write(f"  partly kept       {summary['part_kept']}")
        write(f"  broken            {summary['broken']}")
        write(f"  not yet due       {summary['open']} (not counted in the "
              f"rate)")
        if summary["kept_rate"] is None:
            write(self.style.WARNING(
                "  kept rate         no promise has come due yet"))
        else:
            write(f"  kept rate         {summary['kept_rate'] * 100:.1f}% of "
                  f"{summary['decided']} decided")
            write(f"  kept or partly    "
                  f"{summary['kept_or_part_rate'] * 100:.1f}%")
        write(f"  promised          {summary['promised_value']:,.2f}")
        write(f"  paid              {summary['paid_value']:,.2f}")
        write(f"  grace             {summary['grace_days']} days after the "
              f"promised date still counts")
        write("")
