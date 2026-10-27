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
from django.utils import timezone as djtimezone

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

#: The last transaction per customer, for ONE MONTH.
#:
#: One month, not the whole lookback, and that is the entire point. The first
#: version of this swept 400 days in a single statement and was cancelled by
#: the database twice - once on a page view at 25 seconds, and again here at
#: the ten-minute ceiling. The rule was already written at the top of this
#: file for the monthly feed: "A month at a time, deliberately.
#: transaction_diary is the bank's whole transaction history, and one pass
#: over all of it would be a single statement nobody can cancel and nothing
#: can report progress on." This now obeys it.
#:
#: The caller walks the months NEWEST FIRST and keeps the first answer it
#: gets for each customer, which is by definition their most recent
#: transaction. No GREATEST, no upsert, and every statement is bounded by one
#: month of rows.
LAST_TXN_MONTH_SQL = """
    SELECT t.fk_customercust_id AS cust_id, MAX(t.tmstamp) AS last_txn
    FROM transaction_diary t
    WHERE t.tmstamp >= %s AND t.tmstamp < %s
      AND t.fk_customercust_id IS NOT NULL
    GROUP BY t.fk_customercust_id
"""

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


def _aware(value, zone):
    """Stamp the warehouse's naive timestamps with the bank's own time zone.

    ``transaction_diary.tmstamp`` is ``timestamp without time zone``, so
    psycopg hands back a naive ``datetime`` for every row.

    Django copes with that - ``DateTimeField.get_prep_value`` localises a
    naive value with ``get_default_timezone()``, which is exactly what this
    does, so the figures were never wrong. What it also does is
    ``warnings.warn`` FIRST, once per value. The message embeds the timestamp
    itself, so Python's warning registry cannot collapse them, and a run over
    a few hundred thousand customers writes a few hundred thousand
    RuntimeWarnings to the console. That is what made the first production
    attempt look hung at the write step, with the months already read.

    So the conversion happens here, up front and once per row, and Django
    finds nothing left to complain about. Africa/Nairobi has never observed
    DST, so there is no ambiguous hour for ``make_aware`` to resolve - the
    case Django's own comment there says it cannot handle.

    An already-aware value is returned untouched, and ``None`` stays ``None``.
    """
    if value is None or djtimezone.is_aware(value):
        return value
    return djtimezone.make_aware(value, zone)


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
        parser.add_argument(
            "--last-transaction-days", type=int, default=400,
            help="How far back to look when refreshing the per-customer "
                 "last-transaction mirror the branch activity tables read. "
                 "0 skips that step.")
        parser.add_argument(
            "--list-lake-tables", default="",
            help="Ask Trino which tables the lake holds whose name contains "
                 "this text, and stop. Nothing is read or written - this is "
                 "for finding the right table instead of guessing one.")
        parser.add_argument(
            "--only-last-transaction", action="store_true",
            help="Refresh ONLY that mirror and skip the monthly rebuild. The "
                 "form for a nightly cron: the monthly feed moves once a "
                 "month, this moves every day.")

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

        if options["list_lake_tables"]:
            self._lake_tables(write, options["list_lake_tables"])
            return

        if options["only_last_transaction"]:
            self._refresh_last_transaction(options, write)
            return

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

    def _refresh_last_transaction(self, options, write):
        """Rebuild the per-customer last-transaction mirror, a month at a time.

        Replaced wholesale rather than merged: the window moves forward every
        night, so a customer who drops out of it has genuinely gone quiet and
        must stop being reported as active. Merging would leave last night's
        answer standing for ever.

        Walked NEWEST MONTH FIRST, keeping the first answer seen for each
        customer - which is their latest transaction, with no GREATEST and no
        upsert. Every statement reads one month, so none of them is the
        unbounded sweep that got cancelled twice.

        A month that cannot be read is reported and the rest still load. The
        mirror is written only at the end, in one transaction, so a run that
        dies halfway leaves yesterday's mirror standing rather than a half
        one that looks complete.
        """
        from django.db import connection, transaction

        from apps.staff_management.models import CustomerLastTransaction

        days = int(options.get("last_transaction_days") or 0)
        if days <= 0:
            write("  last-transaction mirror: skipped (0 days asked for).")
            return

        today = datetime.date.today()
        floor = today - datetime.timedelta(days=days)
        # Newest month first. `latest` keeps the first answer per customer.
        months = []
        cursor_month = today.replace(day=1)
        while cursor_month >= floor.replace(day=1):
            months.append(cursor_month)
            cursor_month = (cursor_month - datetime.timedelta(days=1)).replace(day=1)

        write("")
        write(f"  last-transaction mirror, {len(months)} month(s) back to "
              f"{floor:%b %Y}, newest first")

        # Looked up once, not per row: this loop sees hundreds of thousands
        # of timestamps and `transaction_diary.tmstamp` is "timestamp WITHOUT
        # time zone", so every one of them arrives naive.
        zone = djtimezone.get_default_timezone()

        latest = {}
        failed = []
        for month in months:
            closes = _next(month)
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
                    cur.execute(LAST_TXN_MONTH_SQL, [month, closes])
                    rows = cur.fetchall()
            except Exception as exc:  # noqa: BLE001 - one month failing must
                # not cost the others, and the reason belongs in the output.
                failed.append((month, str(exc)[:120]))
                write(self.style.WARNING(
                    f"      {month:%b %Y}  could not be read: "
                    f"{str(exc)[:90]}"))
                continue

            fresh = 0
            for cust_id, last_txn in rows:
                key = int(cust_id)
                if key not in latest:        # newest month wins
                    latest[key] = _aware(last_txn, zone)
                    fresh += 1
            write(f"      {month:%b %Y}  {len(rows):>8,} transacted   "
                  f"{fresh:>8,} new to the mirror")

        write(f"      {len(latest):,} customer(s) in all")
        if options["dry_run"]:
            write(self.style.WARNING("  --dry-run: nothing was written."))
            return
        if not latest:
            # An empty read must never wipe a mirror that has figures in it.
            # The same rule the cost load already enforces.
            write(self.style.WARNING(
                "  Nothing came back, so the mirror was left as it was - an "
                "empty read must not wipe one that has figures in it."))
            return
        if failed:
            # A month that failed is a month of customers who would silently
            # look dormant. Said plainly rather than buried above.
            write(self.style.WARNING(
                f"  {len(failed)} month(s) could not be read. Customers whose "
                f"last transaction falls in them will read as quieter than "
                f"they are."))

        with transaction.atomic():
            CustomerLastTransaction.objects.all().delete()
            CustomerLastTransaction.objects.bulk_create(
                [CustomerLastTransaction(cust_id=cust_id, last_txn=last_txn,
                                         lookback_days=days)
                 for cust_id, last_txn in latest.items()],
                batch_size=5000)
        write(self.style.SUCCESS(
            f"  Wrote {len(latest):,} row(s) to customer_last_transaction."))

    def _lake_tables(self, write, pattern):
        """What the lake actually holds, so nothing has to be guessed.

        Added because the obvious next move is to run this aggregate in Trino
        instead of Postgres, and the lake tables this codebase already knows
        about - active_channels, dim_customer, eom_deposits, sap_cost_data and
        four more - include no day-grain transaction table. Naming one on a
        hunch is how a wrong table ends up in production, so this asks.
        """
        from apps.staff_management import cost_ingest

        try:
            cursor = cost_ingest._connect().cursor()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        catalog = "delta"
        cursor.execute(f"SHOW SCHEMAS FROM {catalog}")
        schemas = [r[0] for r in cursor.fetchall()]
        write("")
        write(f"  schemas in {catalog}: {', '.join(schemas)}")
        for schema in schemas:
            if schema in ("information_schema",):
                continue
            try:
                cursor.execute(f"SHOW TABLES FROM {catalog}.{schema}")
                names = [r[0] for r in cursor.fetchall()]
            except Exception as exc:  # noqa: BLE001
                write(f"    {schema}: could not list ({str(exc)[:60]})")
                continue
            hits = [n for n in names if pattern.lower() in n.lower()]
            write(f"    {schema}: {len(names)} table(s), "
                  f"{len(hits)} matching {pattern!r}")
            for name in hits:
                write(f"        {catalog}.{schema}.{name}")
