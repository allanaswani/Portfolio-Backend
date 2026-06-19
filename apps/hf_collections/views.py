from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from core.pagination import StandardPagination
from .models import Collection
from .serializers import CollectionSerializer
import django_filters.rest_framework


@extend_schema(tags=["Collections"])
class CollectionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CollectionSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "collection_officer_code", "collection_status", "recording_date"]
    queryset = Collection.objects.all()


@extend_schema(tags=["Collections"])
class CollectionDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CollectionSerializer
    queryset = Collection.objects.all()


@extend_schema(tags=["Collections"])
class CollectionSearchView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CollectionSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["cust_id", "loan_account_no", "collection_officer_code", "collection_status"]
    queryset = Collection.objects.all()
