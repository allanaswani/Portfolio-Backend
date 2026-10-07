"""Tools the Claude agent can call to ground its answers in real HF Group data.

Each tool maps to a JSON schema (sent to the model) and an executor that queries
the application models directly — the same data the dashboards read — so the
agent's answers reflect live figures across **every module** (mortgages, leads,
collections, HFDI projects, rights issue, EXCO initiatives, staff performance,
insurance, trade finance, the service desk, referrals, the commercial pipeline,
design briefs, the trade register, bank-wide deposits/loans, insights &
analytics) rather than guesses. Results are bounded and JSON-serialised before being returned to
the model as ``tool_result`` content.

Safety: every executor is dispatched through ``run_tool`` which wraps the call in
a try/except and returns a JSON ``{"error": ...}`` string on failure — so a tool
that touches an empty or unavailable table (e.g. a warehouse read in a dev
environment) degrades gracefully and never raises a 500.
"""

import json
from datetime import date, timedelta

from core import warehouse
from django.db.models import Count, Sum
from django.utils import timezone

from apps.mortgages.models import (
    Borrower, MortgageApplication, MortgageLoan, RepaymentScheduleItem,
    Payment, Lead, FieldAgent, FieldVisit,
)
from apps.insights.models import Insight
from apps.analytics.models import AnalyticsSnapshot
from apps.hf_collections.models import Collection
from apps.hfdi.models import Project, Sales
from apps.hf_rights_issue.models import RightsIssueApplication
from apps.exco_innitiatives.models import ExcoInitiative
from apps.client_briefs.models import ClientBrief
from apps.staff_management.models import (
    EmployeeMonthlyPerformance, InsurancePolicy, TradeFinanceData,
)
from apps.gceo_dashboard.models import (
    CeoDepositMovement, CeoLoanMovementMonthlyBySegment,
)
from apps.service_desk.models import KbArticle, Ticket
from apps.referrals.models import Referral
from apps.commercial_pipeline.models import PipelineEntry
from apps.design_briefs.models import DesignBrief
from apps.trade_register.models import TradeRegisterEntry

MAX_ROWS = 25


# ── Executors ────────────────────────────────────────────────────────────────

def _portfolio_dashboard():
    loans = MortgageLoan.objects.all()
    active = loans.filter(status="active")
    today = date.today()
    soon = today + timedelta(days=30)
    return {
        "active_loans": active.count(),
        "total_loans": loans.count(),
        "outstanding_balance": str(active.aggregate(s=Sum("outstanding_balance"))["s"] or 0),
        "disbursed_principal": str(loans.aggregate(s=Sum("principal"))["s"] or 0),
        "interest_earned": str(Payment.objects.aggregate(s=Sum("interest_paid"))["s"] or 0),
        "repayments_due_30d": RepaymentScheduleItem.objects.filter(
            is_paid=False, due_date__gte=today, due_date__lte=soon).count(),
        "overdue_installments": RepaymentScheduleItem.objects.filter(
            is_paid=False, due_date__lt=today).count(),
        "applications_by_status": {
            row["status"]: row["n"]
            for row in MortgageApplication.objects.values("status").annotate(n=Count("id"))
        },
        "total_borrowers": Borrower.objects.count(),
        "total_applications": MortgageApplication.objects.count(),
    }


def _lead_funnel():
    counts = {row["status"]: row["n"]
              for row in Lead.objects.values("status").annotate(n=Count("id"))}
    total = sum(counts.values())
    converted = counts.get("converted", 0)
    return {
        "total_leads": total,
        "converted": converted,
        "conversion_rate": round((converted / total * 100) if total else 0, 2),
        "funnel": [{"status": key, "label": label, "count": counts.get(key, 0)}
                   for key, label in Lead.STATUS],
    }


def _field_leaderboard():
    rows = []
    for agent in FieldAgent.objects.all():
        agent_leads = Lead.objects.filter(field_agent=agent)
        visits = FieldVisit.objects.filter(field_agent=agent)
        total = agent_leads.count()
        converted = agent_leads.filter(status="converted").count()
        rows.append({
            "name": agent.name, "team": agent.team, "branch": agent.branch,
            "leads": total, "converted": converted,
            "conversion_rate": round((converted / total * 100) if total else 0, 2),
            "visits": visits.count(),
            "customers_onboarded": visits.aggregate(s=Sum("customers_onboarded"))["s"] or 0,
        })
    rows.sort(key=lambda r: (r["converted"], r["leads"]), reverse=True)
    return rows[:MAX_ROWS]


