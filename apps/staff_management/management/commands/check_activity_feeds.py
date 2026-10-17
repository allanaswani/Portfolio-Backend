"""What the Active Customers and Digital Adoption lines can actually read.

    manage.py check_activity_feeds
    manage.py check_activity_feeds --code AKL3116

Those two lines read the registration data first and the lake's mirror
behind it. When a card says "that figure could not be read" there are four
different things it can mean, and from the card they look identical:

  * the table is not on this database under any name we try;
  * it is there under a name or a column shape we do not recognise;
  * it is there and recognised but holds no 2025, so the prior-year base a
    "grow by 20%" target needs cannot be read;
  * it is there and this person simply has nobody active in two consecutive
    months.

This reports which of the four it is, and names every ``%regist%`` table on
the database so a spelling we have not tried shows up rather than being
guessed at.

ASCII only in the output: a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Report what the activity feeds hold, and why a line is blank."

    def add_arguments(self, parser):
        parser.add_argument("--code", default="",
                            help="Run the reader for one sales code.")

    def handle(self, **options):
        from django.db import connection

        from apps.staff_management import active_channels
        from apps.staff_management import registration_activity as ra

        write = self.stdout.write

        # ── every table that could be it ──────────────────────────────────
        write("")
        write("  Tables on this database with 'regist' in the name:")
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name ILIKE %s ORDER BY 1", ["%regist%"])
                names = [row[0] for row in cur.fetchall()]
        except Exception as exc:  # noqa: BLE001
            names = []
            write(self.style.WARNING(f"      could not be listed: {exc}"))
        for name in names:
            write(f"      {name}")
        if not names:
            write(self.style.WARNING("      none at all"))

        write("")
        write(f"  Names tried, in order: {', '.join(ra.TABLE_NAMES)}")

        # ── the registration feed ─────────────────────────────────────────
        found = ra.find_table()
        write("")
        if not found:
            write(self.style.WARNING(
                "  REGISTRATION DATA: not recognised."))
            write("      A table is only recognised when it carries columns "
                  "named")
            write(f"      {ra.PREFIX_ACTIVE}_<month>_<year>, for example "
                  f"{ra.PREFIX_ACTIVE}_dec_2025.")
            for name in names:
                columns = ra._columns_of(name)
                flags = [c for c in columns
                         if "active" in c.lower() or "trx" in c.lower()]
                write(f"      {name}: {len(columns)} column(s)"
                      + (f"; closest looking: {', '.join(flags[:8])}"
                         if flags else "; none look like activity flags"))
        else:
            span = ra.coverage()
            write(self.style.SUCCESS(f"  REGISTRATION DATA: {found}"))
            write(f"      months       {len(span['months'])}: "
                  + ", ".join(m.strftime("%b %Y")
                              for m in span["months"][:18]))
            write(f"      pairs        {len(span['complete_pairs'])} month(s) "
                  f"have the month before them, which is what "
                  f"\"two months active\" needs")
            years = sorted({m.year for m in span["months"]})
            write(f"      years        {years}")
            if len(years) < 2:
                write(self.style.WARNING(
                    "      Only one year, so the PRIOR-YEAR base a "
                    "\"grow by 20%\" target is applied to cannot be read. "
                    "That is the message on the card."))
            write(f"      digital      {len(span['digital_months'])} month(s) "
                  f"of {ra.PREFIX_DIGITAL}_* columns")

        # ── the lake's mirror, which is the second feed ───────────────────
        mirror = active_channels.coverage()
        write("")
        if not mirror["rows"]:
            write("  LAKE MIRROR: empty - run load_active_channels.")
        else:
            write(f"  LAKE MIRROR: {mirror['rows']:,} row(s), "
                  f"{mirror['first_month']:%b %Y} to "
                  f"{mirror['last_month']:%b %Y}")
            write("      Only reached when the registration table is ABSENT "
                  "- not when it is present and answers nothing.")

        # ── one person ────────────────────────────────────────────────────
        if options["code"]:
            import datetime

            code = options["code"].strip()
            year = datetime.date.today().year
            write("")
            write(f"  {code}:")
            for label, digital in (("active", False), ("digital", True)):
                result = ra.two_month_active(code, year, digital=digital)
                if "error" in result:
                    write(f"      {label:8} {result['error']}")
                elif not result:
                    write(f"      {label:8} the feed reaches no month with "
                          f"two consecutive months of activity")
                else:
                    for when in sorted(result, reverse=True):
                        count, as_at = result[when]
                        write(f"      {label:8} {when}: {count} customer(s), "
                              f"as at {as_at}")
        write("")
