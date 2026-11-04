"""How a host script reports to the alerting: deploy/host/disk_guard.sh.

    manage.py host_alert --subject "..." --body "..."       # it needs a person
    manage.py host_alert --fixed "..."                      # it fixed it itself

A problem goes to the downtime recipients. Something fixed needs nobody's time,
so it is noted for the next morning's digest and mails nobody.

Works with the database down, since a full disk is one of the ways it goes down:
the recipients then come from the file ``apps.observability.outage`` keeps.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Report a host problem by mail, or note a self-fix for the digest."

    def add_arguments(self, parser):
        parser.add_argument("--subject", default="")
        parser.add_argument("--body", default="")
        parser.add_argument("--fixed", default="",
                            help="What was fixed automatically.")

    def handle(self, *args, **options):
        from apps.observability import alerts, outage

        if options["fixed"]:
            from apps.observability.models import AlertState

            now = timezone.now()
            try:
                AlertState.objects.create(
                    key=f"{alerts.SELF_FIXED_PREFIX}{now.isoformat()}",
                    state="fixed", detail=options["fixed"][:2000], since=now)
            except Exception as exc:  # noqa: BLE001 - the fix itself is done
                self.stdout.write(f"could not note it: {exc}")
            self.stdout.write(f"noted: {options['fixed']}")
            return

        if not options["subject"]:
            raise CommandError("Give --subject and --body, or --fixed.")
        try:
            count = alerts.send(alerts.AlertRecipient.KIND_DOWNTIME,
                                options["subject"], options["body"])
        except Exception:  # noqa: BLE001 - the database may be what is down
            count = outage.mail(options["subject"], options["body"])
        self.stdout.write(f"sent to {count} recipient(s)")
