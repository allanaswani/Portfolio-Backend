"""Remove briefs that should never have existed - tests, and ones raised by mistake.

    python manage.py purge_briefs --list                     # every brief, to pick from
    python manage.py purge_briefs DB-8015F4F0 DB-A3748A4F    # shows what would go
    python manage.py purge_briefs DB-8015F4F0 DB-A3748A4F --confirm

The module itself never deletes a brief - closing archives it, because what
the department produced is its own record. This is the one exception, for
rows that are NOT a record of anything: test entries and a brief created by
mistake (17 Nov 2026, Marketing). It deletes the brief with its timeline,
artwork, comments and checklist, and its rows in the history table, so a
deleted test does not linger in the audit trail either. Without --confirm it
only prints.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Delete named briefs (tests / mistakes) with everything under them."

    def add_arguments(self, parser):
        parser.add_argument("references", nargs="*",
                            help="Brief references, e.g. DB-8015F4F0.")
        parser.add_argument("--list", action="store_true",
                            help="List every brief and stop.")
        parser.add_argument("--confirm", action="store_true",
                            help="Actually delete. Without it nothing changes.")

    def handle(self, *args, **opts):
        from apps.design_briefs.models import DesignBrief

        write = self.stdout.write
        if opts["list"]:
            for b in DesignBrief.objects.order_by("created_at"):
                write(f"  {b.reference}  {b.created_at:%d %b %Y}  {b.status:<11}  "
                      f"{b.design_item[:40]:<40}  {b.department[:30]:<30}  "
                      f"-> {b.addressed_to[:25]}")
            return

        refs = sorted({r.strip().upper() for r in opts["references"] if r.strip()})
        if not refs:
            raise CommandError("Name the briefs to remove, or use --list.")
        found = list(DesignBrief.objects.filter(reference__in=refs))
        missing = set(refs) - {b.reference for b in found}
        if missing:
            raise CommandError(f"No such brief: {', '.join(sorted(missing))}. "
                               "Nothing was deleted.")

        for b in found:
            write(f"  {b.reference}  {b.design_item}  ({b.department} -> "
                  f"{b.addressed_to}), {b.events.count()} event(s), "
                  f"{b.proofs.count()} artwork version(s), "
                  f"{b.comments.count()} comment(s)")
        if not opts["confirm"]:
            write(self.style.WARNING(
                f"  {len(found)} brief(s) would be deleted. Add --confirm to do it."))
            return

        with transaction.atomic():
            # The brief first: deleting it writes one last history row of its
            # own, which the history delete after it then takes too.
            gone = 0
            for b in found:
                gone += b.delete()[0]
            history = DesignBrief.history.model.objects.filter(
                reference__in=refs).delete()[0]
        write(self.style.SUCCESS(
            f"  deleted {len(found)} brief(s) - {gone} row(s) with everything "
            f"under them, and {history} history row(s)"))
