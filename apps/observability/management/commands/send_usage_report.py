"""The Daily Usage Report: a short mail with an Excel workbook attached.

    0 7 * * * docker exec hf-backend python manage.py send_usage_report
    manage.py send_usage_report --dry-run                    # print, send nothing
    manage.py send_usage_report --dry-run --xlsx /tmp/u.xlsx # and write the file
    manage.py send_usage_report --day 2026-10-28             # a particular day

It answers one question: how are the branches using the tools? So its first
sheet after the summary ranks every branch, including the ones nobody opened
anything in.

Goes to everybody ticked for "Daily usage report" under Administration ->
Alerts, from the same reports address as the other reports.

Two sources, both already recorded:

* the portfolio tool - ``user_activity_events``, a row per page somebody opens;
* Customer 360 - ``observability_external_usage_day``, the per-person daily
  roll-up Customer 360 pushes with its own ``push_usage`` job.

**Who is counted.** Everybody except the group in
:mod:`apps.analytics.exclusions` - the Strategy team, who build and support
these tools, so their clicks say nothing about adoption.

**A person's branch** is, in order: the branch on their profile; the sales
roster's branch for the sales code on their profile; the HR roster's unit for
their address. Each must name one of the bank's branches exactly - nothing is
inferred - and anybody none of them place is counted under "No branch recorded",
outside the ranking.

**The ranking** is over the 7 days ending on the report's day, because one day
is too noisy to rank anybody on: the share of a branch's accounts that opened
either tool, then how many people, then how much they opened.
"""

import datetime
import html as html_module
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

NO_BRANCH = "No branch recorded"
#: Profile branches that are real, but not branches to rank.
NOT_RANKED = {"HEAD OFFICE BRANCH", "HFDI"}
TOP = 10


def _bounds(day):
    """The bank's day, as aware datetimes."""
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    return start, start + datetime.timedelta(days=1)


def _excluded():
    from apps.analytics.exclusions import excluded_usernames

    return excluded_usernames()


def _events(start, end):
    """The usage events the report counts."""
    from apps.analytics.exclusions import excluded_user_ids
    from apps.analytics.models import UserActivityEvent

    return (UserActivityEvent.objects
            .filter(created_at__gte=start, created_at__lt=end)
            .exclude(user_id__in=excluded_user_ids()))


def _external(**filters):
    """Other systems' daily rows the report counts → list."""
    from apps.observability.models import ExternalUsageDay

    excluded = _excluded()
    return [r for r in ExternalUsageDay.objects.filter(**filters)
            if (r.username or "").lower() not in excluded]


def _names():
    from django.contrib.auth import get_user_model

    return {u.username.lower(): (u.get_full_name() or u.username)
            for u in get_user_model().objects.all()}


def _rankable_branches():
    """The bank's branches, as the Users screen spells them."""
    from apps.portfolio.models import BRANCH_CHOICES

    return [value for value, _label in BRANCH_CHOICES
            if value not in NOT_RANKED]


def _a_branch(text):
    """A roster's wording → the Users screen's spelling, or "" if it is not
    exactly one of the bank's branches. Nothing is inferred from a near match."""
    from apps.portfolio.models import BRANCH_CHOICES

    known = {value for value, _label in BRANCH_CHOICES}
    name = " ".join(str(text or "").upper().split())
    if name in known:
        return name
    return f"{name} BRANCH" if f"{name} BRANCH" in known else ""


