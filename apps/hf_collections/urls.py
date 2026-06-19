from django.urls import path
from . import views

urlpatterns = [
    path("collections/", views.CollectionListCreateView.as_view()),
    path("collections/search/", views.CollectionSearchView.as_view()),
    path("collections/<int:pk>/", views.CollectionDetailView.as_view()),
]
