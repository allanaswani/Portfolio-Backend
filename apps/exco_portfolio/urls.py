"""Exco portfolio dashboard routes (mounted at ``exco/``).

Bank-wide scope. Fixed-deposits and allocated-customers reuse the CEO dashboard's
existing whole-bank views; the other three are defined in this app.
"""

from django.urls import path

from . import views

urlpatterns = [
    # Bank-wide CEO views, gated to the executive groups (see views.py).
    path("fixed_deposits/list/", views.ExcoFixedDepositListView.as_view()),
    path("customers_list_allocated/", views.ExcoCustomersView.as_view()),
    # Whole-bank equivalents of the RM-scoped portfolio views.
    path("customer_feedback_list/", views.ExcoFeedbackListView.as_view()),
    path("loans-arrears/list/", views.ExcoLoansArrearsListView.as_view()),
    path("prospects/", views.ExcoProspectsListView.as_view()),
]