def _roster_branches():
    """(sales code → branch, address → branch) from the two rosters.

    Each read has its own savepoint: a roster missing from a database must cost
    the report that one fallback, not the report.
    """
    by_code, by_email = {}, {}
    try:
        from apps.staff_management.models import BranchEmployeeDmcData

        with transaction.atomic():
            for code, branch in (BranchEmployeeDmcData.objects
                                 .values_list("sales_code", "staff_branch")):
                name = _a_branch(branch)
                if code and name:
                    by_code[str(code).strip().upper()] = name
    except Exception:  # noqa: BLE001 - see the docstring
        pass
    try:
        from apps.staff_management.models import StaffEmployeeData

        with transaction.atomic():
            for email, unit in (StaffEmployeeData.objects
                                .filter(is_active=True)
                                .values_list("staff_email", "staff_unit")):
                name = _a_branch(unit)
                local = str(email or "").strip().lower().split("@")[0]
                if local and name:
                    # The name before the @, since the bank's addresses moved
                    # between two domains. Two people on one name place neither.
                    by_email[local] = (None if local in by_email
                                       and by_email[local] != name else name)
    except Exception:  # noqa: BLE001 - see the docstring
        pass
    return by_code, by_email


def _branches():
    """username (lower) → the person's branch - see the module docstring."""
    from django.contrib.auth import get_user_model

    from apps.portfolio.models import Profile

    by_code, by_email = _roster_branches()
    profiles = {p["user_id"]: p for p in
                Profile.objects.values("user_id", "branch", "sales_code")}
    out = {}
    for user in get_user_model().objects.only("id", "username", "email"):
        profile = profiles.get(user.id, {})
        local = (user.email or "").strip().lower().split("@")[0]
        out[user.username.lower()] = (
            (profile.get("branch") or "").strip()
            or by_code.get((profile.get("sales_code") or "").strip().upper())
            or by_email.get(local)
            or by_email.get(user.username.lower())
            or NO_BRANCH)
    return out


def _accounts():
    """Active accounts the report counts → [User]."""
    from django.contrib.auth import get_user_model

    excluded = _excluded()
    return [u for u in get_user_model().objects.filter(is_active=True)
            if u.username.lower() not in excluded]


def portfolio_week(day):
    """Everybody's portfolio tool use over the 7 days ending ``day`` →
    {username: {"pages", "days": set, "today"}}."""
    from django.db.models import Count
    from django.db.models.functions import TruncDate

    start, _ = _bounds(day - datetime.timedelta(days=6))
    _, end = _bounds(day)
    people = defaultdict(lambda: {"pages": 0, "days": set(), "today": 0})
    for row in (_events(start, end)
                .annotate(d=TruncDate("created_at"))
                .values("user__username", "d").annotate(n=Count("id"))):
        who = people[row["user__username"].lower()]
        who["pages"] += row["n"]
        who["days"].add(row["d"])
        if row["d"] == day:
            who["today"] += row["n"]
    return people


def external_week(day):
    """Each other system over the 7 days ending ``day`` →
    {source: {username: {"profiles", "searches", "minutes", "days", "today"}}}."""
    first = day - datetime.timedelta(days=6)
    out = defaultdict(lambda: defaultdict(lambda: {
        "profiles": 0, "searches": 0, "minutes": 0, "days": set(), "today": None}))
    for row in _external(day__gte=first, day__lte=day):
        who = out[row.source][row.username.lower()]
        who["profiles"] += row.customer_views
        who["searches"] += row.searches
        who["minutes"] += row.active_minutes
        who["days"].add(row.day)
        if row.day == day:
            who["today"] = row
    return out


