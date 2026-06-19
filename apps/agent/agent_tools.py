"""Tools the Claude agent can call to ground its answers in real HF Group data.

Each tool maps to a JSON schema (sent to the model) and an executor that queries
the application models directly — the same data the dashboards read — so the
agent's answers reflect live figures across **every module** (mortgages, leads,
collections, HFDI projects, rights issue, EXCO initiatives, staff performance,
insurance, trade finance, bank-wide deposits/loans, insights & analytics) rather
than guesses. Results are bounded and JSON-serialised before being returned to
the model as ``tool_result`` content.

Safety: every executor is dispatched through ``run_tool`` which wraps the call in
a try/except and returns a JSON ``{"error": ...}`` string on failure — so a tool
that touches an empty or unavailable table (e.g. a warehouse read in a dev
environment) degrades gracefully and never raises a 500.
"""

import json
from datetime import date, timedelta

from django.db.models import Count, Sum

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
    qs = Insight.objects.filter(is_active=True)
    if category:
        qs = qs.filter(category=category)
    return [{
        "title": i.title, "category": i.category, "severity": i.severity,
        "segment": i.segment, "branch": i.branch,
        "metric_value": str(i.metric_value) if i.metric_value is not None else None,
        "metric_delta": str(i.metric_delta) if i.metric_delta is not None else None,
        "body": (i.body or "")[:400],
        "generated_at": str(i.generated_at.date()),
    } for i in qs.order_by("-generated_at")[:_clamp(limit)]]


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
    return [{
        "banking_segment": r.banking_segment, "segment": r.segment,
        "prev_year_balance": r.end_previous_year_bal, "current_balance": r.current_bal,
        "pct_movement": r.percentage_movement,
    } for r in CeoDepositMovement.objects.all()[:_clamp(limit)]]


def _bank_loans_movement(limit=MAX_ROWS):
    rows = CeoLoanMovementMonthlyBySegment.objects.all().order_by("-dates_eom")[:_clamp(limit)]
    return [{
        "segment": r.segment, "month": str(r.dates_eom) if r.dates_eom else None,
        "volume": r.volume, "value": r.value,
    } for r in rows]


# ── Tool registry ────────────────────────────────────────────────────────────

_STATUS_LOAN = ["active", "closed", "default", "restructured"]

TOOL_DEFINITIONS = [
    {
        "name": "get_portfolio_dashboard",
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
]

_DISPATCH = {
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
}


def run_tool(name, tool_input):
    """Execute a tool by name and return its result as a JSON string."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool '{name}'."})
    try:
        result = fn(**(tool_input or {}))
        return json.dumps(result, default=str)
    except Exception as exc:  # surface a usable error to the model, don't 500
        return json.dumps({"error": f"Tool '{name}' failed: {exc}"})
