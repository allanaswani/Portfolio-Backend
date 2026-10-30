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

Each person's branch is the one on their portfolio profile (Administration ->
Users). Head office staff mostly have none, and are counted under
"No branch on profile" rather than guessed at.

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
NO_BRANCH = "No branch on profile"


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


def _branches():
    """username (lower) -> the branch on their profile."""
    from apps.portfolio.models import Profile

    return {u.lower(): (b or "").strip() or NO_BRANCH
            for u, b in Profile.objects.values_list("user__username",
                                                    "branch")}


def _branch_table(rows):
    """[(username, amount)] -> [(branch, people, amount)], busiest first."""
    branches = _branches()
    people, amount = defaultdict(set), Counter()
    for username, value in rows:
        branch = branches.get((username or "").lower(), NO_BRANCH)
        people[branch].add((username or "").lower())
        amount[branch] += value
    return sorted(((b, len(people[b]), amount[b]) for b in people),
                  key=lambda r: (-r[1], -r[2], r[0]))


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
    branches = _branches()
    return {
        "users": len(by_user),
        "accounts": get_user_model().objects.filter(is_active=True).count(),
        "views": sum(r["views"] for r in by_user),
        "top_users": [
            (" ".join(p for p in (r["user__first_name"], r["user__last_name"])
                      if p).strip() or r["user__username"], r["views"],
             branches.get(r["user__username"].lower(), NO_BRANCH))
            for r in by_user[:TOP]],
        "top_areas": [(r["path"], r["users"], r["views"]) for r in areas],
        "branches": _branch_table((r["user__username"], r["views"])
                                  for r in by_user),
    }


def external_day(day):
    """Every other system's usage on one day → {source: dict}."""
    from apps.observability.models import ExternalUsageDay

    out = {}
    names = _names()
    branches = _branches()
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
                           r.customer_views, r.searches, r.active_minutes,
                           branches.get(r.username.lower(), NO_BRANCH))
                          for r in rows[:TOP]],
            "branches": _branch_table((r.username, r.customer_views)
                                      for r in rows),
            "top_features": features.most_common(TOP),
            "last_reported": last,
            "sessions": sum(r.sessions for r in rows),
            "page_views": sum(r.page_views for r in rows),
            "errors": sum(r.errors for r in rows),
            # Everybody, not the top ten - the HTML report lists them all.
            "people": [{
                "name": names.get(r.username.lower(), r.username),
                "username": r.username.lower(),
                "branch": branches.get(r.username.lower(), NO_BRANCH),
                "profiles": r.customer_views,
                "customers": r.distinct_customers,
                "searches": r.searches,
                "exports": r.exports,
                "minutes": r.active_minutes,
                "sessions": r.sessions,
                "first": timezone.localtime(r.first_at) if r.first_at else None,
                "last": timezone.localtime(r.last_at) if r.last_at else None,
            } for r in rows],
        }
    return out


def external_week(day):
    """Each other system over the 7 days ending ``day``, a row per day →
    {source: {"days": [{day, people, profiles, searches, minutes}],
    "people": distinct people in the week}}."""
    from django.db.models import Count, Sum

    from apps.observability.models import ExternalUsageDay

    first = day - datetime.timedelta(days=6)
    days = [first + datetime.timedelta(days=i) for i in range(7)]
    rows = (ExternalUsageDay.objects.filter(day__gte=first, day__lte=day)
            .values("source", "day")
            .annotate(people=Count("id"), profiles=Sum("customer_views"),
                      searches=Sum("searches"), minutes=Sum("active_minutes")))
    by = defaultdict(dict)
    for r in rows:
        by[r["source"]][r["day"]] = r
    distinct = dict(ExternalUsageDay.objects
                    .filter(day__gte=first, day__lte=day)
                    .values("source")
                    .annotate(n=Count("username", distinct=True))
                    .values_list("source", "n"))
    out = {}
    for source, per_day in by.items():
        out[source] = {
            "days": [{"day": d,
                      "people": per_day.get(d, {}).get("people") or 0,
                      "profiles": per_day.get(d, {}).get("profiles") or 0,
                      "searches": per_day.get(d, {}).get("searches") or 0,
                      "minutes": per_day.get(d, {}).get("minutes") or 0}
                     for d in days],
            "people": distinct.get(source, 0),
        }
    return out


