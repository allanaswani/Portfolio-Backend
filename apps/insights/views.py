from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination
import django_filters.rest_framework

from .models import Insight
from .serializers import InsightSerializer


@extend_schema(tags=["Insights"])
class InsightListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InsightSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["category", "severity", "segment", "branch", "is_active"]
    queryset = Insight.objects.filter(is_active=True)


@extend_schema(tags=["Insights"])
class InsightDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InsightSerializer
    queryset = Insight.objects.all()