def _list_loans(status=None, limit=MAX_ROWS):
    qs = MortgageLoan.objects.select_related("borrower", "product").all()
    if status:
        qs = qs.filter(status=status)
    return [{
        "loan_ref": ln.loan_ref,
        "borrower": ln.borrower.full_name if ln.borrower_id else None,
        "product": ln.product.name if ln.product_id else None,
        "principal": str(ln.principal),
        "outstanding_balance": str(ln.outstanding_balance),
        "interest_rate": str(ln.interest_rate),
        "monthly_installment": str(ln.monthly_installment),
        "status": ln.status,
        "disbursement_date": str(ln.disbursement_date) if ln.disbursement_date else None,
    } for ln in qs[:_clamp(limit)]]


def _list_borrowers(search=None, branch=None, limit=MAX_ROWS):
    qs = Borrower.objects.all()
    if search:
        qs = qs.filter(full_name__icontains=search)
    if branch:
        qs = qs.filter(branch__icontains=branch)
    return [{
        "full_name": b.full_name, "national_id": b.national_id, "branch": b.branch,
        "employment_status": b.employment_status, "employer": b.employer,
        "gross_monthly_income": str(b.gross_monthly_income),
        "risk_rating": b.risk_rating, "kyc_status": b.kyc_status,
    } for b in qs[:_clamp(limit)]]


def _list_leads(status=None, branch=None, limit=MAX_ROWS):
    qs = Lead.objects.select_related("field_agent", "interested_product").all()
    if status:
        qs = qs.filter(status=status)
    if branch:
        qs = qs.filter(branch__icontains=branch)
    return [{
        "lead_ref": ld.lead_ref, "full_name": ld.full_name, "phone": ld.phone,
        "branch": ld.branch, "status": ld.status,
        "estimated_loan_amount": str(ld.estimated_loan_amount or 0),
        "field_agent": ld.field_agent.name if ld.field_agent_id else None,
        "interested_product": ld.interested_product.name if ld.interested_product_id else None,
    } for ld in qs[:_clamp(limit)]]


def _list_applications(status=None, limit=MAX_ROWS):
    qs = MortgageApplication.objects.select_related("borrower", "product").all()
    if status:
        qs = qs.filter(status=status)
    return [{
        "application_ref": a.application_ref,
        "borrower": a.borrower.full_name if a.borrower_id else None,
        "product": a.product.name if a.product_id else None,
        "amount_requested": str(a.amount_requested),
        "tenure_months": a.tenure_months,
        "status": a.status,
    } for a in qs[:_clamp(limit)]]


def _clamp(limit):
    try:
        return max(1, min(int(limit), MAX_ROWS))
    except (TypeError, ValueError):
        return MAX_ROWS


# ── Cross-module executors ───────────────────────────────────────────────────

def _business_insights(category=None, limit=MAX_ROWS):
    """Stored insights from the 6-hourly pipeline.

    An empty result used to end the conversation: the assistant said "there are
    no active business insights or alerts" and stopped, which reads as "the bank
    has nothing going on" when it actually means "a cron job has not run".
    Every other tool on this list still works, so an empty table is a reason to
    go and look at the data, not a reason to stop.
    """
    qs = Insight.objects.filter(is_active=True)
    if category:
        qs = qs.filter(category=category)

    rows = [{
        "title": i.title, "category": i.category, "severity": i.severity,
        "segment": i.segment, "branch": i.branch,
        "metric_value": str(i.metric_value) if i.metric_value is not None else None,
        "metric_delta": str(i.metric_delta) if i.metric_delta is not None else None,
        "body": (i.body or "")[:400],
        "generated_at": str(i.generated_at.date()),
    } for i in qs.order_by("-generated_at")[:_clamp(limit)]]
    if rows:
        return rows

    # Say WHY it is empty and what to do instead, so the model answers with
    # something the reader can act on rather than a dead end.
    stale = Insight.objects.filter(is_active=False).order_by("-generated_at").first()
    return {
        "insights": [],
        "reason": (
            "The stored insight table is empty. These are written by a scheduled "
            "job (manage.py run_insights_pipeline, every 6 hours); nothing here "
            "means that job has not run recently, NOT that the bank has no "
            "issues worth reporting."
        ),
        "last_generated": str(stale.generated_at.date()) if stale else None,
        "what_to_do": (
            "Do not tell the user there is nothing to report. Build the answer "
            "from live data instead - portfolio totals, arrears and collections, "
            "deposit and loan movement, branch and RM performance - and say the "
            "figures are read live because the scheduled insight job has not run."
        ),
    }