def portfolio_usernames(day):
    """Lower-cased usernames who opened the portfolio tool on ``day``, with
    their pages → {username: pages}."""
    from django.db.models import Count

    from apps.analytics.models import UserActivityEvent

    start, end = _bounds(day)
    return {(r["user__username"] or "").lower(): r["views"]
            for r in (UserActivityEvent.objects
                      .filter(created_at__gte=start, created_at__lt=end)
                      .values("user__username").annotate(views=Count("id")))}


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


def week_leaders(day):
    """The 7 days ending ``day``: who used each system most, and where.

    People are ranked by the days they came back, then by volume - somebody
    in it every day matters more than one long afternoon.
    """
    from django.db.models import Count
    from django.db.models.functions import TruncDate

    from apps.analytics.models import UserActivityEvent
    from apps.observability.models import ExternalUsageDay

    first = day - datetime.timedelta(days=6)
    start, _ = _bounds(first)
    _, end = _bounds(day)
    names, branches = _names(), _branches()
    out = {}

    per_day = (UserActivityEvent.objects
               .filter(created_at__gte=start, created_at__lt=end)
               .annotate(d=TruncDate("created_at"))
               .values("user__username", "d").annotate(views=Count("id")))
    days, volume = defaultdict(set), Counter()
    for r in per_day:
        days[r["user__username"]].add(r["d"])
        volume[r["user__username"]] += r["views"]
    out["Portfolio tool"] = days, volume

    for source in sorted(set(ExternalUsageDay.objects
                             .values_list("source", flat=True))):
        days, volume = defaultdict(set), Counter()
        for username, d, views in (ExternalUsageDay.objects
                                   .filter(source=source, day__gte=first,
                                           day__lte=day)
                                   .values_list("username", "day",
                                                "customer_views")):
            days[username].add(d)
            volume[username] += views
        title = "Customer 360" if "360" in source else _plain(source, 30)
        out[title] = days, volume

    leaders = {}
    for title, (days, volume) in out.items():
        people = sorted(days, key=lambda u: (-len(days[u]), -volume[u], u))
        leaders[title] = {
            "people": [(names.get(u.lower(), u),
                        branches.get(u.lower(), NO_BRANCH),
                        len(days[u]), volume[u]) for u in people[:TOP]],
            "branches": _branch_table((u, volume[u]) for u in days),
        }
    return leaders


def _branch_lines(rows, unit):
    lines = [f"  By branch                          people  {unit:>8}"]
    lines += [f"    {_plain(branch, 32):32} {people:6}  {amount:8,}"
              for branch, people, amount in rows]
    return lines


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
    if p["branches"]:
        lines += [""] + _branch_lines(p["branches"], "pages")
    if p["top_users"]:
        lines += ["", "  Most active people               branch"
                      "                 pages"]
        lines += [f"    {_plain(name, 28):28} {_plain(branch, 22):22} "
                  f"{views:5}"
                  for name, views, branch in p["top_users"]]
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
        if x["branches"]:
            lines += [""] + _branch_lines(x["branches"], "profiles")
        if x["top_users"]:
            lines += ["", "  Most active people       branch               "
                          "profiles  searches  minutes"]
            lines += [f"    {_plain(name, 22):22} {_plain(branch, 20):20} "
                      f"{views:8} {searches:9} {minutes:8}"
                      for name, views, searches, minutes, branch
                      in x["top_users"]]
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

    for title, x in week_leaders(day).items():
        unit = "pages" if title == "Portfolio tool" else "profiles"
        lines += ["", f"LAST 7 DAYS - {title.upper()} - who uses it most"]
        if not x["people"]:
            lines.append("  Nobody in the last 7 days.")
            continue
        lines.append(f"  Person                   branch               "
                     f"days  {unit:>8}")
        lines += [f"    {_plain(name, 22):22} {_plain(branch, 20):20} "
                  f"{active:4}  {amount:8,}"
                  for name, branch, active, amount in x["people"]]
        lines += [""] + _branch_lines(x["branches"][:TOP], unit)
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# The HTML part
# ─────────────────────────────────────────────────────────────────────────────
#
# The plain text above stays as the text part (and what --dry-run prints). This
# is the part a mail client shows. Mail clients - Outlook above all - ignore
# stylesheets, flexbox and most of CSS, so it is tables and inline styles only,
# and every bar is a table cell with a percentage width.

