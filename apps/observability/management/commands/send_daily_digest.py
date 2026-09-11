"""One summary a day: uptime, speed, what broke, and what changed.

The body is deliberately plain ASCII. It is printed to a console by --dry-run,
and a console that cannot encode an em dash should not be able to crash the
job that reports on everything else.

    0 7 * * * docker exec hf-backend python manage.py send_daily_digest

Unlike the immediate alerts this is sent regardless of state — it is the
"nothing is on fire" message as much as the other kind, and a monitoring system
nobody hears from is one nobody trusts.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Avg
from django.utils import timezone

from apps.observability import alerts, audit, health, metrics
from apps.observability.models import MonitoredService, ServiceProbe


def _plain(text, limit=140):
    """One short ASCII line. The body is printed to a console by --dry-run, and
    a console that cannot encode an em dash must not crash the job that reports
    on everything else."""
    flat = " ".join(str(text or "").split())
    flat = flat.replace("—", "-").replace("–", "-").replace("…", "...")
    flat = flat.encode("ascii", "replace").decode("ascii")
    return flat[: limit - 3] + "..." if len(flat) > limit else flat


class Command(BaseCommand):
    help = "Email a 24-hour summary to the daily-digest recipients."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        hours = max(1, options["hours"])
        body = self.build(hours)

        if options["dry_run"]:
            self.stdout.write(body)
            return

        today = timezone.localdate()
        count = alerts.send(
            alerts.AlertRecipient.KIND_DAILY_DIGEST,
            f"Daily digest - {today}",
            body,
        )
        self.stdout.write(f"digest sent to {count} recipient(s)")

    def build(self, hours):
        lines = [f"Portfolio health, last {hours} hours", "=" * 46, ""]

        # -- The application ------------------------------------------------
        overview = metrics.overview(hours=hours)
        uptime = overview["uptime"]
        lines += [
            "APPLICATION",
            f"  Requests served : {overview['requests']:,} "
            f"({overview['throughput_per_min']}/min)",
            f"  Median response : {overview['p50']} ms   p95: {overview['p95']} ms",
            f"  Server errors   : {overview['errors']} ({overview['error_rate']}%)",
            f"  Active users    : {overview['active_users']}",
        ]
        if uptime.get("measured"):
            lines.append(
                f"  Uptime          : {uptime['percent']}% "
                f"({uptime['downtime_minutes']} min down)")
        else:
            # Never invent a number here. Traffic is not uptime.
            lines.append("  Uptime          : not measured - the heartbeat job "
                         "is not scheduled")
        lines.append("")

        # -- Other systems --------------------------------------------------
        since = timezone.now() - timedelta(hours=hours)

        services = list(MonitoredService.objects.filter(is_active=True))
        if services:
            lines.append("OTHER SYSTEMS")
            for service in services:
                probes = ServiceProbe.objects.filter(
                    service=service, created_at__gte=since)
                total = probes.count()
                if not total:
                    lines.append(f"  {service.name}: not probed")
                    continue
                failed = probes.filter(ok=False).count()
                ok_pct = round((total - failed) / total * 100, 1)
                avg = probes.filter(ok=True).aggregate(m=Avg("duration_ms"))["m"]
                avg_txt = f"{round(avg)} ms" if avg else "-"
                lines.append(
                    f"  {service.name}: {ok_pct}% reachable, avg {avg_txt}"
                    + (f", {failed} failed check(s)" if failed else "")
                )
            lines.append("")

        # -- Data -------------------------------------------------------------
        rows = health.table_health()
        problems = [r for r in rows
                    if r["status"] in ("missing", "empty", "stale", "error")]
        lines.append("DATA")
        lines.append(f"  Warehouse tables: {len(rows)}")
        if problems:
            lines.append(f"  Needing attention: {len(problems)}")
            for row in problems[:15]:
                # "error" on its own tells the reader nothing they can act on.
                # The reason is almost always MAX() over an unindexed column
                # timing out, which is a different job from a stalled ETL.
                why = f" - {_plain(row['error'])}" if row.get("error") else ""
                lines.append(f"    - {row['table']}: {row['status']}{why}")
            if len(problems) > 15:
                lines.append(f"    ... and {len(problems) - 15} more")
        else:
            lines.append("  Every table is loaded and fresh.")
        lines.append("")

        # -- Changes ----------------------------------------------------------
        changes = audit.feed(since=since, limit=500, with_changes=False)
        lines.append("CHANGES")
        lines.append(f"  Recorded: {len(changes)}")
        by_user = {}
        deletions = 0
        for row in changes:
            by_user[row["username"] or "system/job"] = \
                by_user.get(row["username"] or "system/job", 0) + 1
            if row["action"] == "deleted":
                deletions += 1
        if deletions:
            lines.append(f"  Deletions: {deletions}")
        for user, n in sorted(by_user.items(), key=lambda kv: -kv[1])[:8]:
            lines.append(f"    {user}: {n}")
        lines.append("")
        lines.append("Full detail: Administration > Data Health and Audit Trail.")
        return "\n".join(lines)
