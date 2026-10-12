"""Load the SAP cost extract, from the lake or from a file.

    manage.py load_sap_costs                      # from Trino
    manage.py load_sap_costs --file extract.xlsx  # from a file
    manage.py load_sap_costs --dry-run            # read and report only

This is the job that should run on a schedule. Until it has run, the cost
screens have nothing to show and say so rather than falling back to a figure
somebody typed in once.

A load REPLACES its snapshot. Each SAP extract is a full copy for its date, not
an increment, which is why the Finance query ends with ``WHERE d.dt = m.max_dt``
and why appending would double every posting the next time the same extract
arrived.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load the SAP cost extract into sap_cost_posting."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", default="",
            help="An .xlsx extract. Without it, the lake is queried.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Read and report what would be written, and write nothing.")

    def handle(self, **options):
        from apps.staff_management import cost_analysis, cost_ingest

        write = self.stdout.write

        if options["file"]:
            write(f"Reading {options['file']}…")
            try:
                with open(options["file"], "rb") as handle:
                    rows = cost_ingest.read_workbook(handle)
            except FileNotFoundError as exc:
                raise CommandError(f"{options['file']} is not there.") from exc
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        else:
            write("Querying delta.gold_db.sap_cost_data…")
            try:
                rows = cost_ingest.fetch_from_trino()
            except RuntimeError as exc:
                raise CommandError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - the reason matters more
                raise CommandError(
                    f"The lake could not be queried: {exc}\n"
                    f"Load the extract with --file instead, or through the "
                    f"Administration screen.") from exc

        if not rows:
            raise CommandError(
                "That extract is empty. Nothing has been changed - an empty "
                "load must not wipe the snapshot that is there.")

        postings, report = cost_ingest.rows_to_postings(
            rows, loaded_by="load_sap_costs")

        write("")
        write(f"  read              {report['read']:,}")
        write(f"  kept              {report['kept']:,}")
        if report["skipped_no_gl"]:
            write(self.style.WARNING(
                f"  no GL account     {report['skipped_no_gl']:,} skipped"))
        if report["skipped_no_amount"]:
            write(self.style.WARNING(
                f"  no amount         {report['skipped_no_amount']:,} skipped"))
        if report["without_a_date"]:
            # Kept, not dropped: it is money that exists, and it shows up in
            # the health view rather than vanishing.
            write(self.style.WARNING(
                f"  no usable date    {report['without_a_date']:,} kept, but "
                f"they cannot be put in a month"))
        write(f"  extract date(s)   {', '.join(report['snapshot_dates']) or '-'}")

        if not report["kept"]:
            raise CommandError("Nothing in that extract could be read.")

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("--dry-run: nothing was written."))
            return

        result = cost_ingest.save_postings(postings, report)
        write("")
        if not result["written"]:
            raise CommandError(result["detail"])
        write(self.style.SUCCESS("  " + result["detail"]))

        # What the load cannot place is worth saying out loud at load time
        # rather than leaving somebody to notice a department total is light.
        health = cost_analysis.health()
        write("")
        write(f"  reportable        {health['reportable_postings']:,} posting(s), "
              f"{health['reportable_amount']:,.0f}")
        for label, key, naming in (
            ("cost centres not in the mapping", "unmapped_cost_centres",
             "cost_centre"),
            ("7-series GLs not in the mapping", "unmapped_gls", "gl"),
        ):
            missing = health[key]
            if not missing:
                continue
            total = sum(item["amount"] for item in missing)
            write(self.style.WARNING(
                f"  {len(missing)} {label}, carrying {total:,.0f} that is NOT "
                f"in any department total:"))
            for item in missing[:10]:
                write(f"      {item[naming]}  {item['postings']:,} posting(s)  "
                      f"{item['amount']:,.0f}")
            if len(missing) > 10:
                write(f"      …and {len(missing) - 10} more")
        write("")
