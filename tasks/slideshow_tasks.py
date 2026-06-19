from celery import shared_task
import structlog

logger = structlog.get_logger(__name__)


def _safe_query(fn, fallback):
    """Run a legacy-DB query, returning fallback if the table doesn't exist."""
    try:
        return fn()
    except Exception:
        return fallback


@shared_task(name="tasks.slideshow_tasks.precompute_all_slides")
def precompute_all_slides():
    """Precompute all dashboard slides and store them in the Slide table."""
    from datetime import timedelta

    from django.db.models import Sum
    from django.utils import timezone

    from apps.gceo_dashboard.models import EmployeeTable
    from apps.portfolio.models import Accounts, HfCustomer, Loans
    from apps.slideshow.models import Slide

    expires_at = timezone.now() + timedelta(minutes=10)
    slides_data = []

    # Customers summary
    total_customers = _safe_query(lambda: HfCustomer.objects.count(), 0)
    active_customers = _safe_query(lambda: HfCustomer.objects.filter(active=True).count(), 0)
    slides_data.append({
        "title": "Customer Overview",
        "content_type": "customers_summary",
        "order": 1,
        "payload": {
            "total_customers": total_customers,
            "active_customers": active_customers,
            "inactive_customers": total_customers - active_customers,
        },
    })

    # Deposits summary
    total_deposits = _safe_query(
        lambda: Accounts.objects.aggregate(total=Sum("current_balance"))["total"] or 0, 0
    )
    slides_data.append({
        "title": "Deposits Summary",
        "content_type": "deposits_summary",
        "order": 2,
        "payload": {"total_deposits": float(total_deposits)},
    })

    # Loans summary
    total_loans = _safe_query(
        lambda: Loans.objects.aggregate(total=Sum("euro_book_balance"))["total"] or 0, 0
    )
    total_arrears = _safe_query(
        lambda: Loans.objects.filter(days_in_arrears__gt=0).aggregate(
            total=Sum("total_arrears")
        )["total"] or 0,
        0,
    )
    slides_data.append({
        "title": "Loans & Arrears",
        "content_type": "loans_summary",
        "order": 3,
        "payload": {
            "total_loans": float(total_loans),
            "total_arrears": float(total_arrears),
        },
    })

    # Staff summary
    total_staff = _safe_query(lambda: EmployeeTable.objects.count(), 0)
    slides_data.append({
        "title": "Staff Overview",
        "content_type": "branch_performance",
        "order": 4,
        "payload": {"total_staff": total_staff},
    })

    Slide.objects.filter(is_active=True).update(is_active=False)
    for data in slides_data:
        Slide.objects.create(
            title=data["title"],
            content_type=data["content_type"],
            order=data["order"],
            payload=data["payload"],
            is_active=True,
            expires_at=expires_at,
        )

    logger.info("slideshow_precomputed", slides_count=len(slides_data))
    return len(slides_data)
