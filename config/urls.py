from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

urlpatterns = [
    # Admin — same path as old backend
    path("lexus/", admin.site.urls),
    path("api-auth/", include("rest_framework.urls")),

    # API Schema
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # Mirrored app URLs — exact same prefixes as old backend
    path("portfolio/", include("apps.portfolio.urls")),
    path("ceo/", include("apps.gceo_dashboard.urls")),
    path("auth/", include("apps.authentication.urls")),
    path("tl_portfolio/", include("apps.tl_portfolio.urls")),
    path("branch_portfolio/", include("apps.branch_portfolio.urls")),
    path("hf_collections/", include("apps.hf_collections.urls")),
    path("collections_tl/", include("apps.collections_team_leaders.urls")),
    path("hfdi/", include("apps.hfdi.urls")),
    path("staff_management/", include("apps.staff_management.urls")),
    path("exco_innitiatives/", include("apps.exco_innitiatives.urls")),
    path("hf_rights_issue/", include("apps.hf_rights_issue.urls")),
    path("portfolio_management_enrichment/", include("apps.portfolio_management_enrichment.urls")),
    path("mortgages/", include("apps.mortgages.urls")),
    path("client_briefs/", include("apps.client_briefs.urls")),

    # New feature APIs (v1 prefix for new frontend)
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/insights/", include("apps.insights.urls")),
    path("api/v1/agent/", include("apps.agent.urls")),
    path("api/v1/slideshow/", include("apps.slideshow.urls")),

    # Password reset
    path("auth/api/password_reset/", include("django_rest_passwordreset.urls", namespace="password_reset")),
]