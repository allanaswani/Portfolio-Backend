"""Give every ``trade_finance_data`` row its register entry.

Re-links a row to the entry it was a copy of (after an Administration upload
replaced the year) or creates one - see :mod:`apps.trade_register.mirror`.
Idempotent; deletes nothing; never changes a TF row. The Trade Finance upload
now runs this itself, so it is only needed once, for rows already loaded.

    python manage.py backfill_trade_register
"""

from django.core.management.base import BaseCommand

from ...mirror import mirror_trade_finance


class Command(BaseCommand):
    help = "Link or create register entries for trade_finance_data rows without one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Only process the first N unlinked TF rows (0 = all).",
        )

    def handle(self, *args, **opts):
        out = mirror_trade_finance(limit=opts["limit"])
        self.stdout.write(self.style.SUCCESS(
            f"Backfill complete: {out['created']} entries created, "
            f"{out['relinked']} re-linked, {out['skipped']} skipped "
            f"(issue date not readable)."
        ))
        if out["skipped_ids"]:
            self.stdout.write(
                "trade_finance_data ids skipped: "
                + ", ".join(str(i) for i in out["skipped_ids"][:200]))