def _analytics_metrics(category=None, limit=MAX_ROWS):
    qs = AnalyticsSnapshot.objects.all()
    if category:
        qs = qs.filter(category=category)
    return [{
        "category": s.category, "metric_name": s.metric_name,
        "metric_value": str(s.metric_value), "segment": s.segment, "branch": s.branch,
        "period_start": str(s.period_start), "period_end": str(s.period_end),
    } for s in qs.order_by("-period_start", "-computed_at")[:_clamp(limit)]]


def _collections_recovery():
    qs = Collection.objects.all()
    by_status = {r["collection_status"]: r["n"]
                 for r in qs.values("collection_status").annotate(n=Count("id"))}
    officers = qs.values("collection_officer_name").annotate(n=Count("id")).order_by("-n")[:10]
    return {
        "total_records": qs.count(),
        "by_status": by_status,
        "promised_to_pay_total": str(qs.aggregate(s=Sum("ptp_amount"))["s"] or 0),
        "top_officers_by_cases": [
            {"officer": o["collection_officer_name"], "cases": o["n"]} for o in officers],
    }


def _hfdi_sales_summary(limit=MAX_ROWS):
    rows = []
    for project in Project.objects.all()[:60]:
        latest = (Sales.objects.filter(project=project)
                  .order_by("-month", "-recording_date").first())
        if latest:
            rows.append({
                "project": project.name,
                "mtd_volume": latest.mtd_volume, "ytd_volume": latest.ytd_volume,
                "mtd_value": str(latest.mtd_value), "ytd_value": str(latest.ytd_value),
                "ytd_income": str(latest.ytd_income),
            })
    rows.sort(key=lambda r: float(r["ytd_value"] or 0), reverse=True)
    return {
        "projects_with_sales": len(rows),
        "total_ytd_value": str(sum(float(r["ytd_value"] or 0) for r in rows)),
        "projects": rows[:_clamp(limit)],
    }


def _rights_issue_summary():
    qs = RightsIssueApplication.objects.all()
    agg = qs.aggregate(payable=Sum("amount_payable"), paid=Sum("amount_paid"),
                       applied=Sum("rights_applied"), allotted=Sum("shares_allotted"),
                       refunds=Sum("refund_amount"))
    return {
        "total_applications": qs.count(),
        "by_status": {r["status"]: r["n"]
                      for r in qs.values("status").annotate(n=Count("id"))},
        "by_payment_status": {r["payment_status"]: r["n"]
                              for r in qs.values("payment_status").annotate(n=Count("id"))},
        "amount_payable": str(agg["payable"] or 0),
        "amount_paid": str(agg["paid"] or 0),
        "rights_applied": int(agg["applied"] or 0),
        "shares_allotted": int(agg["allotted"] or 0),
        "refunds": str(agg["refunds"] or 0),
    }


def _exco_initiatives(status=None, limit=MAX_ROWS):
    qs = ExcoInitiative.objects.all()
    if status:
        qs = qs.filter(status=status)
    agg = ExcoInitiative.objects.aggregate(alloc=Sum("budget_allocated"),
                                           util=Sum("budget_utilised"))
    return {
        "by_status": {r["status"]: r["n"]
                      for r in ExcoInitiative.objects.values("status").annotate(n=Count("id"))},
        "by_priority": {r["priority"]: r["n"]
                        for r in ExcoInitiative.objects.values("priority").annotate(n=Count("id"))},
        "budget_allocated": str(agg["alloc"] or 0),
        "budget_utilised": str(agg["util"] or 0),
        "initiatives": [{
            "title": e.title, "status": e.status, "priority": e.priority,
            "owner": e.owner, "progress_pct": e.progress_percentage,
            "budget_allocated": str(e.budget_allocated or 0),
            "budget_utilised": str(e.budget_utilised or 0),
            "target_completion": str(e.target_completion_date) if e.target_completion_date else None,
        } for e in qs.order_by("-recording_date")[:_clamp(limit)]],
    }


