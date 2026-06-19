from django.urls import path
from . import views

urlpatterns = [
    path("", views.InsightListView.as_view()),
    path("<int:pk>/", views.InsightDetailView.as_view()),
]
