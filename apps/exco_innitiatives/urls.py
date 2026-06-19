from django.urls import path
from . import views

urlpatterns = [
    path("initiatives/", views.ExcoInitiativeListCreateView.as_view()),
    path("initiatives/<int:pk>/", views.ExcoInitiativeDetailView.as_view()),
]
