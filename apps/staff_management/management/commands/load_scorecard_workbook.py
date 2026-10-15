"""Load the desk's scorecard workbook.

    manage.py load_scorecard_workbook "Portfolio Management - Q3 2026_scorecards.xlsb" --dry-run
    manage.py load_scorecard_workbook <file>

The workbook is where the scorecards were worked out before this platform
computed them, and it is still the authority for the lines nothing here can
measure - banking covenant tracking, account planning, leave, weighted sales.
Those come across; everything the platform measures for itself is counted and
deliberately left alone, because taking a deposit figure out of a spreadsheet
when the balance tables hold it would undo the thing that makes the card worth
trusting.

Nothing is written without ``--dry-run`` being left off, and the dry run
prints exactly what would change.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load figures from the desk's scorecard workbook (.xlsb)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="The scorecard .xlsb.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be written, and write nothing.")
        parser.add_argument(
            "--show", type=int, default=12,
            help="How many individual figures to print. Default 12.")

    def handle(self, **options):
        import pathlib

        from apps.staff_management import scorecard_workbook as workbook

        write = self.stdout.write
        path = pathlib.Path(options["file"])
        if not path.exists():
            raise CommandError(f"{path} is not there.")

        try:
            cards, report = workbook.read_workbook(str(path))
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            raise CommandError(
                f"That workbook could not be read: {exc}") from exc

        write("")
        write(f"  sheets read     {', '.join(report['sheets_read']) or '-'}")
        for skipped in report["sheets_skipped"]:
            write(f"  skipped         {skipped['sheet']} - {skipped['why']}")
        write(f"  cards           {len(cards)}")
        write(f"  KPI lines       {report['lines']}")
        write(f"  roster rows     {report['roster_rows']} "
              f"(the workbook's own List sheet)")

        if not cards:
            raise CommandError(
                "No cards were read. The workbook needs its role sheets with "
                "a staff name in row 2 and a feed key in column M.")

        entries, planned = workbook.plan(cards)

        write("")
        write(f"  {'card':24} {'person':24} {'code':10} "
              f"{'role':20} act tgt unmapped")
        for card in planned["cards"]:
            flag = "" if card["matched"] else "   <- reaches nobody"
            write(f"  {card['sheet']:24} {card['staff_name'][:22]:24} "
                  f"{card['sales_code']:10} {card['role_code']:20} "
                  f"{card['actuals']:3} {card['targets']:3} "
                  f"{card['unmapped']:8}{flag}")

        write("")
        write(f"  to write        {planned['actuals']} actual(s), "
              f"{planned['targets']} target(s)")
        # Not a shortfall, and not a refusal either: these were written,
        # but the platform measures them too and its own figure wins wherever
        # it produces one. What is loaded for them only fills a blank.
        write(f"  fallback only   {planned['behind_a_live_source']} line(s) "
              f"the platform also measures - it wins where it answers, so "
              f"these stand in only where it does not")

        if planned["no_person"]:
            write("")
            write(self.style.WARNING(
                f"  {len(planned['no_person'])} card(s) reach nobody:"))
            for item in planned["no_person"]:
                write(f"      {item['sheet']:24} "
                      f"{item['staff_name'][:24]:26} {item['why']}")

        if planned["unmapped"]:
            write("")
            write(self.style.WARNING(
                f"  {len(planned['unmapped'])} line(s) could not be matched "
                f"to a KPI on that person's card - the wording differs from "
                f"the seeded description, and a guess would score somebody "
                f"on the wrong line:"))
            for item in planned["unmapped"]:
                write(f"      {item['sheet']:24} {item['line'][:38]:40} "
                      f"{item['feed_key']}")

        if options["show"] and entries:
            write("")
            write("  figures:")
            for entry in entries[:options["show"]]:
                write(f"      {entry['kind']:7} {entry['sales_code']:10} "
                      f"{entry['kpi_code'][:44]:46} {entry['value']}")
            if len(entries) > options["show"]:
                write(f"      …and {len(entries) - options['show']} more")

        if not entries:
            write("")
            write(self.style.WARNING(
                "  Nothing to write. If every card says it reaches nobody, "
                "the sales codes on the workbook's List sheet do not match "
                "this platform's rosters - run card_doctor on one of them."))
            return

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("  --dry-run: nothing was written."))
            return

        written = workbook.save(entries, who="load_scorecard_workbook")
        write("")
        write(self.style.SUCCESS(
            f"  Saved {written['actuals']} actual(s) and "
            f"{written['targets']} target(s)."))
        write("  They show on the cards marked as entered rather than "
              "measured, and a warehouse figure still wins where there is "
              "one.")
        write("")
