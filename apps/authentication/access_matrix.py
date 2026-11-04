"""Who has access to the portfolio system, and what each role opens.

Built for the regulator's "access matrix / approved-user listing". It reports what
the system holds. The system does not hold who approved each person's access, so that
column stays blank for the bank's signed forms to fill, rather than implying approval.
"""

from django.contrib.auth.models import User

from core.roles import ALL_ROLE_DESCRIPTIONS, ROLE_TO_TIER, tier_for_groups

COVERAGE_NOTE = (
    "Portfolio system accounts. One login also opens Customer 360. Accounts created "
    "only inside Customer 360 are held there and are not listed here. "
    "Approval is not recorded in the system: complete it from the signed access forms."
)
#: Not signed in for this long is flagged for the owner to review.
DORMANT_DAYS = 90


def user_rows():
    """One row per account, in a stable order."""
    from apps.analytics.exclusions import EXCLUDED_GROUP  # noqa: F401 - documents the group
    from django.utils import timezone

    now = timezone.now()
    rows = []
    for user in (User.objects.select_related("profile").prefetch_related("groups")
                 .order_by("username")):
        groups = sorted(g.name for g in user.groups.all())
        profile = getattr(user, "profile", None)
        idle = (now - user.last_login).days if user.last_login else None
        rows.append({
            "username": user.username,
            "name": user.get_full_name(),
            "email": user.email,
            "branch": getattr(profile, "branch", "") or "",
            "segment": getattr(profile, "segment", "") or "",
            "sales_code": getattr(profile, "sales_code", "") or "",
            "active": user.is_active,
            "staff": user.is_staff,
            "superuser": user.is_superuser,
            "tier": tier_for_groups(groups),
            "roles": groups,
            "date_joined": user.date_joined,
            "last_login": user.last_login,
            "days_since_login": idle,
        })
    return rows


def summary(rows):
    active = [r for r in rows if r["active"]]
    return {
        "accounts": len(rows),
        "active": len(active),
        "inactive": len(rows) - len(active),
        "superusers": sum(1 for r in active if r["superuser"]),
        "staff_flag": sum(1 for r in active if r["staff"]),
        "no_role": sum(1 for r in active if not r["roles"]),
        "never_signed_in": sum(1 for r in active if r["last_login"] is None),
        "dormant": sum(1 for r in active if (r["days_since_login"] or 0) > DORMANT_DAYS),
    }


def role_rows(rows):
    """One row per role: what it is, its tier, and how many active accounts hold it."""
    held = {}
    for row in rows:
        if row["active"]:
            for role in row["roles"]:
                held[role] = held.get(role, 0) + 1
    names = sorted(set(ALL_ROLE_DESCRIPTIONS) | set(held))
    return [{"role": name,
             "tier": ROLE_TO_TIER.get(name, "not in the registry"),
             "description": ALL_ROLE_DESCRIPTIONS.get(name, "Not in the role registry"),
             "active_accounts": held.get(name, 0)} for name in names]


def workbook(rows):
    """The Excel report's bytes."""
    from apps.observability import report_xlsx

    totals = summary(rows)
    user_headers = ["Username", "Name", "Email", "Branch", "Segment", "Sales code",
                    "Active", "Staff flag", "Superuser", "Tier", "Roles",
                    "Created", "Last sign-in", "Days since sign-in",
                    "Approved by", "Form reference"]

    def line(r):
        return [r["username"], r["name"], r["email"], r["branch"], r["segment"],
                r["sales_code"], "Yes" if r["active"] else "No",
                "Yes" if r["staff"] else "No", "Yes" if r["superuser"] else "No",
                r["tier"], ", ".join(r["roles"]), r["date_joined"], r["last_login"],
                r["days_since_login"], "", ""]

    privileged = [r for r in rows if r["active"] and (r["superuser"] or r["staff"])]
    dormant = [r for r in rows if r["active"] and (
        r["last_login"] is None or (r["days_since_login"] or 0) > DORMANT_DAYS)]
    labels = (("Accounts", "accounts"), ("Active", "active"), ("Inactive", "inactive"),
              ("Active superusers", "superusers"), ("Active with staff flag", "staff_flag"),
              ("Active with no role", "no_role"),
              ("Active, never signed in", "never_signed_in"),
              (f"Active, no sign-in for over {DORMANT_DAYS} days", "dormant"))
    return report_xlsx.build([
        {"title": "Summary", "note": COVERAGE_NOTE, "headers": ["Measure", "Value"],
         "rows": [(label, totals[key]) for label, key in labels]},
        {"title": "Access Matrix", "headers": ["Role", "Tier", "What it gives", "Active accounts"],
         "rows": [(r["role"], r["tier"], r["description"], r["active_accounts"])
                  for r in role_rows(rows)]},
        {"title": "User Listing", "note": COVERAGE_NOTE, "headers": user_headers,
         "rows": [line(r) for r in rows]},
        {"title": "Privileged Accounts", "headers": user_headers,
         "rows": [line(r) for r in privileged]},
        {"title": "For Review", "note": f"Active accounts never used, or unused for over "
                                        f"{DORMANT_DAYS} days.",
         "headers": user_headers, "rows": [line(r) for r in dormant]},
    ])
