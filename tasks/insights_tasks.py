from celery import shared_task
import structlog

logger = structlog.get_logger(__name__)


@shared_task(name="tasks.insights_tasks.run_pipeline")
def run_pipeline():
    """Generate portfolio insights and persist them to the Insight table."""
    from django.utils import timezone
    from datetime import timedelta
    from apps.insights.models import Insight
    from apps.portfolio.models import Loans, HfCustomer
    from django.db.models import Sum, Count, Avg

    now = timezone.now()
    expires_at = now + timedelta(hours=6)

    # Deactivate stale insights
    Insight.objects.filter(expires_at__lt=now).update(is_active=False)

    generated = []

    # Insight: high arrears rate
    total_loans = Loans.objects.count()
    arrears_loans = Loans.objects.filter(days_in_arrears__gt=0).count()
    if total_loans > 0:
        arrears_pct = (arrears_loans / total_loans) * 100
        severity = "critical" if arrears_pct > 20 else ("warning" if arrears_pct > 10 else "info")
        insight = Insight.objects.create(
            title=f"Loans in Arrears: {arrears_pct:.1f}%",
            body=(
                f"{arrears_loans:,} out of {total_loans:,} loan accounts are in arrears "
                f"({arrears_pct:.1f}%). "
                + ("Immediate recovery action is recommended." if arrears_pct > 20 else "Monitor closely.")
            ),
            category="loans",
            severity=severity,
            metric_value=arrears_pct,
            is_active=True,
            expires_at=expires_at,
        )
        generated.append(insight.id)

    # Insight: active vs inactive customers
    total_customers = HfCustomer.objects.count()
    active_customers = HfCustomer.objects.filter(active=True).count()
    if total_customers > 0:
        active_pct = (active_customers / total_customers) * 100
        severity = "warning" if active_pct < 60 else "positive"
        insight = Insight.objects.create(
            title=f"Customer Activation Rate: {active_pct:.1f}%",
            body=(
                f"{active_customers:,} of {total_customers:,} customers are active ({active_pct:.1f}%). "
                + ("Consider reactivation campaigns." if active_pct < 60 else "Healthy activation rate.")
            ),
            category="customers",
            severity=severity,
            metric_value=active_pct,
            is_active=True,
            expires_at=expires_at,
        )
        generated.append(insight.id)

    logger.info("insights_pipeline_complete", insights_generated=len(generated))
    return len(generated)