def _staff_performance(department=None, limit=MAX_ROWS):
    latest = (EmployeeMonthlyPerformance.objects.order_by("-month")
              .values_list("month", flat=True).first())
    if not latest:
        return {"message": "No staff performance data available yet."}
    qs = EmployeeMonthlyPerformance.objects.filter(month=latest)
    if department:
        qs = qs.filter(department__icontains=department)
    return {
        "month": str(latest),
        "headcount": qs.count(),
        "top_performers": [{
            "staff_name": e.staff_name, "sales_code": e.sales_code,
            "department": e.department, "total_score": round(e.total_score, 2),
            "grade": e.grade,
            "deposit_actual": str(e.deposit_actual), "loan_actual": str(e.loan_actual),
            "revenue_actual": str(e.revenue_actual),
        } for e in qs.order_by("-total_score")[:_clamp(limit)]],
    }


def _client_briefs_summary(status=None, limit=MAX_ROWS):
    qs = ClientBrief.objects.select_related("rm").all()
    if status:
        qs = qs.filter(status=status)
    return {
        "total": ClientBrief.objects.count(),
        "by_status": {r["status"]: r["n"]
                      for r in ClientBrief.objects.values("status").annotate(n=Count("id"))},
        "briefs": [{
            "client_name": b.client_name, "status": b.status,
            "subject": b.display_subject,
            "rm": (b.rm.get_full_name() or b.rm.username) if b.rm_id else None,
            "created_at": str(b.created_at.date()),
        } for b in qs.order_by("-created_at")[:_clamp(limit)]],
    }


def _insurance_summary(year=None):
    qs = InsurancePolicy.objects.all()
    if year:
        qs = qs.filter(year=str(year))
    agg = qs.aggregate(premiums=Sum("premiums"), paid=Sum("paid"),
                       balance=Sum("balance"), sum_insured=Sum("sum_insured"))
    by_product = (qs.values("product").annotate(n=Count("id"), premium=Sum("premiums"))
                  .order_by("-premium")[:10])
    return {
        "policies": qs.count(),
        "premiums": str(agg["premiums"] or 0), "paid": str(agg["paid"] or 0),
        "balance": str(agg["balance"] or 0), "sum_insured": str(agg["sum_insured"] or 0),
        "by_product": [{"product": r["product"], "policies": r["n"],
                        "premiums": str(r["premium"] or 0)} for r in by_product],
    }


def _trade_finance_summary(year=None):
    qs = TradeFinanceData.objects.all()
    if year:
        qs = qs.filter(year=str(year))
    by_product = (qs.values("product_type").annotate(n=Count("id"), commission=Sum("commission_lcy"))
                  .order_by("-commission")[:10])
    return {
        "guarantees": qs.count(),
        "commission_lcy": str(qs.aggregate(s=Sum("commission_lcy"))["s"] or 0),
        "by_product": [{"product_type": r["product_type"], "count": r["n"],
                        "commission": str(r["commission"] or 0)} for r in by_product],
    }


def _bank_deposits_movement(limit=MAX_ROWS):
    # Dict rows, not model instances: these warehouse tables have no id column
    # and asking for one 500s. See core/warehouse.py.
    return [{
        "banking_segment": r["banking_segment"], "segment": r["segment"],
        "prev_year_balance": r["end_previous_year_bal"],
        "current_balance": r["current_bal"],
        "pct_movement": r["percentage_movement"],
    } for r in warehouse.rows(CeoDepositMovement)[:_clamp(limit)]]


def _bank_loans_movement(limit=MAX_ROWS):
    rows = (warehouse.rows(CeoLoanMovementMonthlyBySegment)
            .order_by("-dates_eom")[:_clamp(limit)])
    return [{
        "segment": r["segment"],
        "month": str(r["dates_eom"]) if r["dates_eom"] else None,
        "volume": r["volume"], "value": r["value"],
    } for r in rows]


# -- Modules that had no tool until now --------------------------------------
# The assistant is one agent behind nineteen entry points, so a module with no
# tool is a module it cannot answer about - it does not refuse, it reasons from
# nothing. These close that gap for the five remaining business modules. Same
# shape as everything above: a bounded aggregate plus a clamped list, and no
# free-form filtering.

