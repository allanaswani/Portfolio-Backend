from django.urls import path
from . import views as v

urlpatterns = [
    # ── Aggregations / stateless ──────────────────────────────────────────────
    path("dashboard/",          v.DashboardView.as_view()),
    path("calculator/",         v.MortgageCalculatorView.as_view()),
    path("leads/funnel/",       v.LeadFunnelView.as_view()),
    path("field/leaderboard/",  v.FieldLeaderboardView.as_view()),

    # ── Products ──────────────────────────────────────────────────────────────
    path("products/upload-csv/", v.ProductCsvUploadView.as_view()),
    path("products/<int:pk>/",   v.ProductDetailView.as_view()),
    path("products/",            v.ProductListCreateView.as_view()),

    # ── Borrowers ─────────────────────────────────────────────────────────────
    path("borrowers/upload-csv/", v.BorrowerCsvUploadView.as_view()),
    path("borrowers/<int:pk>/",   v.BorrowerDetailView.as_view()),
    path("borrowers/",            v.BorrowerListCreateView.as_view()),

    # ── Properties ────────────────────────────────────────────────────────────
    path("properties/<int:pk>/", v.PropertyDetailView.as_view()),
    path("properties/",          v.PropertyListCreateView.as_view()),

    # ── Applications (+ pipeline actions) ─────────────────────────────────────
    path("applications/<int:pk>/approve/",  v.ApplicationApproveView.as_view()),
    path("applications/<int:pk>/reject/",   v.ApplicationRejectView.as_view()),
    path("applications/<int:pk>/disburse/", v.ApplicationDisburseView.as_view()),
    path("applications/<int:pk>/",          v.ApplicationDetailView.as_view()),
    path("applications/",                   v.ApplicationListCreateView.as_view()),

    # ── Approvals ─────────────────────────────────────────────────────────────
    path("approvals/<int:pk>/", v.ApprovalDetailView.as_view()),
    path("approvals/",          v.ApprovalListCreateView.as_view()),

    # ── Loans + repayment schedule ────────────────────────────────────────────
    path("loans/<int:pk>/", v.LoanDetailView.as_view()),
    path("loans/",          v.LoanListCreateView.as_view()),
    path("schedule/<int:pk>/", v.ScheduleDetailView.as_view()),
    path("schedule/",          v.ScheduleListCreateView.as_view()),

    # ── Payments ──────────────────────────────────────────────────────────────
    path("payments/upload-csv/", v.PaymentCsvUploadView.as_view()),
    path("payments/<int:pk>/",   v.PaymentDetailView.as_view()),
    path("payments/",            v.PaymentListCreateView.as_view()),

    # ── Fees & insurance ──────────────────────────────────────────────────────
    path("fees/<int:pk>/", v.FeeDetailView.as_view()),
    path("fees/",          v.FeeListCreateView.as_view()),
    path("insurance/<int:pk>/", v.InsuranceDetailView.as_view()),
    path("insurance/",          v.InsuranceListCreateView.as_view()),

    # ── Documents (metadata only) ─────────────────────────────────────────────
    path("documents/<int:pk>/", v.DocumentDetailView.as_view()),
    path("documents/",          v.DocumentListCreateView.as_view()),

    # ══ Leads / field-onboarding CRM ══════════════════════════════════════════
    path("lead-sources/<int:pk>/", v.LeadSourceDetailView.as_view()),
    path("lead-sources/",          v.LeadSourceListCreateView.as_view()),
    path("campaigns/<int:pk>/", v.CampaignDetailView.as_view()),
    path("campaigns/",          v.CampaignListCreateView.as_view()),
    path("field-agents/upload-csv/", v.FieldAgentCsvUploadView.as_view()),
    path("field-agents/<int:pk>/",   v.FieldAgentDetailView.as_view()),
    path("field-agents/",            v.FieldAgentListCreateView.as_view()),

    path("leads/upload-csv/",      v.LeadCsvUploadView.as_view()),
    path("leads/<int:pk>/convert/", v.LeadConvertView.as_view()),
    path("leads/<int:pk>/",        v.LeadDetailView.as_view()),
    path("leads/",                 v.LeadListCreateView.as_view()),

    path("field-visits/upload-csv/", v.FieldVisitCsvUploadView.as_view()),
    path("field-visits/<int:pk>/",   v.FieldVisitDetailView.as_view()),
    path("field-visits/",            v.FieldVisitListCreateView.as_view()),

    path("follow-ups/<int:pk>/", v.FollowUpDetailView.as_view()),
    path("follow-ups/",          v.FollowUpListCreateView.as_view()),
    path("feedback/<int:pk>/", v.FeedbackDetailView.as_view()),
    path("feedback/",          v.FeedbackListCreateView.as_view()),

    # ── Interest Rate Management ──────────────────────────────────────────────
    path("interest-rates/<int:pk>/", v.InterestRateDetailView.as_view()),
    path("interest-rates/",          v.InterestRateListCreateView.as_view()),

    # ── Collections & Recovery ────────────────────────────────────────────────
    path("collections/summary/",      v.CollectionsSummaryView.as_view()),
    path("collection-cases/<int:pk>/", v.CollectionCaseDetailView.as_view()),
    path("collection-cases/",          v.CollectionCaseListCreateView.as_view()),

    # ── Reports & Analytics ───────────────────────────────────────────────────
    path("reports/", v.ReportsView.as_view()),

    # ── Notifications ─────────────────────────────────────────────────────────
    path("notifications/unread-count/", v.NotificationUnreadCountView.as_view()),
    path("notifications/read-all/",     v.NotificationMarkAllReadView.as_view()),
    path("notifications/<int:pk>/read/", v.NotificationMarkReadView.as_view()),
    path("notifications/",              v.NotificationListView.as_view()),
]