def branch_ranking(day):
    """Every branch, best first, on the 7 days ending ``day`` → [dict].

    A branch nobody used is on the list, at the bottom - that is the branch the
    report exists to find. Rank is its position; there are no shared ranks,
    because the ties are broken on what people did.
    """
    branches = _branches()
    portfolio = portfolio_week(day)
    c360 = next((people for source, people in external_week(day).items()
                 if "360" in source), {})

    accounts = Counter(branches.get(u.username.lower(), NO_BRANCH)
                       for u in _accounts())
    rows = {name: {"branch": name, "accounts": accounts.get(name, 0),
                   "active": set(), "portfolio": set(), "c360": set(),
                   "pages": 0, "profiles": 0, "today": set()}
            for name in _rankable_branches()}
    for username, who in portfolio.items():
        row = rows.get(branches.get(username, NO_BRANCH))
        if row is not None:
            row["active"].add(username)
            row["portfolio"].add(username)
            row["pages"] += who["pages"]
            if who["today"]:
                row["today"].add(username)
    for username, who in c360.items():
        row = rows.get(branches.get(username, NO_BRANCH))
        if row is not None:
            row["active"].add(username)
            row["c360"].add(username)
            row["profiles"] += who["profiles"]
            if who["today"] is not None:
                row["today"].add(username)

    def share(row):
        return len(row["active"]) / row["accounts"] if row["accounts"] else 0.0

    ordered = sorted(rows.values(),
                     key=lambda r: (-share(r), -len(r["active"]),
                                    -(r["pages"] + r["profiles"]), r["branch"]))
    return [{"rank": rank, "branch": r["branch"], "accounts": r["accounts"],
             "active": len(r["active"]), "share": share(r),
             "portfolio_people": len(r["portfolio"]), "pages": r["pages"],
             "c360_people": len(r["c360"]), "profiles": r["profiles"],
             "yesterday": len(r["today"])}
            for rank, r in enumerate(ordered, 1)]


def portfolio_day(day):
    """The portfolio tool on one day → dict."""
    from django.db.models import Count

    start, end = _bounds(day)
    events = _events(start, end)
    by_user = list(events.values("user__username").annotate(views=Count("id"))
                   .order_by("-views"))
    areas = list(events.values("path")
                 .annotate(views=Count("id"),
                           users=Count("user", distinct=True))
                 .order_by("-views"))
    return {
        "users": len(by_user),
        "accounts": len(_accounts()),
        "views": sum(r["views"] for r in by_user),
        "top_areas": [(r["path"], r["users"], r["views"]) for r in areas],
    }


def last_reported(source):
    from apps.observability.models import ExternalUsageDay

    return (ExternalUsageDay.objects.filter(source=source)
            .order_by("-reported_at")
            .values_list("reported_at", flat=True).first())


def _sources():
    from apps.observability.models import ExternalUsageDay

    return sorted(set(ExternalUsageDay.objects.values_list("source", flat=True)))


def _title(source):
    return "Customer 360" if "360" in source else source


def _source_status(source, day):
    """One line on whether this system reported the day. A stopped push and a
    quiet day must not both read as nought."""
    rows = _external(source=source, day=day)
    if rows:
        return (f"{len(rows)} people, "
                f"{sum(r.customer_views for r in rows):,} profiles opened")
    last = last_reported(source)
    if not last:
        return "It has never reported."
    return (f"Nothing reported for {day:%d %b %Y}. Last report received "
            f"{timezone.localtime(last):%d %b %Y %H:%M}.")


