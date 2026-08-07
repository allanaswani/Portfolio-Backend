from django.urls import path

from . import views as v

urlpatterns = [
    # Aggregations / roster
    path("stats/", v.ReferralStatsView.as_view()),
    path("telesales-agents/", v.TelesalesAgentsView.as_view()),
    path("departments/", v.ReferralDepartmentsView.as_view()),

    # Pipeline actions (specific routes before the <pk> catch-all)
    path("<int:pk>/allocate/", v.ReferralAllocateView.as_view()),
    path("<int:pk>/status/", v.ReferralStatusView.as_view()),

    # CRUD
    path("<int:pk>/", v.ReferralDetailView.as_view()),
    path("", v.ReferralListCreateView.as_view()),
]
