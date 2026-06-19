from django.urls import path
from . import views

urlpatterns = [
    path("applications/", views.RightsIssueApplicationListCreateView.as_view()),
    path("applications/<int:pk>/", views.RightsIssueApplicationDetailView.as_view()),
    path("summary/", views.RightsIssueSummaryView.as_view()),
]
