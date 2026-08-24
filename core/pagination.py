from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 500


class TotalPagesPagination(PageNumberPagination):
    """PageNumberPagination that also returns ``total_pages`` (old-backend contract)."""

    page_size = 10
    page_size_query_param = "page_size"
    # Matches StandardPagination so a full-table Export crawls in 500-row pages.
    # The reallocation base is ~333k rows; at the old ceiling of 100 that was
    # 3,330 sequential requests. The default stays 10 for normal page views.
    max_page_size = 500

    def get_paginated_response(self, data):
        return Response({
            "count": self.page.paginator.count,
            "total_pages": self.page.paginator.num_pages,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        })


class LargePagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000