def _service_desk_summary(status=None, limit=MAX_ROWS):
    qs = Ticket.objects.all()
    if status:
        qs = qs.filter(status=status)
    return {
        "total_tickets": Ticket.objects.count(),
        "by_status": {r["status"]: r["n"] for r in
                      Ticket.objects.values("status").annotate(n=Count("id"))},
        "by_priority": {r["priority"]: r["n"] for r in
                        Ticket.objects.values("priority").annotate(n=Count("id"))},
        # Past its resolution deadline and still unresolved. Counted on the whole
        # table rather than the filtered slice, so the number means the same
        # thing whatever status was asked for.
        "open_past_resolution_due": Ticket.objects.filter(
            resolution_due_at__lt=timezone.now(), resolved_at__isnull=True).count(),
        "unassigned": Ticket.objects.filter(assigned_to__isnull=True).count(),
        "reopened_at_least_once": Ticket.objects.filter(reopened_count__gt=0).count(),
        "kb_articles": KbArticle.objects.count(),
        "tickets": [{
            "reference": t.reference, "subject": t.subject,
            "status": t.status, "priority": t.priority,
            "department": t.requester_department, "branch": t.requester_branch,
            "assigned_to": (t.assigned_to.get_full_name() or t.assigned_to.username)
                           if t.assigned_to_id else None,
            "raised": str(t.created_at.date()),
            "resolved": str(t.resolved_at.date()) if t.resolved_at else None,
        } for t in qs.select_related("assigned_to").order_by("-created_at")[:_clamp(limit)]],
    }


def _referrals_summary(status=None, limit=MAX_ROWS):
    qs = Referral.objects.all()
    if status:
        qs = qs.filter(status=status)
    return {
        "total_referrals": Referral.objects.count(),
        "by_status": {r["status"]: r["n"] for r in
                      Referral.objects.values("status").annotate(n=Count("id"))},
        "by_branch": {r["branch"] or "(unset)": r["n"] for r in
                      Referral.objects.values("branch").annotate(n=Count("id"))
                      .order_by("-n")[:15]},
        "converted": Referral.objects.filter(converted_at__isnull=False).count(),
        "contacted": Referral.objects.filter(contacted_at__isnull=False).count(),
        "unallocated": Referral.objects.filter(assigned_to__isnull=True).count(),
        "flagged_possible_duplicate": Referral.objects.filter(
            is_possible_duplicate=True).count(),
        "referrals": [{
            "ref": r.referral_ref, "customer": r.customer_name,
            "status": r.status, "branch": r.branch, "segment": r.segment,
            "assigned_to": (r.assigned_to.get_full_name() or r.assigned_to.username)
                           if r.assigned_to_id else None,
            "created": str(r.created_at.date()),
        } for r in qs.select_related("assigned_to").order_by("-created_at")[:_clamp(limit)]],
    }


def _commercial_pipeline_summary(kind=None, limit=MAX_ROWS):
    qs = PipelineEntry.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    return {
        "total_entries": PipelineEntry.objects.count(),
        "by_kind": {r["kind"]: r["n"] for r in
                    PipelineEntry.objects.values("kind").annotate(n=Count("id"))},
        "by_segment": {r["segment"] or "(unset)": r["n"] for r in
                       PipelineEntry.objects.values("segment").annotate(n=Count("id"))
                       .order_by("-n")[:15]},
        "entries": [{
            "kind": e.kind, "customer": e.customer_name, "rm": e.rm_name,
            "branch": e.branch, "segment": e.segment,
        } for e in qs[:_clamp(limit)]],
    }


def _design_briefs_summary(status=None, limit=MAX_ROWS):
    qs = DesignBrief.objects.all()
    if status:
        qs = qs.filter(status=status)
    return {
        "total_briefs": DesignBrief.objects.count(),
        "by_status": {r["status"]: r["n"] for r in
                      DesignBrief.objects.values("status").annotate(n=Count("id"))},
        "by_department": {r["department"] or "(unset)": r["n"] for r in
                          DesignBrief.objects.values("department").annotate(n=Count("id"))
                          .order_by("-n")[:15]},
        "unassigned": DesignBrief.objects.filter(assigned_designer__isnull=True).count(),
        "sent_back_for_rework": DesignBrief.objects.filter(rework_count__gt=0).count(),
        "briefs": [{
            "reference": b.reference, "item": b.design_item,
            "type": b.item_type, "status": b.status, "priority": b.priority,
            "department": b.department,
            "designer": (b.assigned_designer.get_full_name()
                         or b.assigned_designer.username)
                        if b.assigned_designer_id else None,
            "release_date": str(b.release_date) if b.release_date else None,
            "reworks": b.rework_count,
        } for b in qs.select_related("assigned_designer")
                     .order_by("-created_at")[:_clamp(limit)]],
    }


