from django.urls import path
from . import views

urlpatterns = [
    path("customer_enrichment/", views.CustomerEnrichmentListCreateView.as_view()),
    path("customer_enrichment/<int:pk>/", views.CustomerEnrichmentDetailView.as_view()),
    path("rm_targets/", views.RmTargetListCreateView.as_view()),
    path("rm_targets/<int:pk>/", views.RmTargetDetailView.as_view()),
]
