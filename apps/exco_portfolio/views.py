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
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.pagination import StandardPagination
from core.permissions import InGroup
from apps.gceo_dashboard.views import CeoFixedDepositListView, CeoCustomersView
from apps.portfolio.models import Loans, Prospects, Feedback
from apps.portfolio.feedback_names import FeedbackNamesMixin
from apps.portfolio.serializers import NamedFeedbackSerializer
from apps.portfolio.serializers import (
    LoansSerializer, ProspectsSerializer, FeedbackSerializer,
)
from services.arrears_managers import LoansArrearsSummaryManager

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
    """Whole-bank arrears book — RM view is filtered by account_officer.

    Ordered by primary key, which matters more here than it looks. The queryset
    had no ordering at all, and an unordered queryset paginated with
    LIMIT/OFFSET gives Postgres no obligation to arrange rows the same way
    twice. A client that walks all 800-odd pages of the arrears book therefore
    collected some loans more than once and missed others, so anything summed
    from the crawled list came out wrong — and wrong by a different amount on
    each reload. Django warns about exactly this (UnorderedObjectListWarning).
    """

    permission_classes = [ExcoAccess]
    serializer_class = LoansSerializer
    pagination_class = StandardPagination
    queryset = Loans.objects.filter(days_in_arrears__gt=0).order_by("id")


@extend_schema(tags=["Exco Dashboard"])
class ExcoLoansArrearsSummaryView(APIView):
    """Whole-bank arrears totals, computed in the database.

    The Exco arrears KPI cards used to be summed in the browser from the list
    endpoint above. That could never be right: the frontend's page crawler stops
    at 500 pages of 10, so it saw at most 5,000 of the ~8,200 accounts actually
    in arrears, and the unordered pagination above shuffled which 5,000.

    This is the same whole-bank query the CEO dashboard uses. It reads `loans`
    directly with no joins, so there is nothing to fan out and nothing to
    truncate — it is the ground truth the cards should have been showing.
    """

    permission_classes = [ExcoAccess]

    def get(self, request):
        return Response(LoansArrearsSummaryManager().high_level_summary())


@extend_schema(tags=["Exco Dashboard"])
class ExcoProspectsListView(generics.ListAPIView):
    """Whole-bank prospects — RM view is filtered by sales_code."""

    permission_classes = [ExcoAccess]
    serializer_class = ProspectsSerializer
    pagination_class = StandardPagination
    queryset = Prospects.objects.all()


@extend_schema(tags=["Exco Dashboard"])
class ExcoFeedbackListView(FeedbackNamesMixin, generics.ListAPIView):
    """Whole-bank customer feedback — RM view is filtered by sales_code."""

    permission_classes = [ExcoAccess]
    serializer_class = NamedFeedbackSerializer
    pagination_class = StandardPagination
    queryset = Feedback.objects.all()