def _trade_register_summary(limit=MAX_ROWS):
    qs = TradeRegisterEntry.objects.all()
    agg = qs.aggregate(commission=Sum("commission"), excise=Sum("excise_duty"))
    return {
        "total_entries": qs.count(),
        "by_product_type": {r["product_type"] or "(unset)": r["n"] for r in
                            qs.values("product_type").annotate(n=Count("id"))},
        "by_action": {r["action"] or "(unset)": r["n"] for r in
                      qs.values("action").annotate(n=Count("id"))},
        "by_branch": {r["originating_branch"] or "(unset)": r["n"] for r in
                      qs.values("originating_branch").annotate(n=Count("id"))
                      .order_by("-n")[:15]},
        # amount_fcy is in mixed currencies, so it is deliberately NOT summed:
        # a total across currencies would be a meaningless number. Commission
        # and excise duty are booked in KES, so those do add up.
        "commission_total_kes": str(agg["commission"] or 0),
        "excise_duty_total_kes": str(agg["excise"] or 0),
        "entries": [{
            "guarantee_ref": e.guarantee_ref, "product_type": e.product_type,
            "action": e.action, "customer": e.our_customer,
            "beneficiary": e.beneficiary, "currency": e.currency,
            "amount_fcy": str(e.amount_fcy), "commission": str(e.commission),
            "branch": e.originating_branch, "rm": e.rm_name,
        } for e in qs.order_by("-id")[:_clamp(limit)]],
    }



# ── Tool registry ────────────────────────────────────────────────────────────

_STATUS_LOAN = ["active", "closed", "default", "restructured"]

