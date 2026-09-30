"""Adoption of another system (Customer 360) by this tool's users.

Customer 360 pushes one row per user per day (``ExternalUsageDay``). On its own that
only lists the people who used it. The question being asked after the training is
the opposite one - who has not - and only this tool's user directory can answer it.
So every active user here is listed, with the Customer 360 usage matched to them by
username (case-insensitive), and put in exactly one of four states:

* ``active``  - used it in the last 7 days
* ``quiet``   - last used 7 to 30 days ago
* ``lapsed``  - last used more than 30 days ago
* ``never``   - no recorded use at all

"Never" means never *recorded*: Customer 360 keeps its activity trail for 90 days, so
a backfill reaches back that far and no further. The response says so.

Days are Nairobi calendar days, the same way the sender cuts them.
"""

from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Max, Min, Sum

from .models import ExternalUsageDay, MonitoredService

NAIROBI = ZoneInfo("Africa/Nairobi")
ACTIVE_DAYS = 7
QUIET_DAYS = 30

FEATURE_LABELS = {
    "customer_profile": "Customer profile opened",
    "search": "Customer search",
    "insights": "Products, limits and activity",
    "recommendations": "Next best product",
    "core_banking": "Core banking tab",
    "domains": "Whizz / Properties / Insurance tabs",
    "overview": "Overview tab",
    "linked_parties": "Linked and related parties",
    "worklist": "Cross-sell worklist",
    "activity_call_list": "Activity call list",
    "portfolio": "Portfolio dashboard",
    "my_book": "My book",
    "property_clients": "Property clients",
    "insurance_clients": "Insurance clients",
    "feedback": "Recommendation feedback",
    "export": "Exports",
}


def _status(last_used, today):
    if last_used is None:
        return "never"
    age = (today - last_used).days
    if age <= ACTIVE_DAYS - 1:
        return "active"
    if age <= QUIET_DAYS:
        return "quiet"
    return "lapsed"


def adoption(source, days, now):
    """The adoption report for ``source`` over the last ``days`` Nairobi days."""
    today = now.astimezone(NAIROBI).date()
    since = today - timedelta(days=days - 1)
    service = MonitoredService.objects.filter(slug=source).first()

    all_rows = ExternalUsageDay.objects.filter(source=source)
    lifetime = {
        r["username"]: r
        for r in all_rows.values("username").annotate(first=Min("day"), last=Max("day"))
    }
    window = all_rows.filter(day__gte=since, day__lte=today)
    per_user = {
        r["username"]: r
        for r in window.values("username").annotate(
            customer_views=Sum("customer_views"), distinct_customers=Sum("distinct_customers"),
            searches=Sum("searches"), exports=Sum("exports"), active_minutes=Sum("active_minutes"),
            requests=Sum("requests"))
    }
    days_active = defaultdict(int)
    trend = {since + timedelta(days=i): {"users": 0, "customer_views": 0, "searches": 0}
             for i in range(days)}
    features = defaultdict(lambda: {"uses": 0, "users": set()})
    for r in window.values("username", "day", "customer_views", "searches", "features"):
        days_active[r["username"]] += 1
        t = trend.get(r["day"])
        if t is not None:
            t["users"] += 1
            t["customer_views"] += r["customer_views"]
            t["searches"] += r["searches"]
        for name, n in (r["features"] or {}).items():
            features[name]["uses"] += int(n or 0)
            features[name]["users"].add(r["username"])

    User = get_user_model()
    people = (User.objects.filter(is_active=True)
              .select_related("profile").prefetch_related("groups"))
    users, seen = [], set()
    for u in people:
        key = (u.username or "").strip().lower()
        seen.add(key)
        profile = getattr(u, "profile", None)
        users.append(_user_row(
            key, lifetime.get(key), per_user.get(key), days_active.get(key, 0), today,
            name=u.get_full_name() or u.username, email=u.email or "",
            roles=[g.name for g in u.groups.all()],
            branch=getattr(profile, "branch", None) or "",
            sales_code=getattr(profile, "sales_code", None) or "",
            known_here=True))
    # Usernames Customer 360 knows that have no active account here (its own local
    # logins, or somebody since disabled) - listed, and marked, rather than dropped.
    for key, life in lifetime.items():
        if key not in seen:
            users.append(_user_row(key, life, per_user.get(key), days_active.get(key, 0), today,
                                   name=key, email="", roles=[], branch="", sales_code="",
                                   known_here=False))

    order = {"active": 0, "quiet": 1, "lapsed": 2, "never": 3}
    users.sort(key=lambda r: (order[r["status"]], -(r["customer_views"] or 0), r["name"].lower()))

    directory = [r for r in users if r["known_here"]]
    counts = defaultdict(int)
    for r in directory:
        counts[r["status"]] += 1
    branches = defaultdict(lambda: {"users": 0, "active": 0, "used_ever": 0})
    for r in directory:
        b = branches[r["branch"] or "No branch on profile"]
        b["users"] += 1
        b["active"] += r["status"] == "active"
        b["used_ever"] += r["status"] != "never"
    by_branch = sorted(
        ({"branch": k, **v, "adoption_pct": round(100.0 * v["used_ever"] / v["users"], 1)}
         for k, v in branches.items()),
        key=lambda b: (-b["users"], b["branch"]))

    last_reported = all_rows.aggregate(m=Max("reported_at"))["m"]
    total = len(directory)
    return {
        "source": source,
        "name": service.name if service else source,
        "days": days,
        "since": since,
        "until": today,
        "last_reported_at": last_reported,
        "history_note": ("Customer 360 keeps its activity trail for 90 days, so use older "
                         "than that is not on record here."),
        "summary": {
            "users": total,
            "active": counts["active"],
            "quiet": counts["quiet"],
            "lapsed": counts["lapsed"],
            "never": counts["never"],
            "used_in_window": sum(1 for r in directory if r["days_active"] > 0),
            "adoption_pct": round(100.0 * sum(1 for r in directory if r["status"] != "never") / total, 1)
            if total else None,
            "customer_views": sum(r["customer_views"] for r in users),
            "searches": sum(r["searches"] for r in users),
        },
        "trend": [{"day": d, **v} for d, v in sorted(trend.items())],
        "features": sorted(
            ({"feature": k, "label": FEATURE_LABELS.get(k, k.replace("_", " ").capitalize()),
              "uses": v["uses"], "users": len(v["users"])} for k, v in features.items()),
            key=lambda f: -f["uses"]),
        "by_branch": by_branch,
        "users": users,
    }


def _user_row(key, life, window, days_active, today, **info):
    last = life["last"] if life else None
    return {
        "username": key,
        **info,
        "status": _status(last, today),
        "first_used": life["first"] if life else None,
        "last_used": last,
        "days_since": (today - last).days if last else None,
        "days_active": days_active,
        "customer_views": (window or {}).get("customer_views") or 0,
        "distinct_customers": (window or {}).get("distinct_customers") or 0,
        "searches": (window or {}).get("searches") or 0,
        "exports": (window or {}).get("exports") or 0,
        "active_minutes": (window or {}).get("active_minutes") or 0,
    }
