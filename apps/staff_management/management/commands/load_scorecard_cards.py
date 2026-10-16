"""Load people's own signed scorecards - sales and back office.

    manage.py load_scorecard_cards "C:/cards/*.xlsx" --dry-run
    manage.py load_scorecard_cards /data/cards/

The master workbook carries one card per ROLE - a worked example - so loading
it reaches ten people. Everybody else has their own file in the same layout,
and their targets exist nowhere else: Lydia Apanja's Income Contribution
target is on Lydia Apanja's card.

These files carry no sales code, only a name, so the person is found by name
and only when exactly one match exists. A card that cannot be placed is
reported, never guessed at.

ASCII only in the output - a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

import glob
import pathlib

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load individual scorecard files (.xlsx)."

    def add_arguments(self, parser):
        parser.add_argument(
            "path", help="A file, a folder, or a glob such as '*.xlsx'.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be written, write none.")
        parser.add_argument("--show", type=int, default=20)

    def handle(self, **options):
        from apps.staff_management import scorecard_cards

        write = self.stdout.write
        given = options["path"]

        target = pathlib.Path(given)
        if target.is_dir():
            paths = sorted(str(p) for p in target.glob("*.xls[xm]"))
        elif any(ch in given for ch in "*?["):
            paths = sorted(glob.glob(given))
        elif target.exists():
            paths = [str(target)]
        else:
            raise CommandError(f"{given} is not there.")

        if not paths:
            raise CommandError(f"No .xlsx files matched {given}.")

        cards, skipped = [], []
        for path in paths:
            try:
                cards.append(scorecard_cards.read_any(path))
            except Exception as exc:  # noqa: BLE001 - the reason is useful
                skipped.append((pathlib.Path(path).name, str(exc)))

        write("")
        write(f"  files             {len(paths)}")
        write(f"  cards read        {len(cards)}")
        for name, why in skipped[:options["show"]]:
            write(self.style.WARNING(f"      {name[:44]:46} {why[:90]}"))

        if not cards:
            raise CommandError("None of those files is a scorecard.")

        entries, report = scorecard_cards.plan_any(cards)
        matched = sum(1 for c in report["cards"] if c["matched"])
        write(f"  matched a person  {matched} of {len(cards)}")
        write(f"  to write          {report['targets']} target(s), "
              f"{report['actuals']} actual(s)")
        if report.get("targets_left_alone"):
            write(f"  targets kept      {report['targets_left_alone']} on the "
                  f"teller / CSO cards. Those carry a YEAR-TO-DATE target, "
                  f"already pro-rated, and the platform pro-rates a year's "
                  f"target itself - loading them would do it twice.")

        if report["no_person"]:
            write("")
            write(self.style.WARNING(
                f"  {len(report['no_person'])} card(s) reach nobody:"))
            for item in report["no_person"][:options["show"]]:
                write(f"      {item['staff_name'][:26]:28} {item['why'][:88]}")

        if report["unmapped"]:
            write("")
            write(self.style.WARNING(
                f"  {len(report['unmapped'])} line(s) could not be mapped:"))
            for item in report["unmapped"][:options["show"]]:
                write(f"      {item['staff_name'][:20]:22} "
                      f"{item['line'][:60]}")

        if report["mismatched_title"]:
            write("")
            write(self.style.WARNING(
                f"  {len(report['mismatched_title'])} card(s) state a title "
                f"the roster does not agree with. Loaded anyway - titles "
                f"drift, and the figures are still theirs:"))
            for item in report["mismatched_title"][:options["show"]]:
                write(f"      {item['staff_name'][:22]:24} card says "
                      f"{item['card_says'][:18]:20} roster says "
                      f"{item['roster_says']}")

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("  --dry-run: nothing was written."))
            return

        written = scorecard_cards.save(entries, who="load_scorecard_cards")
        write("")
        write(self.style.SUCCESS(f"  Saved {written} figure(s)."))
        write("  They show on the cards straight away.")
        write("")
