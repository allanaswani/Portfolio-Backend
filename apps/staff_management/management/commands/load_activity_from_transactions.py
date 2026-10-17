"""Build the customer activity mirror from transaction_diary.

    manage.py load_activity_from_transactions --from 2025-01 --to 2026-12
    manage.py load_activity_from_transactions --dry-run

Why this exists
───────────────
Active Customers and Digital Adoption are stated as a rate on the person's
own PRIOR-YEAR count, so they need 2025. Neither feed could give it:

* ``registation_data`` is not a table. "Routine Registration Data" is an
  emailed Excel REPORT - ``routine_registration_data.py`` in the ETL - and
  it COMPUTES those activity flags from ``transaction_diary``, ``customers``
  and ``daily_balance_movement``, every one of which is on this database;
* the lake's ``active_channels`` is a table, and reaches back only to
  January 2026.

So the same thing is computed here, from the same source, into the same
mirror the lake's feed fills - one row per customer per month, with a flag
for activity and a flag for digital activity. The card is unchanged: it
reads the mirror either way.

A month at a time, deliberately. ``transaction_diary`` is the bank's whole
transaction history, and one pass over all of it would be a single
statement nobody can cancel and nothing can report progress on.

ASCII only in the output: a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError

#: What counts as DIGITAL. The two channel descriptions the CEO dashboard
#: already treats as digital - see ``gceo_legacy.digital_active_30`` - so
#: "digital" means one thing on both screens.
DIGITAL_CHANNELS = (
    "ESB - ENTERPRISE SERVICE BUS",
    "KOCELA - SUBSCRIBER AND PAYMENT CHANNEL",
)

#: Per MONTH, not per run. A month that cannot be read in this long is
#: reported and the rest still load.
TIMEOUT_MS = 600_000

SQL = """
    SELECT t.fk_customercust_id AS cust_id,
           MAX(CASE WHEN t.chanel_description IS NOT NULL
                     AND TRIM(t.justific_name) = ANY(%s)
                    THEN 1 ELSE 0 END) AS digital
    FROM transaction_diary t
    WHERE t.tmstamp >= %s AND t.tmstamp < %s
      AND t.fk_customercust_id IS NOT NULL
    GROUP BY t.fk_customercust_id
"""


def _month(text, what):
    try:
        year, month = str(text).strip().split("-")
        return datetime.date(int(year), int(month), 1)
    except Exception as exc:  # noqa: BLE001
        raise CommandError(
            f"--{what} should be YYYY-MM, for example 2025-01.") from exc


def _next(month):
    return (month.replace(day=28)
            + datetime.timedelta(days=4)).replace(day=1)


class Command(BaseCommand):
    help = "Build the activity mirror from transaction_diary."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="start", default="",
                            help="First month, YYYY-MM. Default: January of "
                                 "last year.")
        parser.add_argument("--to", dest="end", default="",
                            help="Last month, YYYY-MM. Default: this month.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Count what each month holds, write none.")

    def handle(self, **options):
        from django.db import connection, transaction

        from apps.staff_management import active_channels
        from apps.staff_management.models import CustomerMonthlyActivity

        write = self.stdout.write
        today = datetime.date.today()

        start = (_month(options["start"], "from") if options["start"]
                 else datetime.date(today.year - 1, 1, 1))
        end = (_month(options["end"], "to") if options["end"]
               else today.replace(day=1))
        if end < start:
            raise CommandError("--to is before --from.")

        write("")
        write(f"  source            transaction_diary")
        write(f"  months            {start:%b %Y} to {end:%b %Y}")
        write(f"  digital channels  {len(DIGITAL_CHANNELS)}")
        write("")

        month = start
        total = digital_total = 0
        failed = []
        while month <= end:
            closes = _next(month)
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    # SET LOCAL only takes effect inside a transaction -
                    # outside one PostgreSQL ignores it with a warning.
                    cur.execute(
                        f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
                    cur.execute(SQL, [list(DIGITAL_CHANNELS), month, closes])
                    rows = cur.fetchall()
            except Exception as exc:  # noqa: BLE001 - one month failing must
                # not cost the others, and the reason belongs in the output.
                failed.append((month, str(exc)[:120]))
                write(self.style.WARNING(
                    f"      {month:%b %Y}  could not be read: "
                    f"{str(exc)[:90]}"))
                month = closes
                continue

            digital = sum(1 for _c, d in rows if d)
            total += len(rows)
            digital_total += digital
            write(f"      {month:%b %Y}  {len(rows):>8,} active   "
                  f"{digital:>8,} digital")

            if not options["dry_run"] and rows:
                CustomerMonthlyActivity.objects.bulk_create(
                    [CustomerMonthlyActivity(
                        cust_id=int(cust_id), month=month,
                        active=True, digital_active=bool(flag))
                     for cust_id, flag in rows],
                    update_conflicts=True,
                    update_fields=["active", "digital_active", "loaded_at"],
                    unique_fields=["cust_id", "month"],
                    batch_size=5000)
            month = closes

        write("")
        write(f"  customer-months   {total:,} ({digital_total:,} digital)")
        if failed:
            write(self.style.WARNING(
                f"  {len(failed)} month(s) could not be read: "
                f"{', '.join(m.strftime('%b %Y') for m, _why in failed)}"))

        if options["dry_run"]:
            write("")
            write(self.style.WARNING("  --dry-run: nothing was written."))
            return

        span = active_channels.coverage()
        write("")
        write(f"  mirror now holds  {span['rows']:,} row(s), "
              f"{span['first_month']:%b %Y} to {span['last_month']:%b %Y}")
        years = sorted({m.year for m in span["months"]})
        write(f"  years             {years}")
        if len(years) < 2:
            write(self.style.WARNING(
                "  Still one year only, so the prior-year base a "
                "\"grow by 20%\" target needs cannot be read. Widen --from."))
        else:
            write("  Both years are there, so Active Customers and Digital "
                  "Adoption can be scored against their own prior year.")
        write("")
