from django.urls import path
from . import views

urlpatterns = [
    # ── Frontend contract: the portfolio-management-frontend exco hooks expect
    # `initiatives/` to be the STRATEGIC hierarchy (Owner → Thrust → Initiative →
    # Milestone), mirroring the old backend. So these paths drive the hierarchy. ──
    path("excoowners/", views.StrategicExcoOwnerListCreateView.as_view()),
    path("excoowners/<int:pk>/", views.StrategicExcoOwnerDetailView.as_view()),

    path("thrusts/", views.StrategicThrustListCreateView.as_view()),
    path("thrusts/<int:pk>/", views.StrategicThrustDetailView.as_view()),

    path("initiatives/", views.StrategicInitiativeListCreateView.as_view()),
    # No trailing slash on the milestones sub-path (matches the frontend hook).
    path("initiatives/<int:initiative_id>/milestones", views.StrategicInitiativeMilestonesView.as_view()),
    path("initiatives/<int:pk>/", views.StrategicInitiativeDetailView.as_view()),

    path("milestones/", views.StrategicMilestoneListCreateView.as_view()),
    path("milestones/<int:pk>/", views.StrategicMilestoneDetailView.as_view()),
    path("initiative_milestones/<int:milestone_id>/history/", views.StrategicMilestoneHistoryView.as_view()),

    # ── Dashboard summaries (exact frontend paths) ──
    path("summary_of_thrust_by_initiatives/", views.SummaryOfThrustByInitiatives.as_view()),
    path("SummaryOfInitiativesByQuarters/", views.SummaryOfInitiativesByQuarters.as_view()),
    path("SummaryInitiativesByPrimaryOwnership/", views.SummaryInitiativesByPrimaryOwnership.as_view()),
    path("SummaryInitiativesByPrimaryOwnershipPerThrust/", views.SummaryInitiativesByPrimaryOwnershipPerThrust.as_view()),
    path("SummaryInitiativesByPrimaryOwnershipPerThrustOverdue/", views.SummaryInitiativesByPrimaryOwnershipPerThrustOverdue.as_view()),
    path("SummaryInitiativesByPrimaryOwnershipPerThrustReview/", views.SummaryInitiativesByPrimaryOwnershipPerThrustReview.as_view()),
    path("SummaryAvgApprovedProportion/", views.SummaryAvgApprovedProportion.as_view()),

    # ── Flat initiative tracker (the new-backend redesign) — moved off
    # `initiatives/` so it no longer clashes with the hierarchy above. ──
    path("flat_initiatives/", views.ExcoInitiativeListCreateView.as_view()),
    path("flat_initiatives/<int:pk>/", views.ExcoInitiativeDetailView.as_view()),
]
