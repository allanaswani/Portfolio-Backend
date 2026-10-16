"""Mirror the lake's customer-activity feed into Postgres.

    manage.py load_active_channels --dry-run
    manage.py load_active_channels

Feeds the Active Customers and Digital Adoption lines. ``active_channels``
lives in the lake and the scorecard is rebuilt on every page view, so this
runs on a schedule and the card reads Postgres - a heavy read on the card
path is what blanked these two lines before.

Credentials come from the environment (``TRINO_*``), never from this file.

ASCII only in the output: a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load delta.gold_db.active_channels into the Postgres mirror."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be written, write none.")

    def handle(self, **options):
        from apps.staff_management import active_channels

        write = self.stdout.write

        write("  reading the lake ...")
        try:
            rows = active_channels.fetch_from_trino()
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            raise CommandError(f"The lake could not be read: {exc}") from exc

        entries, report = active_channels.plan(rows)
        write(f"  lake rows         {report['read']:,} (already aggregated to "
              f"one row per customer per month)")
        write(f"  customers         {report['customers']:,}")
        write(f"  months            {len(report['months'])} - "
              f"{', '.join(m.strftime('%b %Y') for m in report['months'])}")

        if report["unreadable_month"]:
            write(self.style.WARNING(
                f"  {len(report['unreadable_month'])} month label(s) could "
                f"not be read and were left out: "
                f"{', '.join(report['unreadable_month'][:6])}. The lake holds "
                f"this as text, so a change of format shows up here."))

        if not entries:
            raise CommandError(
                "Nothing could be read from the feed. Nothing was written - "
                "the mirror keeps whatever it already had.")

        if options["dry_run"]:
            write("")
            write(self.style.WARNING(
                f"  --dry-run: {report['to_write']:,} row(s) would be "
                f"written. Nothing was."))
            return

        written = active_channels.save(entries)
        write("")
        write(self.style.SUCCESS(f"  Wrote {written:,} row(s)."))

        span = active_channels.coverage()
        write("")
        write(f"  mirror now holds  {span['rows']:,} row(s), "
              f"{span['first_month']:%b %Y} to {span['last_month']:%b %Y}")
        if span["latest_pair"]:
            write(f"  latest full pair  {span['latest_pair']:%b %Y} "
                  f"(with the month before it) - this is the figure the "
                  f"cards will show")
        else:
            write(self.style.WARNING(
                "  No two CONSECUTIVE months are loaded, so no card can show "
                "a two-month-active figure yet."))

        years = sorted({m.year for m in span["months"]})
        if len(years) < 2:
            write("")
            write(self.style.WARNING(
                f"  The feed covers {years[0] if years else 'no year'} only. "
                f"The cards state their target as a rate on the person's own "
                f"PRIOR-YEAR count, and that base cannot come from a feed "
                f"that does not go back a year - so the target has to come "
                f"from the scorecard workbook until the lake carries the "
                f"earlier months."))
        write("")
