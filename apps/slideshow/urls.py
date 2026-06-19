from django.urls import path
from . import views

urlpatterns = [
    path("", views.SlideListView.as_view()),
    path("refresh/", views.TriggerSlideRefreshView.as_view()),
    path("<int:pk>/", views.SlideDetailView.as_view()),
]
