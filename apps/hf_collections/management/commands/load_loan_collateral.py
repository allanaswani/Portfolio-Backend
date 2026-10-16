"""Mirror the lake's loan collateral into Postgres.

    manage.py load_loan_collateral --dry-run
    manage.py load_loan_collateral

What a loan is actually secured on, from account_collateral joined to
collateral. The collections page typed collateral from product_mapping
before, which types the PRODUCT - so every mortgage read "PROPERTY" whether
or not a charge existed.

Mirrored rather than read live: the customer page is built on request, and a
lake read on that path is what hands the browser a dead connection.

Credentials come from the environment (TRINO_*), never from this file.

ASCII only in the output: a box-drawing character raises UnicodeEncodeError
on the Windows console and takes the command down with it.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Load loan collateral from the lake into the Postgres mirror."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be written, write none.")
        parser.add_argument("--account", default="",
                            help="Show the charges against one loan account.")

    def handle(self, **options):
        from apps.hf_collections import collateral

        write = self.stdout.write

        if options["account"]:
            account = options["account"].strip()
            found = collateral.for_accounts([account])
            charges = found.get(account, [])
            write("")
            write(f"  {account}: {len(charges)} charge(s)")
            for charge in charges:
                value = charge["estimated_value"]
                write(f"      {charge['type'][:34]:36} "
                      + (f"{value:>18,.2f}" if value is not None
                         else f"{'no value':>18}")
                      + (f"  expires {charge['expires_on']}"
                         if charge["expires_on"] else ""))
            if not charges:
                write(self.style.WARNING(
                    "  Nothing. Either that account carries no charge, or "
                    "the mirror has not been loaded - run this without "
                    "--account."))
            write("")
            return

        write("  reading the lake ...")
        try:
            rows = collateral.fetch_from_trino()
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            raise CommandError(f"The lake could not be read: {exc}") from exc

        entries, report = collateral.plan(rows)
        write(f"  charges read      {report['read']:,}")
        write(f"  loan accounts     {report['accounts']:,}")
        if report["duplicates"]:
            write(f"  duplicates        {report['duplicates']:,} charge(s) "
                  f"listed more than once, collapsed - one charge is one "
                  f"charge")
        if report["no_account"]:
            write(self.style.WARNING(
                f"  {report['no_account']} charge(s) name no loan account "
                f"and were left out - a charge nothing hangs off cannot be "
                f"shown against anything."))

        write("")
        for kind, count in sorted(report["by_type"].items(),
                                  key=lambda kv: -kv[1]):
            write(f"      {(kind or '(untyped)')[:34]:36} {count:6,}")

        if not entries:
            raise CommandError("Nothing was read, so nothing was written.")

        if options["dry_run"]:
            write("")
            write(self.style.WARNING(
                f"  --dry-run: {report['to_write']:,} row(s) would be "
                f"written. Nothing was."))
            return

        written = collateral.save(entries)
        write("")
        write(self.style.SUCCESS(f"  Wrote {written:,} charge(s)."))

        span = collateral.coverage()
        write(f"  mirror now holds  {span['charges']:,} charge(s) over "
              f"{span['accounts']:,} loan account(s)")
        write("  They show on the customer page straight away.")
        write("")
