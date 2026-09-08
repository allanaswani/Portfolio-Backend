"""Trade Register API — CRUD for entries, plus the dropdown/reference helpers
the form needs (products, RM/DSR lookup, live reference preview)."""

from datetime import datetime, timedelta

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from . import references as refs
from .models import (
    TradeCurrency, TradeProduct, TradeProductCategory, TradeRegisterEntry,
    TradeTariff,
)
from .serializers import (
    TradeCurrencySerializer,
    TradeProductAdminSerializer,
    TradeProductCategorySerializer,
    TradeProductSerializer,
    TradeRegisterEntrySerializer,
    TradeTariffSerializer,
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
    """Branch names for the Originating Branch dropdown.

    The list used to be the known branches uppercased, unioned with whatever
    spellings the data happened to hold — so "THIKA" and "THIKA BRANCH" were two
    entries, and the desk saw its branches twice. Every name now goes through
    ``normalize_branch``, the canonicaliser the rest of the application already
    uses, so one branch appears once however it was typed.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.staff_management.branches import normalize_branch
        from apps.staff_management.models import TradeFinanceData
        from .models import TradeRegisterEntry

        names = set()
        for source in (
            HFC_BRANCHES,
            TradeRegisterEntry.objects.values_list("originating_branch", flat=True),
            TradeFinanceData.objects.values_list("originating_branch", flat=True),
        ):
            for raw in source:
                canon = normalize_branch(raw)
                if canon:
                    names.add(canon)
        return Response(sorted(names))


@extend_schema(tags=TAG)
class TradeProductCategoryListView(generics.ListAPIView):
    """The desk's four product categories, for the first dropdown.

    Picking a category narrows the product dropdown to that category's
    products — ``/products/?category=<id or code>``.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TradeProductCategorySerializer
    pagination_class = None
    queryset = TradeProductCategory.objects.filter(is_active=True).prefetch_related("products")


@extend_schema(tags=TAG)
class TradeProductListView(generics.ListAPIView):
    """Active products for the Product Type dropdown (each carries its code).

    ``?category=`` takes a category id or its code, so the form can narrow the
    list the moment a category is chosen. Retired products are excluded — they
    stay readable on the transactions that reference them, but a product the
    desk has dropped is not offered for a new one.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TradeProductSerializer
    pagination_class = None

    def get_queryset(self):
        qs = TradeProduct.objects.filter(is_active=True).select_related("category")
        category = (self.request.query_params.get("category") or "").strip()
        if category:
            if category.isdigit():
                qs = qs.filter(category_id=int(category))
            else:
                qs = qs.filter(category__code__iexact=category)
        return qs


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


def _parse_date(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def filter_entries(qs, params):
    """The filters every list of transactions shares.

    Date range, category, product, branch and archive state — applied here once
    so the register, the diary and the Trade Finance view cannot disagree about
    what a filter means, and so an export covers exactly what the screen showed.

    ``date_field`` chooses which date the range applies to. It defaults to the
    issue date, but a report of what was CAPTURED in a period wants the
    reporting date and one of what EXPIRES in it wants the expiry, so the caller
    says which.
    """
    field = (params.get("date_field") or "issue_date").strip()
    if field not in ("issue_date", "reporting_date", "expiry_date", "created_at"):
        field = "issue_date"

    start = _parse_date(params.get("date_from"))
    end = _parse_date(params.get("date_to"))
    if start:
        qs = qs.filter(**{f"{field}__gte": start})
    if end:
        qs = qs.filter(**{f"{field}__lte": end})

    category = (params.get("category") or "").strip()
    if category:
        if category.isdigit():
            qs = qs.filter(product__category_id=int(category))
        else:
            qs = qs.filter(product__category__code__iexact=category)

    product = (params.get("product") or "").strip()
    if product.isdigit():
        qs = qs.filter(product_id=int(product))

    branch = (params.get("branch") or "").strip()
    if branch:
        qs = qs.filter(originating_branch__iexact=branch)

    action = (params.get("action") or "").strip()
    if action:
        qs = qs.filter(action__iexact=action)

    # The active register hides what has expired and been filed away; the
    # Expired folder is exactly those rows. "all" asks for both.
    archived = (params.get("archived") or "").strip().lower()
    if archived in ("1", "true", "yes"):
        qs = qs.filter(is_archived=True)
    elif archived != "all":
        qs = qs.filter(is_archived=False)
    return qs


@extend_schema(tags=TAG)
class TradeRegisterEntryListCreateView(generics.ListCreateAPIView):
    """The register. Filterable by date range, category, product and branch,
    so an export covers exactly the period the screen was showing."""

    permission_classes = [IsAuthenticated]
    serializer_class = TradeRegisterEntrySerializer
    pagination_class = StandardPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "guarantee_ref", "our_customer", "beneficiary", "rm_name",
        "rm_code", "product_type", "originating_branch", "segment",
    ]
    ordering_fields = [
        "issue_date", "expiry_date", "amount_fcy", "created_at", "reporting_date",
    ]

    def get_queryset(self):
        qs = (TradeRegisterEntry.objects
              .select_related("product", "product__category", "product__tariff")
              .with_position())
        return filter_entries(qs, self.request.query_params)

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(created_by=user)


@extend_schema(tags=TAG)
class TradeRegisterEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TradeRegisterEntrySerializer
    queryset = (TradeRegisterEntry.objects
                .select_related("product", "product__category", "product__tariff")
                .with_position())


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

    The roster is not the only source, though. Moving to ``employee_table``
    found the RMs that ``staff_employee_data`` was missing — and lost the DSRs
    and sales staff whose record never made it onto the HR roster. Swapping one
    incomplete list for another is not a fix, so both are searched and merged,
    each result saying which source it came from.

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

        # The write alias, not the read one: the router sends unmanaged models
        # to ``datawarehouse`` for reads and falls through to ``default`` for
        # writes. On production the two are the same database, and the write
        # alias is the one a test can reach — the same pinning as
        # ``employee_master_views.employee_db``.
        alias = db_router.db_for_write(EmployeeTable) or "default"
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
        seen = set()
        for row in rows:
            pf = self.pf_number(row["staff_id"])
            name = (row["name"] or "").strip()
            seen.add(name.upper())
            out.append({
                "name": name,
                "code": codes.get(pf, ""),
                "pf_number": str(pf) if pf is not None else "",
                "job_title": (row["job_title"] or "").strip(),
                "department": (row["department"] or "").strip(),
                "unit": (row["unit"] or row["org_unit"] or "").strip(),
                "exited": row["staff_exit_date"] is not None,
                "source": "roster",
            })

        # ── Anyone the HR roster does not carry ─────────────────────────────
        # Moving to employee_table fixed the RMs that were missing from
        # staff_employee_data, and lost anyone who is in the sales tables but
        # NOT on the HR roster — DSRs and sales staff whose record never made it
        # into employee_table. Swapping one incomplete source for another is not
        # a fix, so both are searched and the results merged, each labelled with
        # where it came from.
        remaining = limit - len(out)
        if remaining > 0:
            extra = []
            dsr = DSRSalesCode.objects.all()
            staff = StaffEmployeeData.objects.filter(is_active=True)
            if search:
                dsr = dsr.filter(
                    Q(salesperson__icontains=search) | Q(sales_code__icontains=search)
                )
                staff = staff.filter(
                    Q(staff_name__icontains=search)
                    | Q(sales_code__icontains=search)
                    | Q(job_title__icontains=search)
                )
            for name, code, dept in dsr.values_list(
                "salesperson", "sales_code", "department"
            )[: remaining * 3]:
                name = (name or "").strip()
                if name and name.upper() not in seen:
                    seen.add(name.upper())
                    extra.append({
                        "name": name, "code": (code or "").strip(), "pf_number": "",
                        "job_title": "DSR", "department": (dept or "").strip(),
                        "unit": "", "exited": False, "source": "dsr",
                    })
            for name, code, title, pf in staff.values_list(
                "staff_name", "sales_code", "job_title", "staff_pf_number"
            )[: remaining * 3]:
                name = (name or "").strip()
                if name and name.upper() not in seen:
                    seen.add(name.upper())
                    extra.append({
                        "name": name, "code": (code or "").strip(),
                        "pf_number": str(pf) if pf is not None else "",
                        "job_title": (title or "").strip(), "department": "",
                        "unit": "", "exited": False, "source": "sales_staff",
                    })
            extra.sort(key=lambda r: r["name"])
            out.extend(extra[:remaining])

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
class TradeActionListView(APIView):
    """The desk's six actions, and which of them act on an existing instrument.

    Served rather than hard-coded in the frontend so the two cannot drift, and
    so the form knows which actions must be given a parent reference.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "actions": [
                {"value": a, "label": a.title(),
                 "needs_parent": a in refs.ACTIONS_ON_EXISTING}
                for a in refs.ACTIONS
            ],
            "legacy": refs.LEGACY_ACTIONS,
        })


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
                # Issuing, amending and cancelling are three different charges
                # in the tariff book, so the action selects the line.
                action=request.query_params.get("action") or refs.ACTION_ISSUANCE,
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
class CustomerLookupView(APIView):
    """Resolve a customer id to the name and segment the register should carry.

    The desk was typing the customer id, then typing the name and picking the
    segment again by hand — three chances to disagree with the core system about
    the same customer. ``?customer_id=12345`` answers from ``hf_customer``.

    ``segment`` and ``banking_segment`` are different columns on that table and
    the register has historically carried the banking segment, so that is what
    is offered first, with the other returned alongside rather than silently
    collapsed into it.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def customer_db():
        """The alias this lookup reads ``hf_customer`` from.

        The router sends unmanaged models to ``datawarehouse`` for reads and
        returns ``None`` for their writes, which falls through to ``default``.
        On production the two aliases are the same physical database, so the
        split is invisible — and pinning to the write alias is what
        ``apps.staff_management.employee_master_views.employee_db`` already does
        for the same reason: it is the alias a test can reach.
        """
        from django.db import router as db_router

        from apps.portfolio.models import HfCustomer

        return db_router.db_for_write(HfCustomer) or "default"

    def get(self, request):
        from apps.portfolio.models import HfCustomer

        raw = (request.query_params.get("customer_id") or "").strip()
        if not raw:
            return Response({"detail": "customer_id is required."}, status=400)
        try:
            customer_id = int(float(raw.replace(",", "")))
        except (TypeError, ValueError):
            return Response({"found": False, "detail": "That is not a customer id."},
                            status=400)

        row = (
            HfCustomer.objects.using(self.customer_db())
            .filter(cust_id=customer_id)
            .values("cust_id", "latin_surname", "segment", "banking_segment", "branch")
            .first()
        )
        if not row:
            return Response({"found": False, "customer_id": customer_id,
                             "detail": "No customer with that id."}, status=404)

        return Response({
            "found": True,
            "customer_id": customer_id,
            "name": (row["latin_surname"] or "").strip(),
            "segment": (row["banking_segment"] or row["segment"] or "").strip(),
            "banking_segment": (row["banking_segment"] or "").strip(),
            "portfolio_segment": (row["segment"] or "").strip(),
            "branch": (row["branch"] or "").strip(),
        })


@extend_schema(tags=TAG)
class TradeDiaryView(APIView):
    """The desk's diary: what has expired, and what is about to.

    A guarantee that has run out is not a dead row — it is an item somebody has
    to release, renew or call up. Nothing in the register surfaced them, so they
    were found by scrolling.

    Returns the whole watchlist grouped into shelves, newest expiry first within
    each. ``?window=`` narrows the "expiring" horizon (default 90 days);
    ``?include_live=1`` adds items further out than that.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone

        try:
            window = max(1, min(365, int(request.query_params.get("window", 90))))
        except (TypeError, ValueError):
            window = 90
        include_live = request.query_params.get("include_live") == "1"
        today = timezone.localdate()

        # The ACTIVE diary. What has expired has been filed away by the daily
        # job and lives in the Expired folder — ?archived=1 — which is the
        # point of the filing: the desk's working list is what it still has to
        # act on. ?archived=all shows both.
        archived = (request.query_params.get("archived") or "").strip().lower()
        qs = (TradeRegisterEntry.objects
              .select_related("product", "product__category", "product__tariff")
              .with_position())
        if archived in ("1", "true", "yes"):
            qs = qs.filter(is_archived=True)
        elif archived != "all":
            qs = qs.filter(is_archived=False)

        qs = filter_entries(qs, {**request.query_params.dict(), "archived": archived or "0"})

        if not include_live:
            # Everything except items comfortably in the future: expired,
            # expiring inside the window, open-ended, and undated. An amendment
            # can have moved the expiry, so new_expiry_date is honoured here as
            # well as the instrument's own date.
            horizon = today + timedelta(days=window)
            qs = qs.filter(
                Q(expiry_date__lte=horizon)
                | Q(is_open_ended=True)
                | Q(expiry_date__isnull=True)
                | Q(amendments__new_expiry_date__lte=horizon)
            ).distinct()

        rows = list(qs.order_by("expiry_date", "-issue_date")[:2000])
        serialized = TradeRegisterEntrySerializer(rows, many=True).data

        buckets = {key: [] for key in TradeRegisterEntry.DIARY_LABELS}
        for entry, payload in zip(rows, serialized):
            buckets[entry.diary_status(today)].append(payload)

        return Response({
            "as_of": today,
            "window_days": window,
            "archived": archived or "0",
            "labels": TradeRegisterEntry.DIARY_LABELS,
            "counts": {key: len(value) for key, value in buckets.items()},
            "buckets": buckets,
        })


@extend_schema(tags=TAG)
class TradeTariffListView(generics.ListCreateAPIView):
    """The tariff book. Reading is open; changing a rate is admin-only.

    Repricing one line reprices every product mapped to it — which is the point
    of having tariffs at all, and the reason this is gated.
    """

    permission_classes = [_TradeAdmin]
    serializer_class = TradeTariffSerializer
    pagination_class = None

    def get_queryset(self):
        qs = (TradeTariff.objects
              .select_related("category", "product")
              .prefetch_related("category__products"))
        category = (self.request.query_params.get("category") or "").strip()
        if category:
            if category.isdigit():
                qs = qs.filter(category_id=int(category))
            else:
                qs = qs.filter(category__code__iexact=category)
        action = (self.request.query_params.get("action") or "").strip()
        if action:
            qs = qs.filter(Q(action__iexact=action) | Q(action=""))
        if self.request.query_params.get("active") != "all":
            qs = qs.filter(is_active=True)
        return qs


@extend_schema(tags=TAG)
class TradeTariffDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [_TradeAdmin]
    serializer_class = TradeTariffSerializer
    queryset = (TradeTariff.objects
                .select_related("category", "product")
                .prefetch_related("category__products"))


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
