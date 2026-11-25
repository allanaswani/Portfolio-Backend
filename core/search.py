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
    """List view that filters by any query param matching a model field name.

    ``?download=csv`` / ``?download=xlsx`` returns the WHOLE filtered list as
    one file, written from the database. Export used to crawl the list a page
    at a time in the browser: the customer allocation base is 365,278 rows
    at 100 a page, 3,653 requests one after another, and Portfolio
    Reallocation's Export sat on "Preparing..." (25 Nov 2026)."""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    search_model = None  # set by subclass
    # Params that control pagination/format rather than filtering.
    IGNORED_PARAMS = {"page", "page_size", "format", "ordering", "download"}

    def list(self, request, *args, **kwargs):
        kind = str(request.query_params.get("download") or "").lower()
        if kind in ("csv", "xlsx"):
            return self.download(kind)
        return super().list(request, *args, **kwargs)

    def download_columns(self):
        """The columns the list shows (its serializer's) that are plain model
        fields, in the serializer's order."""
        model_fields = {f.name for f in self.search_model._meta.concrete_fields}
        model_fields |= {f.attname for f in self.search_model._meta.concrete_fields}
        names = list(self.get_serializer().fields.keys())
        cols = [n for n in names if n in model_fields]
        return cols or [f.name for f in self.search_model._meta.concrete_fields]

    def download(self, kind):
        import datetime
        import decimal

        from django.http import StreamingHttpResponse

        cols = self.download_columns()
        rows = self.filter_queryset(self.get_queryset()).values_list(*cols).iterator(
            chunk_size=5000)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        name = f"{self.search_model.__name__}_{stamp}.{kind}"
        heads = [c.replace("_", " ").title() for c in cols]

        def plain(v):
            if isinstance(v, decimal.Decimal):
                return float(v)
            if isinstance(v, datetime.datetime) and v.tzinfo is not None:
                return v.replace(tzinfo=None)
            return v

        if kind == "csv":
            import csv

            class Echo:
                def write(self, value):
                    return value

            writer = csv.writer(Echo())

            def stream():
                yield "﻿"                     # Excel reads it as UTF-8
                yield writer.writerow(heads)
                for row in rows:
                    yield writer.writerow(["" if v is None else v for v in row])

            response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
        else:
            import tempfile

            from openpyxl import Workbook

            book = Workbook(write_only=True)
            sheet = book.create_sheet("Data")
            sheet.append(heads)
            for row in rows:
                sheet.append([plain(v) for v in row])
            handle = tempfile.TemporaryFile()
            book.save(handle)
            handle.seek(0)

            def stream():
                try:
                    while True:
                        chunk = handle.read(1 << 20)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    handle.close()

            response = StreamingHttpResponse(
                stream(), content_type="application/vnd.openxmlformats-"
                                       "officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

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
