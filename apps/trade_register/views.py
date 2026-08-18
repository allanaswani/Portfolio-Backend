"""Trade Register API — CRUD for entries, plus the dropdown/reference helpers
the form needs (products, RM/DSR lookup, live reference preview)."""

from datetime import datetime

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from . import references as refs
from .models import TradeProduct, TradeRegisterEntry
from .serializers import TradeProductSerializer, TradeRegisterEntrySerializer

TAG = ["Trade Register"]


@extend_schema(tags=TAG)
class TradeProductListView(generics.ListAPIView):
    """Active products for the Product Type dropdown (each carries its code)."""

    permission_classes = [IsAuthenticated]
    serializer_class = TradeProductSerializer
    pagination_class = None
    queryset = TradeProduct.objects.filter(is_active=True)


@extend_schema(tags=TAG)
class TradeRegisterEntryListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TradeRegisterEntrySerializer
    pagination_class = StandardPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "guarantee_ref", "our_customer", "beneficiary", "rm_name",
        "rm_code", "product_type", "originating_branch", "segment",
    ]
    ordering_fields = ["issue_date", "expiry_date", "amount_fcy", "created_at"]
    queryset = TradeRegisterEntry.objects.select_related("product").all()

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(created_by=user)


@extend_schema(tags=TAG)
class TradeRegisterEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TradeRegisterEntrySerializer
    queryset = TradeRegisterEntry.objects.select_related("product").all()


@extend_schema(tags=TAG)
class RMLookupView(APIView):
    """RM/DSR name+code options for the dropdown.

    Merges the active staff roster (``staff_employee_data``) with DSR seller-code
    allocations (``dsr_sales_codes``), de-duplicated on (name, code).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management.models import DSRSalesCode, StaffEmployeeData

        seen = set()
        out = []

        def add(name, code, source):
            name = (name or "").strip()
            code = (code or "").strip()
            if not name:
                return
            key = (name.upper(), code.upper())
            if key in seen:
                return
            seen.add(key)
            out.append({"name": name, "code": code, "source": source})

        for name, code in StaffEmployeeData.objects.filter(
            is_active=True
        ).values_list("staff_name", "sales_code"):
            add(name, code, "staff")
        for name, code in DSRSalesCode.objects.values_list("salesperson", "sales_code"):
            add(name, code, "dsr")

        out.sort(key=lambda r: r["name"])
        return Response(out)


@extend_schema(tags=TAG)
class ReferencePreviewView(APIView):
    """Preview the reference a new entry WOULD get, for live display in the form.

    Query params: ``product`` (id) or ``family``; ``issue_date`` (YYYY-MM-DD);
    optional ``amendment_type`` + ``parent_ref``.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        amendment = (request.query_params.get("amendment_type") or "").strip()
        parent = (request.query_params.get("parent_ref") or "").strip()
        if amendment and parent:
            return Response({"reference": refs.amend_reference(parent, amendment)})

        family = (request.query_params.get("family") or "").strip()
        product_id = request.query_params.get("product")
        if not family and product_id:
            product = TradeProduct.objects.filter(pk=product_id).first()
            family = product.ref_family if product else ""
        if not family:
            return Response({"reference": "", "detail": "product or family required"})

        issue_raw = (request.query_params.get("issue_date") or "").strip()
        issue_date = None
        if issue_raw:
            try:
                issue_date = datetime.strptime(issue_raw[:10], "%Y-%m-%d").date()
            except ValueError:
                issue_date = None
        if family != refs.FAMILY_IMPORT_LC and not issue_date:
            return Response({"reference": "", "detail": "issue_date required"})

        return Response({"reference": refs.generate_reference(family, issue_date)})
