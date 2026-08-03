from django.urls import path
from . import views

urlpatterns = [
    path("targets/",            views.TargetListCreateView.as_view()),
    path("targets/<int:pk>/",   views.TargetDetailView.as_view()),
    path("targets/matrix/",     views.TargetsMatrixView.as_view()),
    path("exec-brief/",         views.ExecBriefView.as_view()),
]
