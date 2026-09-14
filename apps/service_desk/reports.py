"""What the desk did, and how long it took.

One module feeding both the dashboard and the emailed report, so the figure a
manager reads in their inbox is the same figure the screen shows. Two sources
for one number is how a meeting turns into an argument about whose number is
right.

Everything is measured in **working time** (see ``worktime``), and everything
that cannot be measured is reported as unmeasured rather than as a zero. A
desk with no tickets has no average resolution time; printing "0h" would read
as instant.
"""

from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

from .models import Ticket, TicketCategory
from .worktime import describe

OPEN_STATUSES = [
    Ticket.STATUS_NEW, Ticket.STATUS_ASSIGNED,
    Ticket.STATUS_IN_PROGRESS, Ticket.STATUS_ON_HOLD,
]


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else None


def _avg(values):
    values = [v for v in values if v is not None]
    return int(sum(values) / len(values)) if values else None


def overview(days=30, now=None):
    """The headline numbers, for the dashboard tiles and the digest."""
    now = now or timezone.now()
    since = now - timedelta(days=days)

    window = Ticket.objects.filter(created_at__gte=since)
    raised = window.count()

    resolved_rows = list(
        Ticket.objects.filter(resolved_at__gte=since)
        .select_related("category")
    )
    resolved = len(resolved_rows)

    open_rows = list(
        Ticket.objects.filter(status__in=OPEN_STATUSES).select_related("category")
    )

    # SLA attainment is judged on tickets that have FINISHED. Counting the ones
    # still in flight would report a breach the desk still has time to avoid.
    met_resolution = sum(1 for t in resolved_rows if t.resolution_breached is False)
    breached_resolution = sum(1 for t in resolved_rows if t.resolution_breached is True)
    judged = met_resolution + breached_resolution

    responded = [t for t in resolved_rows if t.first_response_at]
    met_response = sum(1 for t in responded if t.response_breached is False)

    # Open tickets already past their promise. This is the number that should
    # make somebody do something today, so it is separate from the historical
    # attainment figure.
    overdue = [t for t in open_rows
               if t.resolution_due_at and now > t.resolution_due_at]
    unanswered = [t for t in open_rows if not t.first_response_at]

    return {
        "days": days,
        "raised": raised,
        "resolved": resolved,
        "open": len(open_rows),
        "unassigned": sum(1 for t in open_rows if not t.assigned_to_id),
        "unanswered": len(unanswered),
        "overdue": len(overdue),
        "awaiting_requester": sum(
            1 for t in open_rows if t.status == Ticket.STATUS_ON_HOLD),
        "awaiting_confirmation": Ticket.objects.filter(
            status=Ticket.STATUS_RESOLVED).count(),

        # None, not 0, when nothing has been judged yet.
        "sla_resolution_percent": _pct(met_resolution, judged),
        "sla_response_percent": _pct(met_response, len(responded)),
        "breached": breached_resolution,

        "avg_resolution_seconds": _avg([t.working_seconds_open() for t in resolved_rows]),
        "avg_response_seconds": _avg([t.working_seconds_to_response() for t in responded]),
        "avg_resolution_label": describe(
            _avg([t.working_seconds_open() for t in resolved_rows])),
        "avg_response_label": describe(
            _avg([t.working_seconds_to_response() for t in responded])),

        "reopened": Ticket.objects.filter(
            last_reopened_at__gte=since).count(),
        "confirmed": Ticket.objects.filter(
            closed_at__gte=since, confirmed_by_requester=True).count(),
        "auto_closed": Ticket.objects.filter(
            closed_at__gte=since, confirmed_by_requester=False).count(),
        "satisfaction": Ticket.objects.filter(
            closed_at__gte=since, satisfaction__isnull=False
        ).aggregate(m=Avg("satisfaction"))["m"],
    }


def by_category(days=30, now=None):
    now = now or timezone.now()
    since = now - timedelta(days=days)
    out = []
    for category in TicketCategory.objects.all():
        rows = list(Ticket.objects.filter(category=category, created_at__gte=since))
        done = [t for t in rows if t.resolved_at]
        judged = [t for t in done if t.resolution_breached is not None]
        met = sum(1 for t in judged if t.resolution_breached is False)
        out.append({
            "slug": category.slug,
            "name": category.name,
            "raised": len(rows),
            "resolved": len(done),
            "open": sum(1 for t in rows if t.status in OPEN_STATUSES),
            "sla_percent": _pct(met, len(judged)),
            "avg_resolution_seconds": _avg([t.working_seconds_open() for t in done]),
            "avg_resolution_label": describe(
                _avg([t.working_seconds_open() for t in done])),
            "target_minutes": category.resolution_minutes,
        })
    out.sort(key=lambda r: -r["raised"])
    return out


def by_handler(days=30, now=None):
    """Per-person load. Deliberately load and speed, never a league table of
    who is 'best' — a handler given the hard queries would come last on that."""
    now = now or timezone.now()
    since = now - timedelta(days=days)
    buckets = {}
    for ticket in (Ticket.objects.filter(assigned_to__isnull=False)
                   .filter(Q(created_at__gte=since) | Q(status__in=OPEN_STATUSES))
                   .select_related("assigned_to", "category")):
        who = ticket.assigned_to
        key = who.id
        row = buckets.setdefault(key, {
            "id": key,
            "name": who.get_full_name() or who.username,
            "username": who.username,
            "open": 0, "resolved": 0, "overdue": 0, "_times": [],
        })
        if ticket.status in OPEN_STATUSES:
            row["open"] += 1
            if ticket.resolution_due_at and now > ticket.resolution_due_at:
                row["overdue"] += 1
        if ticket.resolved_at and ticket.resolved_at >= since:
            row["resolved"] += 1
            row["_times"].append(ticket.working_seconds_open())

    out = []
    for row in buckets.values():
        times = row.pop("_times")
        row["avg_resolution_seconds"] = _avg(times)
        row["avg_resolution_label"] = describe(_avg(times))
        out.append(row)
    out.sort(key=lambda r: (-r["open"], -r["resolved"]))
    return out


