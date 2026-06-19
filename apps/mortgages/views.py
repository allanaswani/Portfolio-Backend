"""Mortgages API — CRUD, CSV bulk import, pipeline actions and aggregations."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import django_filters.rest_framework
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from apps.staff_management.views import BaseCsvUploadView

from .models import (
    MortgageProduct, Borrower, Property, MortgageApplication, LoanApproval,
    MortgageLoan, RepaymentScheduleItem, Payment, Fee, MortgageInsurancePolicy,
    MortgageDocument, LeadSource, Campaign, FieldAgent, Lead, FieldVisit,
    FollowUp, CustomerFeedback, InterestRate, CollectionCase, Notification,
)
from .serializers import (
    MortgageProductSerializer, BorrowerSerializer, PropertySerializer,
    MortgageApplicationSerializer, LoanApprovalSerializer, MortgageLoanSerializer,
    RepaymentScheduleItemSerializer, PaymentSerializer, FeeSerializer,
    MortgageInsurancePolicySerializer, MortgageDocumentSerializer,
    LeadSourceSerializer, CampaignSerializer, FieldAgentSerializer, LeadSerializer,
    FieldVisitSerializer, FollowUpSerializer, CustomerFeedbackSerializer,
    InterestRateSerializer, CollectionCaseSerializer, NotificationSerializer,
)

DjangoFilterBackend = django_filters.rest_framework.DjangoFilterBackend
TAG = ["Mortgages"]
TAG_LEADS = ["Mortgages — Leads"]

TWO_DP = Decimal("0.01")


# ── Amortization ───────────────────────────────────────────────────────────────

def _dec(value, default="0"):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def monthly_installment(principal, annual_rate_pct, tenure_months):
    """Standard annuity payment. Falls back to straight-line when rate is 0."""
    p = _dec(principal)
    n = int(tenure_months or 0)
    if n <= 0:
        return Decimal("0.00")
    r = _dec(annual_rate_pct) / Decimal("1200")  # monthly rate as a fraction
    if r == 0:
        m = p / Decimal(n)
    else:
        factor = (Decimal(1) + r) ** n
        m = p * r * factor / (factor - Decimal(1))
    return m.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def build_amortization(principal, annual_rate_pct, tenure_months, start_date=None):
    """Return (installment, [rows]) for an annuity schedule."""
    p = _dec(principal)
    n = int(tenure_months or 0)
    inst = monthly_installment(p, annual_rate_pct, tenure_months)
    r = _dec(annual_rate_pct) / Decimal("1200")
    start = start_date or date.today()
    rows, balance = [], p
    for i in range(1, n + 1):
        interest = (balance * r).quantize(TWO_DP, rounding=ROUND_HALF_UP)
        principal_comp = inst - interest
        if i == n:  # final installment clears any rounding remainder
            principal_comp = balance
            inst_row = (principal_comp + interest).quantize(TWO_DP, rounding=ROUND_HALF_UP)
        else:
            inst_row = inst
        balance = (balance - principal_comp).quantize(TWO_DP, rounding=ROUND_HALF_UP)
        rows.append({
            "installment_no": i,
            "due_date": (start + timedelta(days=30 * i)).isoformat(),
            "payment_amount": str(inst_row),
            "principal_component": str(principal_comp.quantize(TWO_DP)),
            "interest_component": str(interest),
            "balance_after": str(max(balance, Decimal("0.00"))),
        })
    return inst, rows


# ── Generic CRUD factory ───────────────────────────────────────────────────────

def crud(model, serializer, filter_fields=(), tag=TAG, select=()):
    """Build (ListCreate, Detail) view classes for a model with shared config."""
    qs = model.objects.all()
    if select:
        qs = qs.select_related(*select)

    @extend_schema(tags=tag)
    class ListCreate(generics.ListCreateAPIView):
        permission_classes = [IsAuthenticated]
        serializer_class = serializer
        pagination_class = StandardPagination
        filter_backends = [DjangoFilterBackend]
        filterset_fields = list(filter_fields)
        queryset = qs

    @extend_schema(tags=tag)
    class Detail(generics.RetrieveUpdateDestroyAPIView):
        permission_classes = [IsAuthenticated]
        serializer_class = serializer
        queryset = qs

    ListCreate.__name__ = f"{model.__name__}ListCreateView"
    Detail.__name__ = f"{model.__name__}DetailView"
    return ListCreate, Detail


ProductListCreateView, ProductDetailView = crud(
    MortgageProduct, MortgageProductSerializer, ["product_type", "rate_type", "is_active"])
BorrowerListCreateView, BorrowerDetailView = crud(
    Borrower, BorrowerSerializer, ["branch", "risk_rating", "kyc_status", "employment_status"])
PropertyListCreateView, PropertyDetailView = crud(
    Property, PropertySerializer, ["property_type", "borrower"], select=("borrower",))
ApplicationListCreateView, ApplicationDetailView = crud(
    MortgageApplication, MortgageApplicationSerializer,
    ["status", "borrower", "product", "lead"], select=("borrower", "product"))
ApprovalListCreateView, ApprovalDetailView = crud(
    LoanApproval, LoanApprovalSerializer, ["application", "decision"])
LoanListCreateView, LoanDetailView = crud(
    MortgageLoan, MortgageLoanSerializer, ["status", "borrower", "product"],
    select=("borrower", "product", "application"))
ScheduleListCreateView, ScheduleDetailView = crud(
    RepaymentScheduleItem, RepaymentScheduleItemSerializer, ["loan", "is_paid"])
PaymentListCreateView, PaymentDetailView = crud(
    Payment, PaymentSerializer, ["loan", "method"], select=("loan",))
FeeListCreateView, FeeDetailView = crud(
    Fee, FeeSerializer, ["fee_type", "status", "application", "loan"])
InsuranceListCreateView, InsuranceDetailView = crud(
    MortgageInsurancePolicy, MortgageInsurancePolicySerializer, ["policy_type", "loan"],
    select=("loan",))
DocumentListCreateView, DocumentDetailView = crud(
    MortgageDocument, MortgageDocumentSerializer, ["doc_type", "borrower", "application"])
LeadSourceListCreateView, LeadSourceDetailView = crud(
    LeadSource, LeadSourceSerializer, ["is_active"], tag=TAG_LEADS)
CampaignListCreateView, CampaignDetailView = crud(
    Campaign, CampaignSerializer, ["is_active"], tag=TAG_LEADS)
FieldAgentListCreateView, FieldAgentDetailView = crud(
    FieldAgent, FieldAgentSerializer, ["team", "branch", "is_active"], tag=TAG_LEADS)
LeadListCreateView, LeadDetailView = crud(
    Lead, LeadSerializer, ["status", "branch", "source", "field_agent", "campaign"],
    tag=TAG_LEADS, select=("source", "field_agent", "interested_product"))
FieldVisitListCreateView, FieldVisitDetailView = crud(
    FieldVisit, FieldVisitSerializer, ["field_agent", "team"], tag=TAG_LEADS,
    select=("field_agent",))
FollowUpListCreateView, FollowUpDetailView = crud(
    FollowUp, FollowUpSerializer, ["lead", "interaction_type"], tag=TAG_LEADS)
FeedbackListCreateView, FeedbackDetailView = crud(
    CustomerFeedback, CustomerFeedbackSerializer, ["borrower", "lead", "rating"], tag=TAG_LEADS)


# ── CSV bulk upload ─────────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class ProductCsvUploadView(BaseCsvUploadView):
    serializer_class = MortgageProductSerializer


@extend_schema(tags=TAG)
class BorrowerCsvUploadView(BaseCsvUploadView):
    serializer_class = BorrowerSerializer


@extend_schema(tags=TAG)
class PaymentCsvUploadView(BaseCsvUploadView):
    serializer_class = PaymentSerializer


@extend_schema(tags=TAG_LEADS)
class LeadCsvUploadView(BaseCsvUploadView):
    serializer_class = LeadSerializer


@extend_schema(tags=TAG_LEADS)
class FieldVisitCsvUploadView(BaseCsvUploadView):
    serializer_class = FieldVisitSerializer


@extend_schema(tags=TAG_LEADS)
class FieldAgentCsvUploadView(BaseCsvUploadView):
    serializer_class = FieldAgentSerializer


# ── Pipeline actions ────────────────────────────────────────────────────────────

@extend_schema(tags=TAG_LEADS)
class LeadConvertView(APIView):
    """Convert a lead into a mortgage application; links both and flips status."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist:
            return Response({"detail": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
        if lead.converted_application_id:
            return Response({"detail": "Lead already converted.",
                             "application": lead.converted_application_id},
                            status=status.HTTP_400_BAD_REQUEST)

        borrower_id = request.data.get("borrower")
        if borrower_id:
            borrower = Borrower.objects.filter(pk=borrower_id).first()
        else:
            borrower = Borrower.objects.create(
                full_name=lead.full_name, phone=lead.phone, email=lead.email,
                branch=lead.branch,
                created_by=request.user if request.user.is_authenticated else None,
            )
        app = MortgageApplication.objects.create(
            borrower=borrower,
            product=lead.interested_product,
            lead=lead,
            amount_requested=lead.estimated_loan_amount or 0,
            purpose=lead.property_interest or "",
            status="submitted",
            submitted_at=timezone.now(),
        )
        lead.converted_application = app
        lead.status = "converted"
        lead.save(update_fields=["converted_application", "status", "updated_at"])
        return Response(MortgageApplicationSerializer(app).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAG)
class ApplicationApproveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            app = MortgageApplication.objects.get(pk=pk)
        except MortgageApplication.DoesNotExist:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        app.status = "approved"
        app.reviewed_by = request.user if request.user.is_authenticated else None
        app.decision_notes = request.data.get("comments", app.decision_notes)
        app.save(update_fields=["status", "reviewed_by", "decision_notes", "updated_at"])
        LoanApproval.objects.create(
            application=app,
            approver=request.user if request.user.is_authenticated else None,
            ltv=app.ltv_ratio, dti=app.dti_ratio,
            decision="approved", decision_date=date.today(),
            comments=request.data.get("comments", ""),
        )
        notify(getattr(app.borrower, "created_by", None), "approval",
               f"Application {app.application_ref} approved",
               f"{app.borrower.full_name}'s mortgage application was approved.",
               link="/mortgage-mgmt/approvals")
        return Response(MortgageApplicationSerializer(app).data)


@extend_schema(tags=TAG)
class ApplicationRejectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            app = MortgageApplication.objects.get(pk=pk)
        except MortgageApplication.DoesNotExist:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        app.status = "rejected"
        app.reviewed_by = request.user if request.user.is_authenticated else None
        app.decision_notes = request.data.get("comments", app.decision_notes)
        app.save(update_fields=["status", "reviewed_by", "decision_notes", "updated_at"])
        LoanApproval.objects.create(
            application=app,
            approver=request.user if request.user.is_authenticated else None,
            decision="rejected", decision_date=date.today(),
            comments=request.data.get("comments", ""),
        )
        return Response(MortgageApplicationSerializer(app).data)


@extend_schema(tags=TAG)
class ApplicationDisburseView(APIView):
    """Create the loan from an approved application and generate its schedule."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            app = MortgageApplication.objects.get(pk=pk)
        except MortgageApplication.DoesNotExist:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        if hasattr(app, "loan") and app.loan is not None:
            return Response({"detail": "Application already disbursed.", "loan": app.loan.pk},
                            status=status.HTTP_400_BAD_REQUEST)

        principal = _dec(request.data.get("principal") or app.amount_requested)
        rate = _dec(request.data.get("interest_rate")
                    or (app.product.interest_rate if app.product else 0))
        tenure = int(request.data.get("tenure_months") or app.tenure_months or 0)
        disb_date = date.today()

        inst, rows = build_amortization(principal, rate, tenure, disb_date)
        loan = MortgageLoan.objects.create(
            application=app, borrower=app.borrower, product=app.product,
            principal=principal, interest_rate=rate, tenure_months=tenure,
            disbursement_date=disb_date, monthly_installment=inst,
            outstanding_balance=principal,
            maturity_date=disb_date + timedelta(days=30 * tenure),
            status="active",
        )
        RepaymentScheduleItem.objects.bulk_create([
            RepaymentScheduleItem(
                loan=loan, installment_no=r["installment_no"], due_date=r["due_date"],
                payment_amount=r["payment_amount"], principal_component=r["principal_component"],
                interest_component=r["interest_component"], balance_after=r["balance_after"],
            ) for r in rows
        ])
        app.status = "disbursed"
        app.save(update_fields=["status", "updated_at"])
        notify(getattr(loan.borrower, "created_by", None), "disbursement",
               f"Loan {loan.loan_ref} disbursed",
               f"{loan.borrower.full_name}'s loan of KES {loan.principal} was disbursed.",
               link="/mortgage-finance/loans")
        return Response(MortgageLoanSerializer(loan).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAG)
class MortgageCalculatorView(APIView):
    """Stateless amortization preview — no persistence."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        principal = request.data.get("principal")
        rate = request.data.get("interest_rate") or request.data.get("annual_rate")
        tenure = request.data.get("tenure_months")
        if principal is None or tenure is None:
            return Response({"detail": "principal and tenure_months are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        inst, rows = build_amortization(principal, rate, tenure)
        total = sum(_dec(r["payment_amount"]) for r in rows)
        interest_total = total - _dec(principal)
        return Response({
            "principal": str(_dec(principal)),
            "interest_rate": str(_dec(rate)),
            "tenure_months": int(tenure),
            "monthly_installment": str(inst),
            "total_payable": str(total.quantize(TWO_DP)),
            "total_interest": str(interest_total.quantize(TWO_DP)),
            "schedule": rows,
        })


# ── Aggregations ────────────────────────────────────────────────────────────────

@extend_schema(tags=TAG)
class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        loans = MortgageLoan.objects.all()
        active = loans.filter(status="active")
        today = date.today()
        soon = today + timedelta(days=30)
        return Response({
            "active_loans": active.count(),
            "total_loans": loans.count(),
            "outstanding_balance": str(active.aggregate(s=Sum("outstanding_balance"))["s"] or 0),
            "disbursed_principal": str(loans.aggregate(s=Sum("principal"))["s"] or 0),
            "interest_earned": str(
                Payment.objects.aggregate(s=Sum("interest_paid"))["s"] or 0),
            "repayments_due_30d": RepaymentScheduleItem.objects.filter(
                is_paid=False, due_date__gte=today, due_date__lte=soon).count(),
            "overdue_installments": RepaymentScheduleItem.objects.filter(
                is_paid=False, due_date__lt=today).count(),
            "applications_by_status": {
                row["status"]: row["n"] for row in
                MortgageApplication.objects.values("status").annotate(n=Count("id"))
            },
            "total_borrowers": Borrower.objects.count(),
            "total_applications": MortgageApplication.objects.count(),
        })


@extend_schema(tags=TAG_LEADS)
class LeadFunnelView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        counts = {row["status"]: row["n"]
                  for row in Lead.objects.values("status").annotate(n=Count("id"))}
        ordered = [{"status": key, "label": label, "count": counts.get(key, 0)}
                   for key, label in Lead.STATUS]
        total = sum(counts.values())
        converted = counts.get("converted", 0)
        return Response({
            "total_leads": total,
            "converted": converted,
            "conversion_rate": round((converted / total * 100) if total else 0, 2),
            "funnel": ordered,
        })


@extend_schema(tags=TAG_LEADS)
class FieldLeaderboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = []
        for agent in FieldAgent.objects.all():
            agent_leads = Lead.objects.filter(field_agent=agent)
            visits = FieldVisit.objects.filter(field_agent=agent)
            total = agent_leads.count()
            converted = agent_leads.filter(status="converted").count()
            rows.append({
                "field_agent": agent.id,
                "name": agent.name,
                "team": agent.team,
                "branch": agent.branch,
                "leads": total,
                "converted": converted,
                "conversion_rate": round((converted / total * 100) if total else 0, 2),
                "visits": visits.count(),
                "customers_onboarded": visits.aggregate(s=Sum("customers_onboarded"))["s"] or 0,
                "applications_started": visits.aggregate(s=Sum("applications_started"))["s"] or 0,
            })
        rows.sort(key=lambda r: (r["converted"], r["leads"]), reverse=True)
        return Response(rows)


# ══ Notifications helper ═════════════════════════════════════════════════════════

def notify(user, ntype, title, body="", link=""):
    """Create an in-app notification (no-op if user is anonymous/None)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return Notification.objects.create(
        user=user, type=ntype, title=title, body=body, link=link)


def _bucket(days):
    if days <= 0:
        return "current"
    if days <= 30:
        return "1-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


# ══ Interest Rate Management ═════════════════════════════════════════════════════

@extend_schema(tags=TAG)
class InterestRateListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InterestRateSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["rate_type", "is_active"]
    queryset = InterestRate.objects.all()

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(created_by=user if user.is_authenticated else None)


@extend_schema(tags=TAG)
class InterestRateDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InterestRateSerializer
    queryset = InterestRate.objects.all()


# ══ Collections & Recovery ═══════════════════════════════════════════════════════

CollectionCaseListCreateView, CollectionCaseDetailView = crud(
    CollectionCase, CollectionCaseSerializer,
    ["status", "assigned_to", "loan"],
    select=("loan", "loan__borrower", "assigned_to"))


@extend_schema(tags=TAG)
class CollectionsSummaryView(APIView):
    """Portfolio-at-risk, arrears buckets, and the overdue-loan list."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = date.today()
        buckets = {b: {"count": 0, "amount": Decimal("0")}
                   for b in ("1-30", "31-60", "61-90", "90+")}
        overdue_rows = []
        total_outstanding = Decimal("0")
        at_risk_outstanding = Decimal("0")

        loans = MortgageLoan.objects.filter(status="active").select_related("borrower")
        for loan in loans:
            total_outstanding += _dec(loan.outstanding_balance)
            overdue = loan.schedule.filter(is_paid=False, due_date__lt=today)
            if not overdue.exists():
                continue
            amount = overdue.aggregate(s=Sum("payment_amount"))["s"] or Decimal("0")
            earliest = overdue.order_by("due_date").first().due_date
            days = (today - earliest).days if earliest else 0
            bucket = _bucket(days)
            at_risk_outstanding += _dec(loan.outstanding_balance)
            if bucket in buckets:
                buckets[bucket]["count"] += 1
                buckets[bucket]["amount"] += _dec(amount)
            overdue_rows.append({
                "loan_ref": loan.loan_ref,
                "borrower": loan.borrower.full_name if loan.borrower_id else None,
                "outstanding_balance": str(loan.outstanding_balance),
                "amount_overdue": str(amount),
                "days_overdue": days,
                "bucket": bucket,
            })

        overdue_rows.sort(key=lambda r: r["days_overdue"], reverse=True)
        par = (at_risk_outstanding / total_outstanding * 100) if total_outstanding else Decimal("0")
        return Response({
            "par_pct": str(par.quantize(TWO_DP)),
            "total_outstanding": str(total_outstanding.quantize(TWO_DP)),
            "at_risk_outstanding": str(at_risk_outstanding.quantize(TWO_DP)),
            "overdue_loans": len(overdue_rows),
            "open_cases": CollectionCase.objects.exclude(
                status__in=["recovered", "written_off"]).count(),
            "buckets": [{"bucket": b, "count": v["count"], "amount": str(v["amount"])}
                        for b, v in buckets.items()],
            "overdue_list": overdue_rows[:50],
        })


# ══ Reports & Analytics ══════════════════════════════════════════════════════════

@extend_schema(tags=TAG)
class ReportsView(APIView):
    """Aggregated report datasets for charts and CSV export."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        loans = MortgageLoan.objects.all()
        active = loans.filter(status="active")

        disbursements = [
            {"month": row["m"].strftime("%Y-%m") if row["m"] else "—",
             "amount": str(row["amt"] or 0), "count": row["n"]}
            for row in loans.exclude(disbursement_date__isnull=True)
            .annotate(m=TruncMonth("disbursement_date"))
            .values("m").annotate(amt=Sum("principal"), n=Count("id")).order_by("m")
        ]

        by_product = [
            {"product": row["product__name"] or "—",
             "outstanding": str(row["bal"] or 0), "count": row["n"]}
            for row in active.values("product__name")
            .annotate(bal=Sum("outstanding_balance"), n=Count("id")).order_by("-bal")
        ]

        by_branch = [
            {"branch": row["borrower__branch"] or "—",
             "outstanding": str(row["bal"] or 0), "count": row["n"]}
            for row in active.values("borrower__branch")
            .annotate(bal=Sum("outstanding_balance"), n=Count("id")).order_by("-bal")
        ]

        applications_by_status = [
            {"status": row["status"], "count": row["n"]}
            for row in MortgageApplication.objects.values("status")
            .annotate(n=Count("id")).order_by("-n")
        ]

        sched = RepaymentScheduleItem.objects
        repayment = {
            "installments_paid": sched.filter(is_paid=True).count(),
            "installments_unpaid": sched.filter(is_paid=False).count(),
            "total_collected": str(Payment.objects.aggregate(s=Sum("amount"))["s"] or 0),
            "principal_collected": str(Payment.objects.aggregate(s=Sum("principal_paid"))["s"] or 0),
            "interest_collected": str(Payment.objects.aggregate(s=Sum("interest_paid"))["s"] or 0),
        }

        return Response({
            "disbursements_by_month": disbursements,
            "portfolio_by_product": by_product,
            "portfolio_by_branch": by_branch,
            "applications_by_status": applications_by_status,
            "repayment_performance": repayment,
        })


# ══ Notifications ════════════════════════════════════════════════════════════════

@extend_schema(tags=TAG)
class NotificationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_read", "type"]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


@extend_schema(tags=TAG)
class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        updated = Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
        if not updated:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": "marked read"})


@extend_schema(tags=TAG)
class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        n = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({"detail": "marked all read", "count": n})


@extend_schema(tags=TAG)
class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "unread": Notification.objects.filter(user=request.user, is_read=False).count()
        })