TOOL_DEFINITIONS = [
    {
        "name": "get_mortgage_dashboard",
        "description": "Get headline mortgage portfolio KPIs: active/total loans, "
                       "outstanding balance, disbursed principal, interest earned, "
                       "repayments due in 30 days, overdue installments, application "
                       "counts by status, and totals. Call this for portfolio-health questions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_lead_funnel",
        "description": "Get the leads conversion funnel: counts per lead status, total "
                       "leads, conversions, and conversion rate. Call this for lead-pipeline questions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_field_leaderboard",
        "description": "Get per-field-agent performance: leads, conversions, conversion "
                       "rate, visits, and customers onboarded, ranked best-first.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_loans",
        "description": "List individual mortgage loans with borrower, principal, "
                       "outstanding balance, rate, installment and status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": _STATUS_LOAN,
                           "description": "Optional loan-status filter."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "list_borrowers",
        "description": "List borrowers with income, employment, branch, risk and KYC status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Match part of the borrower's name."},
                "branch": {"type": "string", "description": "Filter by branch."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "list_leads",
        "description": "List sales leads with status, estimated amount, agent and product.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by lead status."},
                "branch": {"type": "string", "description": "Filter by branch."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "list_applications",
        "description": "List mortgage applications with borrower, product, amount, tenure and status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by application status."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    # ── Cross-module tools ────────────────────────────────────────────────────
    {
        "name": "get_business_insights",
        "description": "Get AI-generated business insights/alerts across the bank "
                       "(deposits, loans, customers, revenue, collections, risk, "
                       "performance) with severity and the metric behind each.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string",
                             "enum": ["deposits", "loans", "customers", "revenue",
                                      "collections", "risk", "performance"],
                             "description": "Optional category filter."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_analytics_metrics",
        "description": "Get the latest analytics snapshot metrics (deposits, loans, "
                       "customers, revenue, collections) by segment/branch and period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string",
                             "enum": ["deposits", "loans", "customers", "revenue", "collections"],
                             "description": "Optional category filter."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_collections_recovery",
        "description": "Get the HF collections & recovery feedback overview: case counts "
                       "by status, total promised-to-pay amount, and the busiest "
                       "collection officers. (Recovery on the wider loan book.)",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_hfdi_sales_summary",
        "description": "Get HF Development & Investment (HFDI) project sales: per-project "
                       "MTD/YTD volume, value and income, ranked by YTD value.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer",
                                     "description": f"Max projects (1-{MAX_ROWS})."}},
        },
    },
    {
        "name": "get_rights_issue_summary",
        "description": "Get the HF rights-issue summary: application counts by status and "
                       "payment status, amounts payable/paid, rights applied, shares "
                       "allotted and refunds.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_exco_initiatives",
        "description": "Get EXCO strategic initiatives: counts by status and priority, "
                       "total budget allocated vs utilised, and the initiative list with progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string",
                           "enum": ["Draft", "In Progress", "On Hold", "Completed", "Cancelled"],
                           "description": "Optional status filter."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_staff_performance",
        "description": "Get staff monthly performance scorecards for the latest month: "
                       "headcount and top performers by total score, with deposit/loan/"
                       "revenue actuals and grade. Optionally filter by department.",
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Filter by department (partial match)."},
                "limit": {"type": "integer", "description": f"Max staff rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_client_briefs",
        "description": "Get the client-brief (HFCB memo) summary RMs prepare for director "
                       "sign-off: total, counts by status (draft/submitted/signed) and recent briefs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["draft", "submitted", "signed"],
                           "description": "Optional status filter."},
                "limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_insurance_summary",
        "description": "Get the bancassurance book: policy count, premiums, paid, balance, "
                       "sum insured, and the top products by premium. Optionally filter by year.",
        "input_schema": {
            "type": "object",
            "properties": {"year": {"type": "string", "description": "Optional year, e.g. '2026'."}},
        },
    },
    {
        "name": "get_trade_finance_summary",
        "description": "Get the trade-finance book: guarantee count, total commission, and "
                       "the top product types by commission. Optionally filter by year.",
        "input_schema": {
            "type": "object",
            "properties": {"year": {"type": "string", "description": "Optional year, e.g. '2026'."}},
        },
    },
    {
        "name": "get_bank_deposits_movement",
        "description": "Get bank-wide (GCEO view) deposit movement by segment: previous "
                       "year-end vs current balance and percentage movement.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."}},
        },
    },
    {
        "name": "get_bank_loans_movement",
        "description": "Get bank-wide (GCEO view) monthly loan movement by segment: volume "
                       "and value, most-recent months first.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": f"Max rows (1-{MAX_ROWS})."}},
        },
    },
    {
        "name": "get_service_desk_summary",
        "description": "Get the internal Service Desk (IT ticketing) overview: ticket "
                       "counts by status and priority, how many are past their "
                       "resolution deadline, how many are unassigned or have been "
                       "reopened, the knowledge-base article count, and recent tickets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string",
                           "description": "Optional ticket status to filter the listed tickets by."},
                "limit": {"type": "integer",
                          "description": f"Max tickets to list (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_referrals_summary",
        "description": "Get the telesales Referrals pipeline: referral counts by status "
                       "and branch, how many were contacted and converted, how many are "
                       "still unallocated, duplicate flags, and recent referrals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string",
                           "description": "Optional referral status to filter the listed referrals by."},
                "limit": {"type": "integer",
                          "description": f"Max referrals to list (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_commercial_pipeline",
        "description": "Get the Commercial Pipeline: entry counts by kind and by segment, "
                       "with the customer, RM and branch of recent entries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string",
                         "description": "Optional pipeline entry kind to filter by."},
                "limit": {"type": "integer",
                          "description": f"Max entries to list (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_design_briefs_summary",
        "description": "Get the Marketing Design Briefs board: brief counts by status and "
                       "requesting department, how many are unassigned or have been sent "
                       "back for rework, and recent briefs with their designer and "
                       "release date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string",
                           "description": "Optional brief status to filter the listed briefs by."},
                "limit": {"type": "integer",
                          "description": f"Max briefs to list (1-{MAX_ROWS})."},
            },
        },
    },
    {
        "name": "get_trade_register_summary",
        "description": "Get the trade desk Register of guarantees and letters of credit: "
                       "entry counts by product type, action and originating branch, total "
                       "commission and excise duty in KES, and recent entries. Foreign "
                       "currency amounts are per-entry and are not totalled, because the "
                       "register holds several currencies.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer",
                                     "description": f"Max entries to list (1-{MAX_ROWS})."}},
        },
    },
]

