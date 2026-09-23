from django.urls import path
from . import views

urlpatterns = [
    path("",                   views.SurfaceListCreateView.as_view()),
    path("generate/",          views.SurfaceGenerateView.as_view()),
    path("<int:pk>/",          views.SurfaceDetailView.as_view()),
    path("<int:pk>/data/",     views.SurfaceDataView.as_view()),
]
