"""Hand the delinquent customers nobody is calling to the officers who can.

    manage.py allocate_collections --dry-run
    manage.py allocate_collections
    manage.py allocate_collections --officers AN3773,CO1004 --limit 200

Core banking leaves ``delay_officer`` blank on plenty of delinquent loans.
Those customers are on no officer's screen, so nobody calls them and they age
quietly into the next bucket.

This never writes to ``loans``: that table is rewritten from core banking
every night, so a write there is gone by morning. Allocations are held in
``hf_collections_allocation``, and an officer's book is the union of the two.
A customer core banking HAS assigned is never moved.

ASCII only in the output - a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Allocate unassigned delinquent customers to collections officers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--officers", default="",
            help="Comma-separated officer codes. Defaults to every officer "
                 "who already holds delinquent loans.")
        parser.add_argument("--limit", type=int, default=None,
                            help="Allocate at most this many customers.")
        parser.add_argument("--branch", default="",
                            help="Only customers at this branch code.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would happen, write nothing.")
        parser.add_argument("--show", type=int, default=12)

    def handle(self, **options):
        from apps.hf_collections import allocation
        from apps.hf_collections import officer as officer_module

        write = self.stdout.write

        codes = [c.strip() for c in options["officers"].split(",") if c.strip()]
        if not codes:
            codes = [row["collection_officer_code"]
                     for row in officer_module.leaderboard()]
            write(f"  officers          {len(codes)} taken from who already "
                  f"holds delinquent loans")
        else:
            write(f"  officers          {len(codes)} named")

        if not codes:
            write(self.style.WARNING(
                "  Nobody holds a delinquent loan, so there is no team to "
                "allocate to. Name officers with --officers."))
            return

        assignments, report = allocation.plan(
            codes, limit=options["limit"],
            branch=options["branch"] or None)

        write(f"  on nobody's book  {report['unallocated']}")
        write(f"  would assign      {report['assigned']}")
        write("")
        for code, row in sorted(report["per_officer"].items()):
            if not row["getting"]:
                continue
            write(f"      {code:14} carrying {row['already_carrying']:5}  "
                  f"+{row['getting']}")

        if options["show"] and assignments:
            write("")
            for item in assignments[:options["show"]]:
                write(f"      {item['cust_id']:>10}  "
                      f"{(item['customer_name'] or '')[:26]:28} "
                      f"{item['arrears']:>14,.2f}  -> "
                      f"{item['collection_officer_code']}")
            if len(assignments) > options["show"]:
                write(f"      and {len(assignments) - options['show']} more")

        for skipped in report["skipped"]:
            write(self.style.WARNING(f"  {skipped}"))

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("  --dry-run: nothing was written."))
            return

        if not assignments:
            write("")
            write("  Nothing to do - every delinquent customer already has "
                  "an officer.")
            return

        written = allocation.save(assignments, who="allocate_collections")
        write("")
        write(self.style.SUCCESS(f"  Allocated {written} customer(s)."))
        write("  They show on the officers' own screens straight away.")
        write("")
