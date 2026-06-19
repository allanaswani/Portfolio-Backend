from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from core.pagination import StandardPagination
import django_filters.rest_framework

from .models import ExcoInitiative
from .serializers import ExcoInitiativeSerializer


@extend_schema(tags=["ExCo Initiatives"])
class ExcoInitiativeListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ExcoInitiativeSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["status", "priority", "owner", "sponsor"]
    queryset = ExcoInitiative.objects.all()


@extend_schema(tags=["ExCo Initiatives"])
class ExcoInitiativeDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ExcoInitiativeSerializer
    queryset = ExcoInitiative.objects.all()