TEAL, TEAL_DARK, C360 = "#1996A9", "#0B5C6B", "#12A594"
INK, MUTED, LINE, WASH = "#1F2D33", "#6B7C83", "#E3ECEF", "#F4F8F9"
FONT = "Segoe UI, Arial, Helvetica, sans-serif"


def _e(value):
    import html

    return html.escape(str(value if value is not None else ""))


def _bar(value, top, colour, width=None):
    share = 0 if not top else max(0, min(100, round(100 * value / top)))
    filled = (f'<td width="{share}%" style="background:{colour};height:8px;'
              f'font-size:0;line-height:0;border-radius:4px">&nbsp;</td>'
              if share else "")
    rest = (f'<td style="height:8px;font-size:0;line-height:0">&nbsp;</td>'
            if share < 100 else "")
    # Inside a table column a bar has no width of its own to fill, so the
    # week tables give it one.
    size = f'{width}' if width else "100%"
    return (f'<table width="{size}" cellpadding="0" cellspacing="0" '
            f'style="background:{WASH};border-radius:4px;width:{size}'
            f'{"px" if width else ""}"><tr>{filled}{rest}</tr></table>')


def _tiles(items, colour):
    """[(figure, label, note)] → one row of KPI tiles."""
    cells = "".join(
        f'<td width="{100 // len(items)}%" valign="top" style="padding:6px">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="background:'
        f'#FFFFFF;border:1px solid {LINE};border-top:3px solid {colour};'
        f'border-radius:6px"><tr><td style="padding:12px 14px">'
        f'<div style="font:700 22px {FONT};color:{INK}">{_e(figure)}</div>'
        f'<div style="font:600 11px {FONT};color:{MUTED};text-transform:'
        f'uppercase;letter-spacing:.4px;padding-top:2px">{_e(label)}</div>'
        + (f'<div style="font:12px {FONT};color:{MUTED};padding-top:4px">'
           f'{_e(note)}</div>' if note else "")
        + '</td></tr></table></td>'
        for figure, label, note in items)
    return (f'<table width="100%" cellpadding="0" cellspacing="0"><tr>{cells}'
            f'</tr></table>')


def _heading(text, colour, note=""):
    return (f'<tr><td style="padding:26px 24px 8px"><div style="font:700 15px '
            f'{FONT};color:{colour};border-left:4px solid {colour};'
            f'padding-left:10px">{_e(text)}</div>'
            + (f'<div style="font:12px {FONT};color:{MUTED};padding:4px 0 0 '
               f'14px">{_e(note)}</div>' if note else "")
            + '</td></tr>')