_DISPATCH = {
    "get_mortgage_dashboard": lambda **kw: _portfolio_dashboard(),
    # The old name, kept so a conversation mid-flight does not break.
    "get_portfolio_dashboard": lambda **kw: _portfolio_dashboard(),
    "get_lead_funnel": lambda **kw: _lead_funnel(),
    "get_field_leaderboard": lambda **kw: _field_leaderboard(),
    "list_loans": _list_loans,
    "list_borrowers": _list_borrowers,
    "list_leads": _list_leads,
    "list_applications": _list_applications,
    "get_business_insights": _business_insights,
    "get_analytics_metrics": _analytics_metrics,
    "get_collections_recovery": lambda **kw: _collections_recovery(),
    "get_hfdi_sales_summary": _hfdi_sales_summary,
    "get_rights_issue_summary": lambda **kw: _rights_issue_summary(),
    "get_exco_initiatives": _exco_initiatives,
    "get_staff_performance": _staff_performance,
    "get_client_briefs": _client_briefs_summary,
    "get_insurance_summary": _insurance_summary,
    "get_trade_finance_summary": _trade_finance_summary,
    "get_bank_deposits_movement": _bank_deposits_movement,
    "get_bank_loans_movement": _bank_loans_movement,
    "get_service_desk_summary": _service_desk_summary,
    "get_referrals_summary": _referrals_summary,
    "get_commercial_pipeline": _commercial_pipeline_summary,
    "get_design_briefs_summary": _design_briefs_summary,
    "get_trade_register_summary": _trade_register_summary,
}


# ── Outward-facing lookups ───────────────────────────────────────────────────
# Every tool above reads this bank's own warehouse. These two do not: they reach
# a third-party service, so they exist ONLY when TINYFISH_API_KEY is set. With
# no key the definitions are never offered to the model, which cannot then try
# and fail — and nothing leaves the bank until somebody deliberately turns it
# on. See apps/agent/web_lookup.py for the guard on what may be sent.

def tool_definitions():
    """The tools to offer the model for this deployment.

    A function rather than a constant because whether the external lookups
    exist is decided by configuration, and a module-level list would freeze
    that at import time.
    """
    from . import bank_tools, rm_tools, trino_tools, web_lookup

    # The signed-in person's own book comes FIRST. A relationship manager
    # asking about "my portfolio" was being answered from the mortgage
    # module, because that tool was called get_portfolio_dashboard and
    # nothing read their actual book.
    #
    # bank_tools follows: one customer, one branch, and the market. Those are
    # scoped to the caller in the queryset, so they are safe to offer to
    # everybody — what differs is how much comes back.
    tools = rm_tools.TOOL_DEFINITIONS + bank_tools.TOOL_DEFINITIONS + TOOL_DEFINITIONS
    if trino_tools.enabled():
        tools = tools + trino_tools.TOOL_DEFINITIONS
    if web_lookup.enabled():
        tools = tools + web_lookup.TOOL_DEFINITIONS
    return tools


def run_tool(name, tool_input, user=None):
    """Execute a tool by name and return its result as a JSON string.

    ``user`` is passed only to the tools that are scoped to the person asking.
    Everything else is bank-wide by design and takes no user, so a tool cannot
    accidentally widen its own scope by ignoring the argument.
    """
    from . import bank_tools, rm_tools, trino_tools, web_lookup

    # Everything scoped to the person asking goes through one path, so a new
    # scoped tool cannot be added without receiving the user.
    for scoped in (rm_tools.DISPATCH, bank_tools.DISPATCH):
        if name in scoped:
            try:
                return json.dumps(
                    scoped[name](user=user, **(tool_input or {})), default=str)
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": f"Tool '{name}' failed: {exc}"})

    if name in trino_tools.DISPATCH:
        # Refuse rather than run if the lake was unconfigured after the model
        # was handed the definition — configuration is the control.
        if not trino_tools.enabled():
            return json.dumps(
                {"error": "The Trino lake is not configured on this server."})
        try:
            return json.dumps(
                trino_tools.DISPATCH[name](**(tool_input or {})), default=str)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"Tool '{name}' failed: {exc}"})

    fn = _DISPATCH.get(name)
    if fn is None and name in web_lookup.DISPATCH:
        # Refuse rather than run if the key was removed after the model was
        # given the definition — configuration is the control, not the prompt.
        if not web_lookup.enabled():
            return json.dumps(
                {"error": "External lookup is not enabled on this server."})
        fn = web_lookup.DISPATCH[name]
    if fn is None:
        return json.dumps({"error": f"Unknown tool '{name}'."})
    try:
        result = fn(**(tool_input or {}))
        return json.dumps(result, default=str)
    except Exception as exc:  # surface a usable error to the model, don't 500
        return json.dumps({"error": f"Tool '{name}' failed: {exc}"})
