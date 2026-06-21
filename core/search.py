"""
Reusable dynamic per-column search.

Ported from the old backend's ``*SearchAPIView`` pattern, where the search
endpoints let the UI filter a table by *any* column shown in the interface:
every query param whose name matches a model field is applied as a
case-insensitive partial match (``icontains``), AND-combined.

Subclass and set ``serializer_class`` + ``search_model`` (or override
``get_base_queryset``). Pagination defaults to ``StandardPagination``.
"""
from django.db.models import Q
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from core.pagination import StandardPagination


class DynamicColumnSearchListView(generics.ListAPIView):
    """List view that filters by any query param matching a model field name."""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    search_model = None  # set by subclass
    # Params that control pagination/format rather than filtering.
    IGNORED_PARAMS = {"page", "page_size", "format", "ordering"}

    def get_base_queryset(self):
        return self.search_model.objects.all()

    def get_queryset(self):
        queryset = self.get_base_queryset()
        field_names = {f.name for f in self.search_model._meta.get_fields()}
        conditions = Q()
        for param, value in self.request.query_params.items():
            if param in self.IGNORED_PARAMS or param not in field_names:
                continue
            conditions &= Q(**{f"{param}__icontains": value})
        return queryset.filter(conditions)