def _table(headers, rows, aligns=None):
    """A plain data table. ``rows`` cells are already-escaped HTML."""
    aligns = aligns or ["left"] + ["right"] * (len(headers) - 1)
    head = "".join(
        f'<th align="{a}" style="font:600 11px {FONT};color:{MUTED};'
        f'text-transform:uppercase;letter-spacing:.3px;padding:8px 10px;'
        f'border-bottom:2px solid {LINE}">{_e(h)}</th>'
        for h, a in zip(headers, aligns))
    body = "".join(
        "<tr>" + "".join(
            f'<td align="{a}" style="font:13px {FONT};color:{INK};padding:7px '
            f'10px;border-bottom:1px solid {LINE}">{c}</td>'
            for c, a in zip(row, aligns)) + "</tr>"
        for row in rows)
    return (f'<tr><td style="padding:0 24px"><table width="100%" '
            f'cellpadding="0" cellspacing="0">{head}{body}</table></td></tr>')


def _bars(rows, colour, unit):
    """[(label, sub, value)] → a ranked bar list."""
    top = max((v for _, _, v in rows), default=0)
    out = "".join(
        f'<tr><td width="38%" style="font:13px {FONT};color:{INK};padding:5px '
        f'10px 5px 0">{_e(label)}'
        + (f'<div style="font:11px {FONT};color:{MUTED}">{_e(sub)}</div>'
           if sub else "")
        + f'</td><td style="padding:5px 0">{_bar(value, top, colour)}</td>'
        f'<td width="70" align="right" style="font:600 13px {FONT};color:{INK};'
        f'padding:5px 0 5px 10px">{value:,}<span style="font:11px {FONT};'
        f'color:{MUTED}"> {_e(unit)}</span></td></tr>'
        for label, sub, value in rows)
    return (f'<tr><td style="padding:0 24px"><table width="100%" '
            f'cellpadding="0" cellspacing="0">{out}</table></td></tr>')


def _feature(name):
    return str(name or "").replace("_", " ").capitalize()


