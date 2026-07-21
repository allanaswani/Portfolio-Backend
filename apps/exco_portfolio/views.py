"""Exco portfolio dashboard — bank-wide (whole-bank) list views.

The old backend never shipped an ``exco`` app (its ``exco/`` mount was a
commented-out stub), so there is nothing to port here. The Exco persona is an
executive view, so these endpoints return whole-bank data: the same querysets as
the RM-scoped ``portfolio`` views but without the ``sales_code`` filter — the
executive analogue the CEO dashboard already uses (``.objects.all()``).

Fixed-deposits and allocated-customers reuse the CEO views directly (see
``urls.py``); the three below have no bank-wide equivalent yet, so they are
defined here.
"""

from rest_framework import generics
from drf_spectacular.utils import extend_schema

from core.pagination import StandardPagination
from core.permissions import InGroup
from apps.gceo_dashboard.views import CeoFixedDepositListView, CeoCustomersView
from apps.portfolio.models import Loans, Prospects, Feedback
from apps.portfolio.serializers import (
    LoansSerializer, ProspectsSerializer, FeedbackSerializer,
)

# Role gate: bank-wide executive data, so restrict to the executive groups
# (superusers are always allowed by the InGroup factory). Applied here rather
# than on the CEO views so the open `ceo/` dashboard is unaffected.
ExcoAccess = InGroup("exco", "ceo")


@extend_schema(tags=["Exco Dashboard"])
class ExcoFixedDepositListView(CeoFixedDepositListView):
    """Bank-wide fixed deposits — CEO view, gated to the executive groups."""

    permission_classes = [ExcoAccess]


@extend_schema(tags=["Exco Dashboard"])
class ExcoCustomersView(CeoCustomersView):
    """Bank-wide allocated customers — CEO view, gated to the executive groups."""

    permission_classes = [ExcoAccess]


@extend_schema(tags=["Exco Dashboard"])
class ExcoLoansArrearsListView(generics.ListAPIView):
    """Whole-bank arrears book — RM view is filtered by account_officer."""

    permission_classes = [ExcoAccess]
    serializer_class = LoansSerializer
    pagination_class = StandardPagination
    queryset = Loans.objects.filter(days_in_arrears__gt=0)


@extend_schema(tags=["Exco Dashboard"])
class ExcoProspectsListView(generics.ListAPIView):
    """Whole-bank prospects — RM view is filtered by sales_code."""

    permission_classes = [ExcoAccess]
    serializer_class = ProspectsSerializer
    pagination_class = StandardPagination
    queryset = Prospects.objects.all()


@extend_schema(tags=["Exco Dashboard"])
class ExcoFeedbackListView(generics.ListAPIView):
    """Whole-bank customer feedback — RM view is filtered by sales_code."""

    permission_classes = [ExcoAccess]
    serializer_class = FeedbackSerializer
    pagination_class = StandardPagination
    queryset = Feedback.objects.all()
