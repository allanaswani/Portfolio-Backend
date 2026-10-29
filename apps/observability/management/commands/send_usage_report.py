"""Who used the portfolio tool and Customer 360 yesterday - one e-mail a day.

    0 7 * * * docker exec hf-backend python manage.py send_usage_report
    manage.py send_usage_report --dry-run          # print it, send nothing
    manage.py send_usage_report --day 2026-10-28   # a particular day

Goes to everybody ticked for "Daily usage report" under Administration ->
Alerts, from the same reports address as the other reports.

Two sources, both already recorded:

* the portfolio tool - ``user_activity_events``, a row per page somebody opens;
* Customer 360 - ``observability_external_usage_day``, the per-person daily
  roll-up Customer 360 pushes with its own ``push_usage`` job.

When Customer 360 reported nothing for the day, the report says when it last
reported, rather than printing zeros: a stopped push and a quiet day look the
same as a number, and are not the same thing.

Plain ASCII, like the daily digest - it is printed to a console by --dry-run.
"""

import datetime
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

TOP = 10


def _plain(text, limit=60):
    flat = " ".join(str(text or "").split())
    flat = flat.replace("—", "-").replace("–", "-")
    flat = flat.encode("ascii", "replace").decode("ascii")
    return flat[: limit - 3] + "..." if len(flat) > limit else flat


def _bounds(day):
    """The bank's day, as aware datetimes."""
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    return start, start + datetime.timedelta(days=1)


def _names():
    from django.contrib.auth import get_user_model

    return {u.username.lower(): (u.get_full_name() or u.username)
            for u in get_user_model().objects.all()}


def portfolio_day(day):
    """The portfolio tool on one day → dict."""
    from django.contrib.auth import get_user_model
    from django.db.models import Count

    from apps.analytics.models import UserActivityEvent

    start, end = _bounds(day)
    events = UserActivityEvent.objects.filter(created_at__gte=start,
                                              created_at__lt=end)
    by_user = list(events.values("user__username", "user__first_name",
                                 "user__last_name")
                   .annotate(views=Count("id")).order_by("-views"))
    areas = list(events.values("path")
                 .annotate(views=Count("id"),
                           users=Count("user", distinct=True))
                 .order_by("-views")[:TOP])
    return {
        "users": len(by_user),
        "accounts": get_user_model().objects.filter(is_active=True).count(),
        "views": sum(r["views"] for r in by_user),
        "top_users": [
            (" ".join(p for p in (r["user__first_name"], r["user__last_name"])
                      if p).strip() or r["user__username"], r["views"])
            for r in by_user[:TOP]],
        "top_areas": [(r["path"], r["users"], r["views"]) for r in areas],
    }


def external_day(day):
    """Every other system's usage on one day → {source: dict}."""
    from apps.observability.models import ExternalUsageDay

    out = {}
    names = _names()
    sources = set(ExternalUsageDay.objects.values_list("source", flat=True))
    for source in sorted(sources):
        rows = list(ExternalUsageDay.objects.filter(source=source, day=day)
                    .order_by("-customer_views", "-requests"))
        features = Counter()
        for r in rows:
            for name, count in (r.features or {}).items():
                if isinstance(count, (int, float)):
                    features[name] += count
        last = (ExternalUsageDay.objects.filter(source=source)
                .order_by("-reported_at")
                .values_list("reported_at", flat=True).first())
        out[source] = {
            "users": len(rows),
            "customer_views": sum(r.customer_views for r in rows),
            "distinct_customers": sum(r.distinct_customers for r in rows),
            "searches": sum(r.searches for r in rows),
            "exports": sum(r.exports for r in rows),
            "minutes": sum(r.active_minutes for r in rows),
            "top_users": [(names.get(r.username.lower(), r.username),
                           r.customer_views, r.searches, r.active_minutes)
                          for r in rows[:TOP]],
            "top_features": features.most_common(TOP),
            "last_reported": last,
        }
    return out


