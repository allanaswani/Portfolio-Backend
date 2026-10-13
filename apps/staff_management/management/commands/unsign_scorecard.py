"""Withdraw a scorecard signature.

    manage.py unsign_scorecard FJ4145
    manage.py unsign_scorecard FJ4145 --period 2026-10
    manage.py unsign_scorecard FJ4145 --list

The screen does this too, and that is where it belongs — this is for a
signature that needs undoing before the fix is deployed, and for the case the
screen refuses: one the line manager has already counter-signed.

The frozen copy is kept either way. "This was signed and then withdrawn" is
part of the record; deleting the copy would hide it.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Withdraw a scorecard signature so the card goes back to live."

    def add_arguments(self, parser):
        parser.add_argument("sales_code")
        parser.add_argument(
            "--period", default="",
            help="YYYY-MM. The current signing period when left out.")
        parser.add_argument(
            "--list", action="store_true",
            help="Show this person's signatures and change nothing.")
        parser.add_argument(
            "--reason", default="withdrawn by an administrator",
            help="Recorded on the row.")

    def handle(self, **options):
        from django.utils import timezone

        from apps.staff_management.scorecard_automation.models import (
            ScorecardSignoff)
        from apps.staff_management.scorecard_signoff import period_for

        write = self.stdout.write
        code = options["sales_code"].strip()

        rows = ScorecardSignoff.objects.filter(
            sales_code__iexact=code).order_by("-period")
        if not rows.exists():
            raise CommandError(f"{code} has no signoff row at all.")

        if options["list"]:
            write("")
            for row in rows:
                state = []
                if row.signed_at:
                    state.append(f"signed by {row.signed_by_name} on "
                                 f"{row.signed_at:%d %b %Y}")
                if row.manager_signed_at:
                    state.append(f"counter-signed by "
                                 f"{row.manager_signed_by_name} on "
                                 f"{row.manager_signed_at:%d %b %Y}")
                if row.withdrawn_at:
                    state.append(f"withdrawn by {row.withdrawn_by_name} on "
                                 f"{row.withdrawn_at:%d %b %Y}")
                if not state:
                    state.append("unsigned")
                score = ("-" if row.performance_score is None
                         else f"{row.performance_score * 100:.1f}%")
                write(f"  {row.period}  {score:>8}  {'; '.join(state)}")
            write("")
            return

        period = options["period"].strip() or period_for()
        row = rows.filter(period=period).first()
        if row is None:
            raise CommandError(
                f"{code} has no signoff row for {period}. Run with --list to "
                f"see which periods they have.")
        if not row.signed_at and not row.manager_signed_at:
            raise CommandError(
                f"{code}'s card for {period} is not signed, so there is "
                f"nothing to withdraw.")

        was = []
        if row.signed_at:
            was.append(f"{row.signed_by_name} on {row.signed_at:%d %b %Y}")
        if row.manager_signed_at:
            was.append(f"counter-signed by {row.manager_signed_by_name} on "
                       f"{row.manager_signed_at:%d %b %Y}")

        row.withdrawn_at = timezone.now()
        row.withdrawn_by_name = "unsign_scorecard"
        row.withdrawn_reason = options["reason"][:255]
        row.signed_at = None
        row.signed_by = None
        row.manager_signed_at = None
        row.manager_signed_by = None
        row.save()

        write("")
        write(self.style.SUCCESS(
            f"  {code}'s signature for {period} has been withdrawn "
            f"(was: {'; '.join(was)})."))
        write("  Their card is back to live figures and can be signed again.")
        write("  The copy that was signed is still on the row.")
        write("")
