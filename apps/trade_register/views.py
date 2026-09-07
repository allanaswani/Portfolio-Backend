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
from .models import TradeCurrency, TradeProduct, TradeRegisterEntry
from .serializers import (
    TradeCurrencySerializer,
    TradeProductAdminSerializer,
    TradeProductSerializer,
    TradeRegisterEntrySerializer,
)

TAG = ["Trade Register"]

# Known HFC branches — the dropdown falls back to these so it's never empty on a
# fresh DB; the live endpoint unions them with branches actually seen in the data.
HFC_BRANCHES = [
    "BURUBURU", "ELDORET", "EMBU", "HARAMBEE AVENUE", "HURLINGHAM", "KISUMU",
    "KITENGELA", "KOMAROCK", "MACHAKOS", "MERU", "MOMBASA", "NAIVASHA", "NAKURU",
    "NANYUKI", "NYERI", "REHANI", "RIVER ROAD", "RONGAI", "SAMEER", "THIKA",
    "TRM", "WESTLANDS", "HEAD OFFICE",
]


@extend_schema(tags=TAG)
class BranchListView(APIView):
    """Branch names for the Originating Branch dropdown — the known HFC branches
    unioned with any branch already present in the trade data, de-duped + sorted."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management.models import TradeFinanceData
        from .models import TradeRegisterEntry

        names = {b.strip().upper() for b in HFC_BRANCHES}
        for src in (
            TradeRegisterEntry.objects.values_list("originating_branch", flat=True),
            TradeFinanceData.objects.values_list("originating_branch", flat=True),
        ):
            names.update((b or "").strip().upper() for b in src if (b or "").strip())
        return Response(sorted(names))


@extend_schema(tags=TAG)
class TradeProductListView(generics.ListAPIView):
    """Active products for the Product Type dropdown (each carries its code)."""

    permission_classes = [IsAuthenticated]
    serializer_class = TradeProductSerializer
    pagination_class = None
    queryset = TradeProduct.objects.filter(is_active=True)


class _TradeAdmin(IsAuthenticated):
    """Read for anyone signed in; changing the desk's pricing is admin-only."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        user = request.user
        return bool(
            user.is_superuser
            or user.is_staff
            or user.groups.filter(name="staff_mgt").exists()
        )


@extend_schema(tags=TAG)
class TradeProductAdminListView(generics.ListCreateAPIView):
    """Maintain the product list and, with it, the commission each one prices at.

    Rates are data rather than constants so that changing one is an edit here,
    not a code change and a deploy.
    """

    permission_classes = [_TradeAdmin]
    serializer_class = TradeProductAdminSerializer
    pagination_class = None
    queryset = TradeProduct.objects.all()