def build_sheets(day):
    """The workbook's sheets for the day → [sheet]."""
    names, branches = _names(), _branches()
    day_figures = portfolio_day(day)
    ranking = branch_ranking(day)
    portfolio = portfolio_week(day)
    external = external_week(day)
    sources = _sources()
    c360_source = next((s for s in sources if "360" in s), None)
    c360 = external.get(c360_source, {}) if c360_source else {}
    used = {u for u in portfolio} | {u for u in c360}
    excluded_count = len(_excluded())

    summary = [
        ("Report day", f"{day:%A %d %B %Y}"),
        ("Active accounts counted", day_figures["accounts"]),
        ("Used the portfolio tool on the day", day_figures["users"]),
        ("Portfolio pages opened on the day", day_figures["views"]),
        ("Used either tool in the last 7 days", len(used)),
    ]
    for source in sources:
        summary.append((f"{_title(source)} on the day",
                        _source_status(source, day)))
    if not sources:
        summary.append(("Customer 360 on the day", "It has never reported."))
    summary.append(("Left out: Strategy team accounts", excluded_count))

    people = []
    for username in used:
        p = portfolio.get(username, {"pages": 0, "days": set(), "today": 0})
        c = c360.get(username, {"profiles": 0, "searches": 0, "minutes": 0,
                                "days": set(), "today": None})
        people.append((names.get(username, username),
                       branches.get(username, NO_BRANCH),
                       len(p["days"] | c["days"]), p["pages"], p["today"],
                       c["profiles"], c["searches"], c["minutes"],
                       c["today"].customer_views if c["today"] else 0))
    people.sort(key=lambda r: (-r[2], -(r[3] + r[5]), r[0]))

    idle = sorted(
        ((u.get_full_name() or u.username,
          branches.get(u.username.lower(), NO_BRANCH), u.last_login)
         for u in _accounts() if u.username.lower() not in used),
        key=lambda r: (r[1], r[0]))

    calendar = []
    for back in range(6, -1, -1):
        when = day - datetime.timedelta(days=back)
        in_portfolio = [w for w in portfolio.values() if when in w["days"]]
        rows = _external(source=c360_source, day=when) if c360_source else []
        calendar.append((when, len(in_portfolio), len(rows),
                         sum(r.customer_views for r in rows),
                         sum(r.searches for r in rows),
                         sum(r.active_minutes for r in rows)))

    sheets = [
        {"title": "Summary", "headers": ["Measure", "Value"], "rows": summary},
        {"title": "Branch Ranking",
         "note": "Last 7 days. Ranked on the share of the branch's accounts "
                 "that opened either tool, then people, then volume.",
         "headers": ["Rank", "Branch", "Accounts", "Active people", "Active %",
                     "Portfolio people", "Portfolio pages", "C360 people",
                     "C360 profiles", "Active on report day"],
         "rows": [(r["rank"], r["branch"], r["accounts"], r["active"],
                   float(r["share"]), r["portfolio_people"], r["pages"],
                   r["c360_people"], r["profiles"], r["yesterday"])
                  for r in ranking]},
        {"title": "People",
         "note": "Everybody who opened either tool in the last 7 days.",
         "headers": ["Person", "Branch", "Days active (7d)", "Portfolio pages (7d)",
                     "Portfolio pages (day)", "C360 profiles (7d)",
                     "C360 searches (7d)", "C360 minutes (7d)",
                     "C360 profiles (day)"],
         "rows": people, "empty": "Nobody used either tool."},
        {"title": "Not Using",
         "note": "Active accounts that opened neither tool in the last 7 days.",
         "headers": ["Person", "Branch", "Last login"], "rows": idle,
         "empty": "Every account used a tool this week."},
        {"title": "Portfolio Areas",
         "note": "The areas of the portfolio tool people opened on the day.",
         "headers": ["Area", "People", "Pages"],
         "rows": day_figures["top_areas"],
         "empty": "Nobody used the portfolio tool on the day."},
        {"title": "Last 7 Days",
         "headers": ["Day", "Portfolio people", "C360 people", "C360 profiles",
                     "C360 searches", "C360 minutes"], "rows": calendar},
    ]

    for source in sources:
        rows = sorted(_external(source=source, day=day),
                      key=lambda r: (-r.customer_views, -r.searches))
        features = Counter()
        for row in rows:
            for name, count in (row.features or {}).items():
                if isinstance(count, (int, float)):
                    features[name] += count
        title = _title(source)
        sheets.append({
            "title": f"{title} People"[:31],
            "note": f"{title} on the day. {_source_status(source, day)}",
            "headers": ["Person", "Branch", "Profiles", "Different customers",
                        "Searches", "Exports", "Minutes", "Sessions",
                        "First seen", "Last seen"],
            "rows": [(names.get(r.username.lower(), r.username),
                      branches.get(r.username.lower(), NO_BRANCH),
                      r.customer_views, r.distinct_customers, r.searches,
                      r.exports, r.active_minutes, r.sessions, r.first_at,
                      r.last_at) for r in rows],
            "empty": "Nothing reported for the day."})
        sheets.append({
            "title": f"{title} Features"[:31],
            "headers": ["Feature", "Uses"],
            "rows": [(str(n).replace("_", " ").capitalize(), int(c))
                     for n, c in features.most_common()],
            "empty": "Nothing reported for the day."})
    return sheets


