from django.urls import path

from . import views

urlpatterns = [
    path("summary/", views.SummaryView.as_view()),
    path("transactions/", views.TransactionListView.as_view()),
    path("refresh/", views.RefreshView.as_view()),
]
