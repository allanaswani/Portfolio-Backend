"""Fill portfolio_rm_targets from the bank's real plan, so the scorecard can grade.

    manage.py load_rm_targets                    # YTD targets as at the closed month
    manage.py load_rm_targets --month 8 --year 2026
    manage.py load_rm_targets --dry-run

RmTarget was empty on production - every month, every RM - which is the whole
reason the scorecard graded 127 people E. The plan itself was never missing; it
just lived somewhere the scorecard does not read.

Where the numbers come from
---------------------------
``branch_employee_dmc_data``, one row per sales staff member. NOT
``branch_final_employee_dmc_data``, which holds one row per BRANCH: a branch's
target sits on its manager's row AND, split up, across that branch's RMs, so
reading both would count the same plan twice. See the double-counting trap in
staff_management/targets.py.

    RmTarget.deposit_target        <- target_deposits_value
    RmTarget.loan_target           <- target_loan_disbursement
    RmTarget.new_customers_target  <- target_new_customers
    RmTarget.revenue_target        <- NOTHING. There is no RM revenue target.

That last line is not an oversight. ``target_pbt_revenue`` exists only on
``branch_final_employee_dmc_data`` - the plan sets revenue per BRANCH and never
splits it across the RMs in that branch. Inventing a split here (per head, or
weighted by deposit target) would be a number the business never agreed to,
attached to somebody's performance review, so revenue_target is left at 0 and
this command says so every run.

The consequence is worth stating plainly: with revenue unscored at 20% and
loans unscored at 30% (no RM-level loan actuals exist either), only half the
weighted scorecard is live, and the best score anybody can reach is 55 - grade
D. ``manage.py scorecard_audit`` works this out from the data.

Why the figures are pro-rated to YTD, not divided by twelve
-----------------------------------------------------------
DMC targets are ANNUAL, keyed by start_date. The scorecard stores one row per
month, so an annual figure has to be sliced - and the slice has to match what
the actual side measures.

Revenue is the constraint. portfolio_rm_revenue carries NO date column at all;
it is a year-to-date snapshot and cannot be filtered to a month. So the actual
for revenue is always YTD, and a monthly target (annual / 12) would be compared
against nine months of income in September - every RM at 110%, capped, for free.

Every pillar is therefore put on the same YTD footing: the row for month M
carries the target accumulated to the END of month M, matching an actual
accumulated to the end of month M. That is also how the old BranchDash graded
deposits, pro-rating the annual growth target by day of year.
"""
import calendar
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


def _previous_month(today):
    return date(today.year - 1, 12, 1) if today.month == 1 \
        else date(today.year, today.month - 1, 1)


class Command(BaseCommand):
    help = "Populate RmTarget from the DMC plan so the scorecard has something to grade against."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, help="Scorecard year (default: this one).")
        parser.add_argument("--month", type=int, help="Scorecard month (default: the closed one).")
        parser.add_argument(
            "--cycle", type=int,
            help="DMC plan cycle to read, by start_date year. Defaults to --year.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *a, **o):
        from apps.portfolio_management_enrichment.models import RmTarget
        from apps.staff_management.models import BranchEmployeeDmcData
        from apps.staff_management.targets import prorate

        w = self.stdout.write
        today = timezone.now().date()
        prev = _previous_month(today)
        year = o["year"] or prev.year
        month = o["month"] or prev.month
        if not 1 <= month <= 12:
            raise CommandError("--month must be 1-12.")
        period = date(year, month, 1)
        cycle = o["cycle"] or year

        # Pro-rate to the END of the scorecard month, so a target accumulated to
        # that date meets an actual accumulated to that date.
        as_at = date(year, month, calendar.monthrange(year, month)[1])

        w("")
        w(f"Scorecard period : {period:%B %Y}   (targets accumulated to {as_at})")
        w(f"DMC plan cycle   : {cycle}   (branch_employee_dmc_data.start_date)")
        w("")

        rows = (
            BranchEmployeeDmcData.objects
            .filter(start_date__year=cycle)
            .exclude(sales_code__isnull=True)
            .exclude(sales_code__exact="")
            .exclude(staff_exit=1)          # this table's exit flag, not "exit"
            .values("sales_code", "staff_name", "target_deposits_value",
                    "target_loan_disbursement", "target_new_customers")
        )
        rows = list(rows)
        if not rows:
            w(f"  No DMC rows with start_date in {cycle}. Nothing to load.")
            w("  Check the plan cycle: manage.py load_rm_targets --cycle <year>")
            return

        # One person can hold more than one DMC row (the upsert key is
        # pf + sales_code + role), so take the largest figure per sales code
        # rather than summing - summing would inflate the target and make a
        # performing RM look like a failure.
        best = {}
        for r in rows:
            code = (r["sales_code"] or "").strip()
            if not code:
                continue
            cur = best.setdefault(code, {"staff_name": r["staff_name"]})
            for field in ("target_deposits_value", "target_loan_disbursement",
                          "target_new_customers"):
                val = r.get(field) or 0
                cur[field] = max(cur.get(field, 0), val)

        created = updated = skipped = 0
        for code, t in sorted(best.items()):
            dep = prorate(t.get("target_deposits_value") or 0, as_at)["ytd"]
            loan = prorate(t.get("target_loan_disbursement") or 0, as_at)["ytd"]
            ncs = prorate(t.get("target_new_customers") or 0, as_at, unit="number")["ytd"]
            rev = 0  # no RM-level revenue target exists; see the module docstring

            if not any((dep, loan, ncs)):
                # A plan row with nothing in it is not a target of zero - it is
                # an absent target, and writing it would score this RM 0 on
                # every pillar and grade them E for a data gap.
                skipped += 1
                continue

            if o["dry_run"]:
                created += 1
                continue

            _, is_new = RmTarget.objects.update_or_create(
                sales_code=code, month=period,
                defaults=dict(
                    deposit_target=dep, loan_target=loan,
                    revenue_target=rev, new_customers_target=int(ncs or 0),
                    input_user="load_rm_targets",
                ),
            )
            created += is_new
            updated += not is_new

        w(f"  DMC rows read              {len(rows):>7}")
        w(f"  distinct sales codes       {len(best):>7}")
        w(f"  skipped (no plan figures)  {skipped:>7}")
        if o["dry_run"]:
            w(f"  would write                {created:>7}")
            w("  --dry-run: nothing written.")
        else:
            w(f"  targets created            {created:>7}")
            w(f"  targets updated            {updated:>7}")
            w("")
            w("  revenue_target is 0 for every row. target_pbt_revenue is set")
            w("  per BRANCH and the plan never splits it across RMs, so there")
            w("  is no RM figure to load. Revenue is 20% of the scorecard and")
            w("  will score zero until the business decides how to split it or")
            w("  the weights are changed.")
            w("")
            w(f"  Now: manage.py run_scorecard --year {year} --month {month}")
        w("")
