from django.urls import path
from . import views

urlpatterns = [
    path("applications/", views.RightsIssueApplicationListCreateView.as_view()),
    path("applications/<int:pk>/", views.RightsIssueApplicationDetailView.as_view()),
    path("summary/", views.RightsIssueSummaryView.as_view()),

    # Rights-uptake register (security_detail) — GET list + CSV update.
    # `csvupload` intentionally has no trailing slash (matches the frontend).
    path("update-security-detail-image-registras/", views.SecurityDetailImageRegistrasListView.as_view()),
    path("update-security-detail-image-registras/csvupload", views.SecurityDetailImageRegistrasCsvUpdateView.as_view()),
]
