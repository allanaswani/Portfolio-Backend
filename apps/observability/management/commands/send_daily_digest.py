"""The Daily System Health Report: a short mail with an Excel workbook attached.

Uptime, speed, what broke, what fixed itself and what changed. It goes to the
daily-digest list and the sensitive-change list, because deletions and role
changes are reported here instead of by a mail each.

    0 7 * * * docker exec hf-backend python manage.py send_daily_digest
    manage.py send_daily_digest --dry-run --xlsx /tmp/h.xlsx   # look, send nothing

Unlike the immediate alerts this is sent regardless of state — it is the
"nothing is on fire" message as much as the other kind, and a monitoring system
nobody hears from is one nobody trusts.

The note is deliberately plain ASCII. It is printed to a console by --dry-run,
and a console that cannot encode an em dash should not be able to crash the job
that reports on everything else.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Avg
from django.utils import timezone

from apps.observability import alerts, audit, health, metrics, report_xlsx
from apps.observability.models import AlertState, MonitoredService, ServiceProbe


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
        parser.add_argument("--xlsx", default="",
                            help="with --dry-run, also write the workbook here")

    def handle(self, *args, **options):
        hours = max(1, options["hours"])
        facts = self.gather(hours)
        body = self.note(hours, facts)

        if options["dry_run"]:
            self.stdout.write(body)
            if options["xlsx"]:
                with open(options["xlsx"], "wb") as out:
                    out.write(report_xlsx.build(self.sheets(hours, facts)))
                self.stdout.write(f"Workbook written to {options['xlsx']}")
            return

        today = timezone.localdate()
        count = alerts.send(
            [alerts.AlertRecipient.KIND_DAILY_DIGEST,
             alerts.AlertRecipient.KIND_SENSITIVE_CHANGE],
            f"Daily System Health Report - {today:%d %b %Y}",
            body,
            attachments=[(f"Daily System Health Report - {today:%Y-%m-%d}.xlsx",
                          report_xlsx.build(self.sheets(hours, facts)),
                          report_xlsx.XLSX_MIME)],
        )
        self.stdout.write(f"digest sent to {count} recipient(s)")

    def gather(self, hours):
        since = timezone.now() - timedelta(hours=hours)
        overview = metrics.overview(hours=hours)
        rows = health.table_health()
        problems = [r for r in rows
                    if r["status"] in ("missing", "empty", "stale", "error")]
        changes = audit.feed(since=since, limit=500, with_changes=True)
        notable = [c for c in changes if c["action"] == "deleted"
                   or c["model"] in alerts.SENSITIVE_MODELS]
        fixed = list(AlertState.objects.filter(
            key__startswith=alerts.SELF_FIXED_PREFIX, since__gte=since)
            .order_by("since"))
        return {"since": since, "overview": overview, "rows": rows,
                "problems": problems, "changes": changes, "notable": notable,
                "fixed": fixed}

    def note(self, hours, facts):
        """The mail's text. The detail is in the attachment."""
        overview, problems = facts["overview"], facts["problems"]
        uptime = overview["uptime"]
        lines = ["Dear All,", "",
                 f"Please find attached the Daily System Health Report for the "
                 f"last {hours} hours.", ""]
        lines.append(
            f"Uptime: {uptime['percent']}% ({uptime['downtime_minutes']} minutes "
            f"down)." if uptime.get("measured") else
            "Uptime: not measured - the heartbeat job is not scheduled.")
        lines.append(f"Requests: {overview['requests']:,}, of which "
                     f"{overview['errors']:,} were server errors "
                     f"({overview['error_rate']}%).")
        lines.append(f"Fixed automatically: {len(facts['fixed'])}.")
        lines.append(f"Sensitive changes: {len(facts['notable'])}.")
        lines.append(f"Data feeds needing attention: {len(problems)}.")
        if problems:
            lines += ["", "To look at (the rest are in the attachment):"]
            lines += [f"- {row['table']}: {row['status']}"
                      for row in problems[:5]]
        lines += ["", "Kind Regards,", "Analytics and Business Performance."]
        return "\n".join(lines) + "\n"

    def sheets(self, hours, facts):
        from django.db.models import Count
        from django.db.models.functions import TruncHour

        from apps.observability.models import RequestMetric

        overview, since = facts["overview"], facts["since"]
        uptime = overview["uptime"]
        summary = [
            ("Period (hours)", hours),
            ("Requests served", overview["requests"]),
            ("Server errors", overview["errors"]),
            ("Server error rate %", float(overview["error_rate"]) / 100),
            ("Median response (ms)", overview["p50"]),
            ("95th percentile response (ms)", overview["p95"]),
            ("Active users", overview["active_users"]),
            ("Uptime", f"{uptime['percent']}%" if uptime.get("measured")
             else "not measured - the heartbeat job is not scheduled"),
            ("Minutes down", uptime["downtime_minutes"]
             if uptime.get("measured") else "not measured"),
        ]

        services = []
        for service in MonitoredService.objects.filter(is_active=True):
            probes = ServiceProbe.objects.filter(service=service,
                                                 created_at__gte=since)
            total = probes.count()
            failed = probes.filter(ok=False).count()
            average = probes.filter(ok=True).aggregate(m=Avg("duration_ms"))["m"]
            services.append((service.name, total, failed,
                             (total - failed) / total if total else None,
                             round(average) if average else None))

        errors = RequestMetric.objects.filter(created_at__gte=since,
                                              is_error=True)
        by_path = errors.values("method", "path").annotate(n=Count("id")) \
            .order_by("-n")[:50]
        by_hour = errors.annotate(h=TruncHour("created_at")).values("h") \
            .annotate(n=Count("id")).order_by("h")

        def changed(row):
            return "; ".join(f"{c['field']}: {c['old']} -> {c['new']}"
                             for c in (row.get("changes") or [])[:5])

        return [
            {"title": "Summary", "headers": ["Measure", "Value"], "rows": summary},
            {"title": "Fixed Automatically",
             "headers": ["When", "What was fixed"],
             "rows": [(f.since, f.detail) for f in facts["fixed"]],
             "empty": "Nothing needed fixing."},
            {"title": "Data Feeds",
             "note": "Tables and checks that are missing, empty, stale or failing.",
             "headers": ["Table", "Status", "Rows", "Last refreshed", "Detail"],
             "rows": [(r["table"], r["status"], r.get("rows"),
                       str(r["last_seen"]) if r.get("last_seen") else "never",
                       _plain(r.get("error") or "", 300))
                      for r in facts["problems"]],
             "empty": f"All {len(facts['rows'])} tables are loaded and fresh."},
            {"title": "Other Systems",
             "headers": ["System", "Checks", "Failed", "Reachable %",
                         "Average ms"], "rows": services,
             "empty": "No other system is being watched."},
            {"title": "Errors by Page", "headers": ["Page", "Errors"],
             "rows": [(f"{r['method']} {r['path']}", r["n"]) for r in by_path],
             "empty": "No server errors."},
            {"title": "Errors by Hour", "headers": ["Hour", "Errors"],
             "rows": [(r["h"], r["n"]) for r in by_hour],
             "empty": "No server errors."},
            {"title": "Sensitive Changes",
             "note": "Deletions anywhere, and any change to sales codes, tariffs, "
                     "mappings, profiles and alert settings.",
             "headers": ["When", "Who", "Action", "What", "Record", "Changed"],
             "rows": [(c["when"],
                       c["username"] or "system/job", c["action"],
                       alerts.SENSITIVE_MODELS.get(c["model"], c["model_label"]),
                       str(c["object_label"] or c["object_id"]), changed(c))
                      for c in facts["notable"]],
             "empty": "No sensitive changes."},
        ]