@extend_schema(tags=TAG)
class TradeProductAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [_TradeAdmin]
    serializer_class = TradeProductAdminSerializer
    queryset = TradeProduct.objects.all()


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
    """RM / DSR options for the transaction form — searchable, and current.

    This used to read ``staff_employee_data``, a partial list that nothing keeps
    in step with HR: RMs the desk needed were simply absent, and people who had
    been promoted or had left were still offered. The roster is
    ``employee_table`` — the list the employee-master upload maintains — so that
    is what it reads now, with anyone carrying an exit date left out and each
    person's current job title shown.

    Searching happens here rather than in the browser: the form was a plain
    dropdown the desk had to scroll, and shipping the whole roster down to
    filter it client-side is what made that necessary.

    Query: ``?search=&limit=&include_exited=1``. Sales codes are merged in from
    the DSR allocations and the sales-staff table, keyed on the PF number, and
    only for the rows actually being returned.
    """

    permission_classes = [IsAuthenticated]

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 500

    def get(self, request):
        from django.db import router as db_router
        from django.db.models import Q

        from apps.gceo_dashboard.models import EmployeeTable
        from apps.staff_management.models import DSRSalesCode, StaffEmployeeData

        search = (request.query_params.get("search") or "").strip()
        include_exited = request.query_params.get("include_exited") == "1"
        try:
            limit = int(request.query_params.get("limit", self.DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = max(1, min(self.MAX_LIMIT, limit))

        alias = db_router.db_for_read(EmployeeTable) or "default"
        qs = EmployeeTable.objects.using(alias).exclude(name__isnull=True).exclude(name="")
        if not include_exited:
            # Either marker alone can carry the exit, depending on which sheet
            # the HR upload recorded it on, so both are honoured.
            qs = qs.filter(staff_exit_date__isnull=True).exclude(exit=1)
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(job_title__icontains=search)
                | Q(department__icontains=search)
            )

        rows = list(
            qs.order_by("name").values(
                "staff_id", "name", "job_title", "department", "unit", "org_unit",
                "staff_exit_date",
            )[:limit]
        )

        # Sales codes live in other tables; look them up only for this page.
        pfs = {self.pf_number(r["staff_id"]) for r in rows}
        pfs.discard(None)
        codes = {}
        if pfs:
            for pf, code in DSRSalesCode.objects.filter(
                pf_number__in=[str(pf) for pf in pfs]
            ).values_list("pf_number", "sales_code"):
                key = self.pf_number(pf)
                if key is not None and code:
                    codes.setdefault(key, code)
            for pf, code in StaffEmployeeData.objects.filter(
                staff_pf_number__in=pfs
            ).values_list("staff_pf_number", "sales_code"):
                if pf is not None and code:
                    codes.setdefault(int(pf), code)

        out = []
        for row in rows:
            pf = self.pf_number(row["staff_id"])
            out.append({
                "name": (row["name"] or "").strip(),
                "code": codes.get(pf, ""),
                "pf_number": str(pf) if pf is not None else "",
                "job_title": (row["job_title"] or "").strip(),
                "department": (row["department"] or "").strip(),
                "unit": (row["unit"] or row["org_unit"] or "").strip(),
                "exited": row["staff_exit_date"] is not None,
                "source": "roster",
            })
        return Response({"count": len(out), "limit": limit, "results": out})

    @staticmethod
    def pf_number(value):
        """``Decimal('4028.00000')`` and ``'4028'`` are the same PF number."""
        if value is None:
            return None
        try:
            return int(float(str(value).strip().replace(",", "")))
        except (TypeError, ValueError):
            return None


@extend_schema(tags=TAG)
class TradeCurrencyListView(generics.ListAPIView):
    """Currencies the desk may write in — a table, not a hard-coded list.

    The form used to offer ten currencies compiled into the frontend bundle,
    which is why the desk found currencies missing: adding one meant a deploy.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TradeCurrencySerializer
    pagination_class = None
    queryset = TradeCurrency.objects.filter(is_active=True)


@extend_schema(tags=TAG)
class ProductLookupView(APIView):
    """Resolve a typed product code to its name and pricing, and quote it.

    This is what makes "type the product ID and the rest fills in" work.
    ``?code=BG`` answers with the product; adding ``&amount_fcy=&fx_rate=
    &issue_date=&expiry_date=&is_open_ended=`` also answers with the commission
    that product prices at and how it was arrived at — so the desk sees the
    working and can disagree with it rather than being handed a bare number.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        code = (request.query_params.get("code") or "").strip()
        product_id = (request.query_params.get("product") or "").strip()
        if not code and not product_id:
            return Response({"detail": "code or product is required."}, status=400)

        product = None
        if product_id.isdigit():
            product = TradeProduct.objects.filter(pk=int(product_id)).first()
        if product is None and code:
            product = TradeProduct.objects.filter(code__iexact=code).first()
        if product is None:
            return Response({"found": False, "detail": "No product with that code."},
                            status=404)

        def _date(name):
            raw = (request.query_params.get(name) or "").strip()
            if not raw:
                return None
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d").date()
            except ValueError:
                return None

        payload = {"found": True, "product": TradeProductSerializer(product).data}
        if request.query_params.get("amount_fcy"):
            quote = product.quote(
                request.query_params.get("amount_fcy"),
                request.query_params.get("fx_rate") or 1,
                _date("issue_date"),
                _date("expiry_date"),
                request.query_params.get("is_open_ended") in ("1", "true", "True"),
            )
            payload["quote"] = {
                **quote,
                "commission": (str(quote["commission"])
                               if quote["commission"] is not None else None),
                "periods": (str(quote["periods"])
                            if quote["periods"] is not None else None),
                "rate": str(quote["rate"]),
            }
        return Response(payload)


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