def trend(days=30, now=None):
    """Raised vs resolved per day — whether the queue is growing."""
    now = now or timezone.now()
    since = (now - timedelta(days=days)).date()
    raised = dict(
        Ticket.objects.filter(created_at__date__gte=since)
        .values_list("created_at__date")
        .annotate(n=Count("id"))
    )
    resolved = dict(
        Ticket.objects.filter(resolved_at__date__gte=since)
        .values_list("resolved_at__date")
        .annotate(n=Count("id"))
    )
    out = []
    day = since
    today = now.date()
    while day <= today:
        out.append({
            "day": day.isoformat(),
            "raised": raised.get(day, 0),
            "resolved": resolved.get(day, 0),
        })
        day += timedelta(days=1)
    return out


def ageing(now=None):
    """Open tickets bucketed by how long they have been waiting.

    The bucket that matters is the last one. A desk with three queries older
    than a working week has three people who have concluded that raising a
    query does nothing.
    """
    now = now or timezone.now()
    buckets = [("under_1d", 0), ("1_to_3d", 0), ("3_to_5d", 0), ("over_5d", 0)]
    counts = dict(buckets)
    day = 9 * 3600  # one working day of this desk's length
    oldest = []
    for ticket in Ticket.objects.filter(status__in=OPEN_STATUSES).select_related(
            "category", "assigned_to"):
        seconds = ticket.working_seconds_open(now)
        if seconds < day:
            counts["under_1d"] += 1
        elif seconds < 3 * day:
            counts["1_to_3d"] += 1
        elif seconds < 5 * day:
            counts["3_to_5d"] += 1
        else:
            counts["over_5d"] += 1
            oldest.append((seconds, ticket))
    oldest.sort(key=lambda pair: -pair[0])
    return {
        "buckets": counts,
        "oldest": [
            {
                "reference": t.reference,
                "subject": t.subject,
                "status": t.status,
                "waiting_label": describe(s),
                "assigned_to": (t.assigned_to.get_full_name() or t.assigned_to.username)
                if t.assigned_to_id else None,
                "category": t.category.name if t.category else None,
            }
            for s, t in oldest[:10]
        ],
    }


def _ascii(text):
    """Fold to ASCII.

    The report is printed to a console by --dry-run, and a console that cannot
    encode an em dash must not break the job that reports on everything else.
    ``describe(None)`` returns an em dash, so this is not hypothetical.
    """
    return (str(text)
            .replace("—", "-").replace("–", "-")
            .replace("‘", "'").replace("’", "'")
            .replace("“", '"').replace("”", '"')
            .replace("…", "...")
            .encode("ascii", "replace").decode("ascii"))


def digest_text(days=7, now=None):
    """The emailed report. Plain ASCII, for the same reason the observability
    digest is: a console that cannot encode an em dash must not break the job."""
    stats = overview(days=days, now=now)
    lines = [
        f"Service Desk - last {days} days",
        "=" * 44,
        "",
        "VOLUME",
        f"  Raised            : {stats['raised']}",
        f"  Resolved          : {stats['resolved']}",
        f"  Still open        : {stats['open']}",
        f"  Never answered    : {stats['unanswered']}",
        f"  Past target now   : {stats['overdue']}",
        "",
        "SPEED (working time)",
        f"  First response    : {stats['avg_response_label']}",
        f"  To resolution     : {stats['avg_resolution_label']}",
    ]

    def pct(value):
        return f"{value}%" if value is not None else "not measured - nothing judged yet"

    lines += [
        "",
        "AGAINST TARGET",
        f"  Responded in time : {pct(stats['sla_response_percent'])}",
        f"  Resolved in time  : {pct(stats['sla_resolution_percent'])}",
        f"  Breached          : {stats['breached']}",
        "",
        "CLOSURE",
        f"  Confirmed by the requester : {stats['confirmed']}",
        f"  Closed with no reply       : {stats['auto_closed']}",
        f"  Reopened                   : {stats['reopened']}",
    ]
    if stats["awaiting_confirmation"]:
        lines.append(f"  Awaiting confirmation      : {stats['awaiting_confirmation']}")

    rows = by_category(days=days, now=now)
    if any(r["raised"] for r in rows):
        lines += ["", "BY CATEGORY"]
        for row in rows:
            if not row["raised"]:
                continue
            lines.append(
                f"  {row['name'][:34]:<34} {row['raised']:>3} raised, "
                f"{row['resolved']:>3} resolved, avg {row['avg_resolution_label']}"
            )

    old = ageing(now=now)
    if old["oldest"]:
        lines += ["", "WAITING LONGEST"]
        for row in old["oldest"][:8]:
            owner = row["assigned_to"] or "nobody"
            lines.append(
                f"  {row['reference']}  {row['waiting_label']:>8}  "
                f"{owner[:20]:<20} {row['subject'][:40]}"
            )

    lines += ["", "Full detail: Service Desk > Reports."]
    return _ascii("\n".join(lines))
