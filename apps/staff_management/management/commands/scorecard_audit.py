"""Why the scorecard page is empty, and why every grade is an E.

    manage.py scorecard_audit

Three different things can produce "no scorecard", and they need different
fixes, so this separates them:

    nothing ran        no rows for the month at all - the engine is triggered
                       by a POST and nothing in the deployment sends it
    nothing to score   rows exist but every score is 0, which is what happens
                       when there are no targets for the period
    nothing reachable  scores exist but the grade bands cannot be earned

It writes nothing.
"""
from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from apps.staff_management.models import (
    EmployeeMonthlyPerformance, PerformanceActual, RoleKPIMapping,
    ScorecardKPI, ScorecardRole,
)

# From views._weighted_score. Duplicated deliberately: if someone changes the
# weights there and not here, the arithmetic below stops agreeing with reality
# and this command's whole point is to notice that kind of drift.
WEIGHTS = {"deposits": 0.40, "loans": 0.30, "revenue": 0.20, "new customers": 0.10}
SCORE_CAP = 110.0


class Command(BaseCommand):
    help = "Diagnose an empty or all-E scorecard."

    def handle(self, *a, **o):
        w = self.stdout.write
        today = timezone.now().date()

        w("")
        w("Scorecard output (employee_monthly_performance_v2)")
        w("=" * 68)
        months = (
            EmployeeMonthlyPerformance.objects
            .values("month")
            .annotate(rows=Count("id"),
                      scored=Count("id", filter=Q(total_score__gt=0)),
                      best=Max("total_score"),
                      mean=Avg("total_score"))
            .order_by("-month")[:8]
        )
        months = list(months)
        if not months:
            w("  EMPTY. The engine has never run.")
        else:
            w(f"  {'month':<12}{'rows':>6}{'scored':>8}{'best':>8}{'average':>9}")
            for m in months:
                w(f"  {m['month']:%Y-%m}     {m['rows']:>6}{m['scored']:>8}"
                  f"{(m['best'] or 0):>8.1f}{(m['mean'] or 0):>9.1f}")
            latest = months[0]["month"]
            behind = (today.year - latest.year) * 12 + today.month - latest.month
            w("")
            w(f"  latest month in the table : {latest:%B %Y}")
            w(f"  today                     : {today:%B %Y}")
            if behind > 1:
                w(f"  {behind} months behind. Nothing has generated a scorecard since")
                w(f"  {latest:%B}, which is what a manual-only trigger looks like.")

        w("")
        w("Targets — the reason a row can exist and still score zero")
        w("=" * 68)
        try:
            from apps.portfolio_management_enrichment.models import RmTarget
            for m in months[:6]:
                n = RmTarget.objects.filter(
                    month__year=m["month"].year, month__month=m["month"].month
                ).count()
                flag = "   <- no targets, so every score is 0" if not n else ""
                w(f"  {m['month']:%Y-%m}   RmTarget rows {n:>6}{flag}")
            if not months:
                w("  (no scorecard months to check targets against)")
        except Exception as exc:
            w(f"  could not read RmTarget: {exc}")

        w("")
        w("Can the grades even be reached")
        w("=" * 68)
        # loan_actual is hardcoded to Decimal("0") in views._compute_scorecard,
        # because there is no RM-level loan actuals table - the loan branch of
        # the warehouse ETL is switched off. A pillar that is always zero still
        # carries its full weight into the total.
        reachable = SCORE_CAP * (1 - WEIGHTS["loans"])
        w(f"  score cap per pillar                 {SCORE_CAP:>8.0f}")
        w(f"  loans weight (always scores zero)    {WEIGHTS['loans'] * 100:>7.0f}%")
        w(f"  highest total anyone can reach       {reachable:>8.1f}")
        w("")
        for grade, floor in (("A", 90), ("B", 80), ("C", 60), ("D", 50)):
            ok = "reachable" if reachable >= floor else "IMPOSSIBLE"
            w(f"    grade {grade}  needs {floor:>3}   {ok}")
        if reachable < 80:
            w("")
            w("  Grades A and B cannot be awarded to anyone, in any month, at")
            w("  any level of performance. loan_actual is hardcoded to 0 in")
            w("  views._compute_scorecard because there is no RM-level loan")
            w("  actuals source, but the loans pillar still takes 30% of the")
            w("  weighted total. Every RM is therefore scored out of 77.")
            w("  This is a business decision to make, not a bug to quietly")
            w("  patch: either the loans ETL gets switched on, or the 30% is")
            w("  redistributed across the pillars that can actually be scored.")

        w("")
        w("Config tables")
        w("=" * 68)
        w(f"  scorecard_roles                 {ScorecardRole.objects.count():>6}")
        w(f"  scorecard_kpis                  {ScorecardKPI.objects.count():>6}")
        w(f"  scorecard_role_kpi_mappings     {RoleKPIMapping.objects.count():>6}")
        w(f"  scorecard_performance_actuals   {PerformanceActual.objects.count():>6}")
        w("")
        w("  These four drive the scorecard CONFIG screens. The engine in")
        w("  views._compute_scorecard does not read them - it scores deposits,")
        w("  loans, revenue and new customers against RmTarget on fixed")
        w("  weights. Empty config tables are therefore not the reason the")
        w("  grades are E; missing targets are.")
        w("")
