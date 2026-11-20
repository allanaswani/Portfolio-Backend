"""The monthly Referrals report: a short note, and the figures in an Excel workbook.

Built for the Postbank partnership (Nov 2026). Postbank's team now refer
customers too, and their sales codes are Postbank's own, so every figure here is
split by where the referral came from (HFCB staff or Postbank) and a referrer is
always identified by the source and the code together, never the code alone.

**Which referrals a month holds.** Those received (captured) in it, each shown at
its status today. Two kinds have left the pipeline and are read back from the
history table, where the deletion left the referral as it last stood:

* a rejected referral, deleted when it is rejected (``ReferralStatusView``);
* one the retention job (``expire_referrals``) cleared, which it does with no
  user, after 90 days unconverted (counted as Expired) or a year after
  converting (still Converted).

Rows a person deleted for any other reason (a superuser clearing test rows) are
not counted.

A separate sheet lists the referrals *converted* in the month, whenever they were
received, since that is the list a referrer is credited on.

National ID, phone and e-mail are left out: the workbook may go outside the bank,
and the reference, the customer's name and the referrer are what reconciling it
needs.
"""

import datetime
from collections import Counter, defaultdict

from django.utils import timezone

from .models import Referral

STATUS_ORDER = [
    Referral.STATUS_UNALLOCATED,
    Referral.STATUS_ALLOCATED,
    Referral.STATUS_CONTACTED,
    Referral.STATUS_CONVERTED,
    Referral.STATUS_REJECTED,
    Referral.STATUS_EXPIRED,
]
STATUS_LABEL = dict(Referral.STATUS)
SOURCE_LABEL = dict(Referral.REFERRER_TYPES)
SOURCES = [Referral.REFERRER_HFCB, Referral.REFERRER_POSTBANK]

ROW_HEADERS = [
    "Reference", "Received", "Source", "Referrer sales code", "Referrer name",
    "Referrer PF", "Customer", "Branch", "Segment", "Status", "Assigned to",
    "Assignee sales code", "Contacted on", "Converted on",
]


def month_bounds(year, month):
    """The month as aware datetimes [start, end)."""
    start = timezone.make_aware(datetime.datetime(year, month, 1))
    nxt = datetime.datetime(year + (month == 12), month % 12 + 1, 1)
    return start, timezone.make_aware(nxt)


def previous_month(today=None):
    today = today or timezone.localdate()
    first = today.replace(day=1)
    last = first - datetime.timedelta(days=1)
    return last.year, last.month


def _name(user):
    if not user:
        return ""
    return user.get_full_name().strip() or user.username


def _record(r, assigned_name):
    """One referral (live row or history row) → the report's fields."""
    return {
        "ref": r.referral_ref,
        "received": r.created_at,
        "source": r.referrer_type or Referral.REFERRER_HFCB,
        "code": (r.sales_code or "").strip(),
        "referrer": (r.referrer_name or r.verified_staff_name or "").strip(),
        "pf": (r.pf_number or "").strip(),
        "customer": r.customer_name,
        "branch": r.branch or "",
        "segment": r.segment or "",
        "status": r.status,
        "assigned": assigned_name,
        "assigned_code": r.assigned_sales_code or "",
        "contacted": r.contacted_at,
        "converted": r.converted_at,
    }


