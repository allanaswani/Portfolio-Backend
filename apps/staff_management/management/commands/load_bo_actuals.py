"""Load the back-office actuals template.

    manage.py load_bo_actuals "2026_BO_Actual_Template.xlsx" --dry-run
    manage.py load_bo_actuals <file>

Unlike the sales workbook, which holds one card per role sheet, this one holds
every back-office person on every measure: 37 sheets, a row per member of
staff, a column per month. One load fills every back-office card.

The year-to-date figure is the LATEST month, for every sheet, because the
counting measures in this template are already running totals - summing them
would count the year twice. See ``apps.staff_management.bo_actuals``.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load the back-office actuals template (.xlsx)."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be written, and write nothing.")
        parser.add_argument("--show", type=int, default=10)

    def handle(self, **options):
        import pathlib

        from apps.staff_management import bo_actuals

        write = self.stdout.write
        path = pathlib.Path(options["file"])
        if not path.exists():
            raise CommandError(f"{path} is not there.")

        try:
            rows, report = bo_actuals.read_workbook(str(path))
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            raise CommandError(
                f"That template could not be read: {exc}") from exc
        if not rows:
            raise CommandError(
                "Nothing was read. The template needs its measure sheets, "
                "each with StaffSalesCode and a column per month.")

        write("")
        write(f"  sheets read       {len(report['sheets_read'])}")
        write(f"  people            {report['people']}")
        write(f"  figures           {report['figures']:,}")
        write(f"  reporting month   {report['reporting_month']} "
              f"(every row is capped to it)")
        if report["not_cumulative"]:
            write(self.style.WARNING(
                f"  {len(report['not_cumulative'])} sheet(s) no longer look "
                f"like a running total: "
                f"{', '.join(report['not_cumulative'])}. Nothing was summed "
                f"on the strength of it - worth a look."))

        entries, planned = bo_actuals.plan(rows)
        write("")
        write(f"  to write          {planned['written']:,} figure(s) for "
              f"{planned['people']} people")
        write(f"  left measured     {planned['measured_here']:,} line(s) the "
              f"platform computes itself")
        write(f"  not on their card {planned['not_on_their_card']:,} "
              f"(a teller and a BOM share a template)")

        if planned["no_person"]:
            write(self.style.WARNING(
                f"  {len(planned['no_person'])} person(s) reach no card:"))
            for item in planned["no_person"][:10]:
                write(f"      {item['sales_code']:12} "
                      f"{item['staff_name'][:26]:28} {item['why']}")
            if len(planned["no_person"]) > 10:
                write(f"      and {len(planned['no_person']) - 10} more")

        if options["show"] and entries:
            write("")
            for entry in entries[:options["show"]]:
                write(f"      {entry['sales_code']:12} "
                      f"{entry['kpi_code'][:42]:44} {entry['value']:>14,.4f}")
            if len(entries) > options["show"]:
                write(f"      and {len(entries) - options['show']} more")

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("  --dry-run: nothing was written."))
            return

        written = bo_actuals.save(entries, who="load_bo_actuals")
        write("")
        write(self.style.SUCCESS(f"  Saved {written:,} figure(s)."))
        write("  They show on the cards straight away - a card is computed "
              "when it is opened.")
        write("")