def _highlights(day):
    """The note's few lines: where the branches stand this week."""
    ranking = branch_ranking(day)
    with_accounts = [r for r in ranking if r["accounts"]]
    if not with_accounts:
        return []

    def line(r):
        return (f"{r['branch']} ({r['active']} of {r['accounts']} accounts, "
                f"{r['share']:.0%})")

    top = with_accounts[:3]
    bottom = [r for r in with_accounts[-3:] if r not in top]
    lines = ["Most used this week: " + "; ".join(line(r) for r in top) + "."]
    if bottom:
        lines.append("Least used: " + "; ".join(line(r) for r in bottom) + ".")
    return lines


def build(day):
    """The mail's text. The figures are in the attachment."""
    p = portfolio_day(day)
    lines = [
        "Dear All,",
        "",
        f"Please find attached the Daily Usage Report for {day:%A %d %B %Y}.",
        "",
        f"{p['users']} of {p['accounts']} accounts used the portfolio tool, "
        f"opening {p['views']:,} pages.",
    ]
    lines += _highlights(day)
    lines += ["", "The branch ranking, the people and those not using the "
                  "tools are in the attached sheets. The Strategy team is not "
                  "counted.", "", "Kind Regards,",
              "Analytics and Business Performance."]
    return "\n".join(lines) + "\n"


def build_html(day):
    """The same note as a mail client shows it: the bank's report note, no
    dashboards in the body."""
    paragraphs, current = [], []
    for line in build(day).splitlines():
        if line:
            current.append(html_module.escape(line))
        elif current:
            paragraphs.append("<br/>".join(current))
            current = []
    if current:
        paragraphs.append("<br/>".join(current))
    body = "".join(f'<p style="margin:0 0 14px">{p}</p>' for p in paragraphs)
    return ('<!DOCTYPE html><html><body style="font-family:Calibri,Arial,'
            f'sans-serif;font-size:14px;color:#1F2D33">{body}</body></html>')


class Command(BaseCommand):
    help = ("E-mail yesterday's use of the portfolio tool and Customer 360 to "
            "the usage-report recipients, with the figures as an Excel file.")

    def add_arguments(self, parser):
        parser.add_argument("--day", default="",
                            help="YYYY-MM-DD; default yesterday (Nairobi)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--xlsx", default="",
                            help="with --dry-run, also write the workbook to "
                                 "this file to look at")

    def handle(self, *args, **options):
        from apps.observability import alerts, report_xlsx

        if options["day"]:
            try:
                day = datetime.datetime.strptime(options["day"],
                                                 "%Y-%m-%d").date()
            except ValueError:
                raise CommandError(f"{options['day']!r} is not YYYY-MM-DD")
        else:
            day = timezone.localdate() - datetime.timedelta(days=1)

        body = build(day)
        workbook = report_xlsx.build(build_sheets(day))
        if options["dry_run"]:
            self.stdout.write(body)
            if options["xlsx"]:
                with open(options["xlsx"], "wb") as out:
                    out.write(workbook)
                self.stdout.write(f"Workbook written to {options['xlsx']}")
            return
        count = alerts.send(
            alerts.AlertRecipient.KIND_USAGE_REPORT,
            f"Daily Usage Report - {day:%d %b %Y}", body, html=build_html(day),
            attachments=[(f"Daily Usage Report - {day:%Y-%m-%d}.xlsx", workbook,
                          report_xlsx.XLSX_MIME)])
        self.stdout.write(f"usage report sent to {count} recipient(s)")