def _gone_from_history(start, end, live_ids):
    """Referrals received in [start, end) that were rejected, or cleared by the
    retention job, and so are no longer in the pipeline."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    gone = (Referral.history
            .filter(history_type="-", created_at__gte=start, created_at__lt=end)
            .filter(Q(status=Referral.STATUS_REJECTED) | Q(history_user__isnull=True))
            .exclude(id__in=live_ids)
            .order_by("id", "-history_date"))
    rows, seen = [], set()
    users = {}
    for h in gone:
        if h.id in seen:
            continue
        seen.add(h.id)
        rows.append(h)
        if h.assigned_to_id:
            users[h.assigned_to_id] = None
    if users:
        for u in get_user_model().objects.filter(pk__in=users):
            users[u.pk] = _name(u)
    records = []
    for h in rows:
        record = _record(h, users.get(h.assigned_to_id) or "")
        if record["status"] not in (Referral.STATUS_REJECTED, Referral.STATUS_CONVERTED):
            record["status"] = Referral.STATUS_EXPIRED  # cleared unconverted at 90 days
        records.append(record)
    return records


def received(year, month):
    """Every referral received in the month, as report records, oldest first."""
    start, end = month_bounds(year, month)
    live = list(Referral.objects.filter(created_at__gte=start, created_at__lt=end)
                .select_related("assigned_to"))
    records = [_record(r, _name(r.assigned_to)) for r in live]
    records += _gone_from_history(start, end, [r.id for r in live])
    return sorted(records, key=lambda r: r["received"])


def converted(year, month):
    """Referrals converted in the month, whenever they were received."""
    start, end = month_bounds(year, month)
    rows = (Referral.objects.filter(converted_at__gte=start, converted_at__lt=end)
            .select_related("assigned_to").order_by("converted_at"))
    return [_record(r, _name(r.assigned_to)) for r in rows]


def _rate(part, whole):
    return (part / whole) if whole else 0.0


def summary_rows(records):
    """One row per source, then a total."""
    by_source = defaultdict(Counter)
    for r in records:
        by_source[r["source"]][r["status"]] += 1
    rows = []
    total = Counter()
    for source in SOURCES:
        counts = by_source.get(source, Counter())
        total.update(counts)
        n = sum(counts.values())
        rows.append([SOURCE_LABEL[source], n]
                    + [counts.get(s, 0) for s in STATUS_ORDER]
                    + [_rate(counts.get(Referral.STATUS_CONVERTED, 0), n)])
    n = sum(total.values())
    rows.append(["Total", n] + [total.get(s, 0) for s in STATUS_ORDER]
                + [_rate(total.get(Referral.STATUS_CONVERTED, 0), n)])
    return rows


def referrer_rows(records):
    """One row per referrer: (source, sales code), most referrals first."""
    groups = {}
    for r in records:
        key = (r["source"], r["code"].upper())
        g = groups.setdefault(key, {"code": r["code"], "names": Counter(),
                                    "counts": Counter()})
        if r["referrer"]:
            g["names"][r["referrer"]] += 1
        g["counts"][r["status"]] += 1
    rows = []
    for (source, _code), g in groups.items():
        c = g["counts"]
        n = sum(c.values())
        conv = c.get(Referral.STATUS_CONVERTED, 0)
        rej = c.get(Referral.STATUS_REJECTED, 0) + c.get(Referral.STATUS_EXPIRED, 0)
        name = g["names"].most_common(1)[0][0] if g["names"] else ""
        rows.append([SOURCE_LABEL[source], g["code"] or "(none given)", name, n,
                     conv, rej, n - conv - rej, _rate(conv, n)])
    rows.sort(key=lambda row: (-row[3], row[0], row[1]))
    return rows


def detail_rows(records):
    return [[r["ref"], r["received"], SOURCE_LABEL.get(r["source"], r["source"]),
             r["code"], r["referrer"], r["pf"], r["customer"], r["branch"],
             r["segment"], STATUS_LABEL.get(r["status"], r["status"]),
             r["assigned"], r["assigned_code"], r["contacted"], r["converted"]]
            for r in records]


def build_sheets(year, month):
    label = datetime.date(year, month, 1).strftime("%B %Y")
    records = received(year, month)
    postbank = [r for r in records if r["source"] == Referral.REFERRER_POSTBANK]
    conv = converted(year, month)
    return [
        {"title": "Summary",
         "note": f"Referrals received in {label}, each at its status today.",
         "headers": ["Source", "Received"]
                    + [STATUS_LABEL[s] for s in STATUS_ORDER] + ["Conversion %"],
         "rows": summary_rows(records)},
        {"title": "By referrer",
         "note": "A referrer is the source and the sales code together: "
                 "Postbank's codes are Postbank's own.",
         "headers": ["Source", "Referrer sales code", "Referrer name", "Received",
                     "Converted", "Rejected or expired", "Still open",
                     "Conversion %"],
         "rows": referrer_rows(records)},
        {"title": "Postbank referrals",
         "note": f"Every referral from Postbank received in {label}.",
         "headers": ROW_HEADERS, "rows": detail_rows(postbank)},
        {"title": f"Converted in {datetime.date(year, month, 1):%b %Y}",
         "note": f"Referrals converted in {label}, whenever they were received.",
         "headers": ROW_HEADERS, "rows": detail_rows(conv)},
        {"title": "All referrals",
         "note": f"Every referral received in {label}.",
         "headers": ROW_HEADERS, "rows": detail_rows(records)},
    ]


def build_body(year, month):
    """The note the mail carries; the figures are in the attachment."""
    label = datetime.date(year, month, 1).strftime("%B %Y")
    records = received(year, month)
    by_source = Counter(r["source"] for r in records)
    conv_cohort = sum(1 for r in records if r["status"] == Referral.STATUS_CONVERTED)
    conv_month = len(converted(year, month))
    return (
        "Dear All,\n\n"
        f"Please find attached the Referrals report for {label}.\n\n"
        f"Referrals received: {len(records):,} "
        f"({by_source.get(Referral.REFERRER_HFCB, 0):,} from HFCB staff, "
        f"{by_source.get(Referral.REFERRER_POSTBANK, 0):,} from Postbank), "
        f"of which {conv_cohort:,} have converted so far.\n"
        f"Referrals converted during {label}: {conv_month:,}.\n\n"
        "Kind Regards,\n"
        "Analytics and Business Performance"
    )


def workbook(year, month):
    from apps.observability import report_xlsx

    return report_xlsx.build(build_sheets(year, month))


def filename(year, month):
    return f"Referrals Report - {year}-{month:02d}.xlsx"
