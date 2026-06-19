from django.urls import path
from . import views as v

urlpatterns = [
    path("briefs/<int:pk>/download/", v.ClientBriefDownloadView.as_view()),
    path("briefs/<int:pk>/",          v.ClientBriefDetailView.as_view()),
    path("briefs/",                   v.ClientBriefListCreateView.as_view()),
]