def build_html(day):
    """The same report as :func:`build`, laid out for a mail client."""
    p = portfolio_day(day)
    external = external_day(day)
    weekly = external_week(day)
    days, portfolio_week, _ = week(day)
    on_portfolio = portfolio_usernames(day)
    names, branches = _names(), _branches()

    c360_key = next((s for s in external if "360" in s), None)
    x = external.get(c360_key) if c360_key else None
    rows = []

    # ── header band ────────────────────────────────────────────────────────
    rows.append(
        f'<tr><td style="background:{TEAL_DARK};padding:22px 24px">'
        f'<div style="font:800 22px {FONT};color:#FFFFFF;letter-spacing:.5px">'
        f'HFCB <span style="font-weight:400;color:#BFE6EC">create great</span>'
        f'</div><div style="font:600 13px {FONT};color:#BFE6EC;padding-top:4px">'
        f'Daily usage &middot; {day:%A %d %B %Y}</div></td></tr>')

    # ── the day at a glance ───────────────────────────────────────────────
    c360_users = x["users"] if x else 0
    reach = (f"{round(100 * c360_users / p['users'])}% of portfolio users"
             if p["users"] else "")
    rows.append(
        '<tr><td style="padding:18px 18px 0">'
        + _tiles([
            (c360_users, "Customer 360 users", reach),
            (f"{x['customer_views']:,}" if x else 0, "Profiles opened",
             f"{x['distinct_customers']:,} different customers" if x else ""),
            (f"{x['searches']:,}" if x else 0, "C360 searches",
             f"{x['minutes']:,} minutes in it" if x else ""),
            (p["users"], "Portfolio tool users",
             f"{p['views']:,} pages, of {p['accounts']} accounts"),
        ], C360) + '</td></tr>')

    # ── Customer 360 ──────────────────────────────────────────────────────
    rows.append(_heading("Customer 360", C360,
                         "Who used it, for what, and how deeply"))
    if x is None:
        rows.append(
            f'<tr><td style="padding:0 24px;font:13px {FONT};color:{INK}">'
            f'Nothing has ever been reported. Customer 360\'s push_usage job '
            f'sends this; it is not running, or not yet set up.</td></tr>')
    elif not x["users"]:
        last = x["last_reported"]
        rows.append(
            f'<tr><td style="padding:0 24px;font:13px {FONT};color:{INK}">'
            f'Nothing reported for {day:%d %b %Y}. '
            + (f'Last report received '
               f'{timezone.localtime(last):%d %b %Y %H:%M}. '
               f'If that is not recent its push_usage job has stopped '
               f'- that is not the same as nobody using it.' if last else
               'It has never reported.') + '</td></tr>')
    else:
        per_person = x["minutes"] / x["users"] if x["users"] else 0
        per_search = (x["customer_views"] / x["searches"]
                      if x["searches"] else 0)
        rows.append(
            '<tr><td style="padding:4px 18px 6px">' + _tiles([
                (x["sessions"], "Sessions", ""),
                (f"{per_person:.0f} min", "Time per person", ""),
                (f"{per_search:.2f}", "Profiles per search",
                 "how often a search ends in a profile"),
                (x["exports"], "Exports", ""),
            ], TEAL) + '</td></tr>')

        if x["top_features"]:
            rows.append(_heading("What people used in it", TEAL))
            rows.append(_bars([(_feature(n), "", int(c))
                               for n, c in x["top_features"]], C360, "uses"))

        rows.append(_heading("Everybody who used it", TEAL,
                             "Most profiles opened first"))
        rows.append(_table(
            ["Person", "Branch", "Profiles", "Customers", "Searches",
             "Minutes", "First - last"],
            [[f'<b>{_e(r["name"])}</b>', _e(r["branch"]),
              f'{r["profiles"]:,}', f'{r["customers"]:,}',
              f'{r["searches"]:,}', f'{r["minutes"]:,}',
              (f'{r["first"]:%H:%M} - {r["last"]:%H:%M}'
               if r["first"] and r["last"] else "-")]
             for r in x["people"]],
            ["left", "left", "right", "right", "right", "right", "right"]))

        looked = [r for r in x["people"] if r["searches"] and not r["profiles"]]
        if looked:
            rows.append(_heading(
                "Searched but opened no profile", "#B7791F",
                "Worth a call - they may not be finding the customer they "
                "look for"))
            rows.append(_table(
                ["Person", "Branch", "Searches"],
                [[_e(r["name"]), _e(r["branch"]), f'{r["searches"]:,}']
                 for r in looked], ["left", "left", "right"]))

        if x["branches"]:
            rows.append(_heading("By branch", TEAL))
            rows.append(_bars([(b, f"{n} {'person' if n == 1 else 'people'}",
                                v) for b, n, v in x["branches"]],
                              C360, "profiles"))

        # The adoption gap: in the portfolio tool today, not in Customer 360.
        in_c360 = {r["username"] for r in x["people"]}
        missing = sorted(((u, v) for u, v in on_portfolio.items()
                          if u and u not in in_c360),
                         key=lambda r: -r[1])
        if missing:
            rows.append(_heading(
                f"Used the portfolio tool but not Customer 360 "
                f"({len(missing)})", "#B7791F",
                "The people trained on it who did not open it today"))
            rows.append(_table(
                ["Person", "Branch", "Portfolio pages"],
                [[_e(names.get(u, u)), _e(branches.get(u, NO_BRANCH)),
                  f"{v:,}"] for u, v in missing[:TOP]],
                ["left", "left", "right"]))
            if len(missing) > TOP:
                rows.append(
                    f'<tr><td style="padding:6px 24px 0;font:12px {FONT};'
                    f'color:{MUTED}">and {len(missing) - TOP} more.</td></tr>')

    # ── Customer 360, the week ────────────────────────────────────────────
    wk = weekly.get(c360_key) if c360_key else None
    if wk:
        rows.append(_heading(
            "Customer 360 - the last 7 days", C360,
            f"{wk['people']} different people used it this week"))
        top = max((d["profiles"] for d in wk["days"]), default=0)
        rows.append(_table(
            ["Day", "People", "Profiles", "", "Searches", "Minutes"],
            [[f'{d["day"]:%a %d %b}', f'{d["people"]:,}',
              f'{d["profiles"]:,}', _bar(d["profiles"], top, C360, 140),
              f'{d["searches"]:,}', f'{d["minutes"]:,}'] for d in wk["days"]],
            ["left", "right", "right", "left", "right", "right"]))

    # ── the portfolio tool ────────────────────────────────────────────────
    rows.append(_heading("Portfolio tool", TEAL_DARK,
                         f"{p['users']} of {p['accounts']} active accounts, "
                         f"{p['views']:,} pages"))
    if p["top_areas"]:
        rows.append(_bars([(path, f"{users} people", views)
                           for path, users, views in p["top_areas"]],
                          TEAL, "pages"))
    if p["top_users"]:
        rows.append(_heading("Most active people", TEAL_DARK))
        rows.append(_table(["Person", "Branch", "Pages"],
                           [[_e(n), _e(b), f"{v:,}"]
                            for n, v, b in p["top_users"]],
                           ["left", "left", "right"]))
    if p["branches"]:
        rows.append(_heading("By branch", TEAL_DARK))
        rows.append(_bars([(b, f"{n} {'person' if n == 1 else 'people'}", v)
                           for b, n, v in p["branches"]], TEAL, "pages"))

    top = max(portfolio_week.values(), default=0)
    rows.append(_heading("Portfolio tool - people each day", TEAL_DARK))
    rows.append(_table(
        ["Day", "", "People"],
        [[f"{d:%a %d %b}", _bar(portfolio_week[d], top, TEAL, 220),
          f"{portfolio_week[d]:,}"] for d in days],
        ["left", "left", "right"]))

    for title, lead in week_leaders(day).items():
        if not lead["people"]:
            continue
        unit = "Pages" if title == "Portfolio tool" else "Profiles"
        rows.append(_heading(f"Last 7 days - {title} - who uses it most",
                             C360 if "360" in title else TEAL_DARK,
                             "Ranked by the days they came back, then volume"))
        rows.append(_table(
            ["Person", "Branch", "Days", unit],
            [[_e(n), _e(b), f"{a}", f"{v:,}"]
             for n, b, a, v in lead["people"]],
            ["left", "left", "right", "right"]))

    rows.append(
        f'<tr><td style="padding:26px 24px 22px;font:11px {FONT};'
        f'color:{MUTED}">Sent each morning to the daily usage report list '
        f'(Administration &rarr; Alerts). Branch is the one on each person\'s '
        f'portfolio profile.</td></tr>')

    return (
        f'<!doctype html><html><body style="margin:0;padding:0;background:'
        f'{WASH}"><table width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{WASH}"><tr><td align="center" style="padding:'
        f'20px 10px"><table width="720" cellpadding="0" cellspacing="0" '
        f'style="max-width:720px;width:100%;background:#FFFFFF;border:1px '
        f'solid {LINE};border-radius:8px;overflow:hidden">'
        + "".join(rows) + '</table></td></tr></table></body></html>')


class Command(BaseCommand):
    help = ("E-mail yesterday's use of the portfolio tool and Customer 360 to "
            "the usage-report recipients.")

    def add_arguments(self, parser):
        parser.add_argument("--day", default="",
                            help="YYYY-MM-DD; default yesterday (Nairobi)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--html", default="",
                            help="with --dry-run, also write the HTML part "
                                 "to this file to look at")

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
        html = build_html(day)
        if options["dry_run"]:
            self.stdout.write(body)
            if options["html"]:
                with open(options["html"], "w", encoding="utf-8") as out:
                    out.write(html)
                self.stdout.write(f"HTML written to {options['html']}")
            return
        count = alerts.send(alerts.AlertRecipient.KIND_USAGE_REPORT,
                            f"Daily usage - {day:%d %b %Y}", body, html=html)
        self.stdout.write(f"usage report sent to {count} recipient(s)")
