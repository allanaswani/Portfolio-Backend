from django.urls import path
from . import views

urlpatterns = [
    path("loan-repayments/", views.LoanRepaymentsListView.as_view()),
    path("loan-repayments/<int:pk>/", views.LoanRepaymentsDetailView.as_view()),
]