def week(day):
    """Daily active people, both systems, for the 7 days ending ``day``."""
    from apps.analytics.models import UserActivityEvent
    from apps.observability.models import ExternalUsageDay

    first = day - datetime.timedelta(days=6)
    start, _ = _bounds(first)
    _, end = _bounds(day)
    portfolio = defaultdict(set)
    for user_id, at in (UserActivityEvent.objects
                        .filter(created_at__gte=start, created_at__lt=end)
                        .values_list("user_id", "created_at")):
        portfolio[timezone.localtime(at).date()].add(user_id)
    external = defaultdict(lambda: defaultdict(int))
    for source, d in (ExternalUsageDay.objects
                      .filter(day__gte=first, day__lte=day)
                      .values_list("source", "day")):
        external[source][d] += 1
    days = [first + datetime.timedelta(days=i) for i in range(7)]
    return days, {d: len(portfolio[d]) for d in days}, external


def build(day):
    p = portfolio_day(day)
    lines = [f"Daily usage - {day:%A %d %b %Y}", "=" * 46, ""]

    lines += [
        "PORTFOLIO TOOL",
        f"  People who used it : {p['users']} of {p['accounts']} active "
        f"accounts",
        f"  Pages opened       : {p['views']:,}",
    ]
    if p["top_areas"]:
        lines += ["", "  Most used areas            people  pages"]
        lines += [f"    {_plain(path, 26):26} {users:6}  {views:5}"
                  for path, users, views in p["top_areas"]]
    if p["top_users"]:
        lines += ["", "  Most active people                 pages"]
        lines += [f"    {_plain(name, 32):32} {views:5}"
                  for name, views in p["top_users"]]
    lines.append("")

    external = external_day(day)
    if not external:
        lines += ["CUSTOMER 360",
                  "  Nothing has ever been reported. Customer 360's push_usage",
                  "  job sends this; it is not running, or not yet set up.", ""]
    for source, x in external.items():
        title = ("CUSTOMER 360" if "360" in source
                 else _plain(source, 40).upper())
        lines.append(title)
        if not x["users"]:
            last = x["last_reported"]
            lines += [
                f"  Nothing reported for {day:%d %b %Y}.",
                (f"  Last report received: "
                 f"{timezone.localtime(last):%d %b %Y %H:%M}. If that is not "
                 f"recent, its push_usage job has stopped - this is not the "
                 f"same as nobody using it." if last else
                 "  It has never reported."),
                ""]
            continue
        lines += [
            f"  People who used it   : {x['users']}",
            f"  Customer profiles    : {x['customer_views']:,} opened, "
            f"{x['distinct_customers']:,} different customers",
            f"  Searches             : {x['searches']:,}",
            f"  Exports              : {x['exports']:,}",
            f"  Time in it           : {x['minutes']:,} minutes",
        ]
        if x["top_features"]:
            lines += ["", "  Most used features"]
            lines += [f"    {_plain(name, 30):30} {count:6}"
                      for name, count in x["top_features"]]
        if x["top_users"]:
            lines += ["", "  Most active people          profiles  searches  "
                          "minutes"]
            lines += [f"    {_plain(name, 26):26} {views:8} {searches:9} "
                      f"{minutes:8}"
                      for name, views, searches, minutes in x["top_users"]]
        lines.append("")

    days, portfolio, others = week(day)
    header = "  Day          Portfolio"
    for source in sorted(others):
        header += f"  {('C360' if '360' in source else source[:8]):>9}"
    lines += ["LAST 7 DAYS - people each day", header]
    for d in days:
        row = f"  {d:%a %d %b}   {portfolio[d]:9}"
        for source in sorted(others):
            row += f"  {others[source][d]:9}"
        lines.append(row)
    return "\n".join(lines) + "\n"


class Command(BaseCommand):
    help = ("E-mail yesterday's use of the portfolio tool and Customer 360 to "
            "the usage-report recipients.")

    def add_arguments(self, parser):
        parser.add_argument("--day", default="",
                            help="YYYY-MM-DD; default yesterday (Nairobi)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        from apps.observability import alerts

        if options["day"]:
            try:
                day = datetime.datetime.strptime(options["day"],
                                                 "%Y-%m-%d").date()
            except ValueError:
                raise CommandError(f"{options['day']!r} is not YYYY-MM-DD")
        else:
            day = timezone.localdate() - datetime.timedelta(days=1)

        body = build(day)
        if options["dry_run"]:
            self.stdout.write(body)
            return
        count = alerts.send(alerts.AlertRecipient.KIND_USAGE_REPORT,
                            f"Daily usage - {day:%d %b %Y}", body)
        self.stdout.write(f"usage report sent to {count} recipient(s)")
