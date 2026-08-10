"""DSR seller-code allocation API (Administration module).

Endpoints:
* ``GET  dsr-sales-codes/``            — list/search existing allocations.
* ``GET  dsr-sales-codes/lookup/?pf_number=`` — is this PF already allocated? If
  not, autofilled name/branch/department + the next code that would be issued.
* ``POST dsr-sales-codes/allocate/``   — allocate a code to a PF (idempotent per PF).
* ``POST dsr-sales-codes/upload-csv/`` — bulk import the listing (upsert on PF).

The code-generation and PF rules live in :mod:`apps.staff_management.dsr`.
"""

import csv
import io
from datetime import datetime

from django.db import IntegrityError, transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from .dsr import autofill_from_roster, next_sales_code
from .models import DSRSalesCode


class DSRSalesCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DSRSalesCode
        fields = "__all__"
        # sales_code is system-generated on allocate; never accept it from the body.
        read_only_fields = ["sales_code", "created_at", "updated_at"]


def _is_admin(user) -> bool:
    """Only administrators may allocate codes or bulk-import the listing."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.is_staff or user.groups.filter(name="staff_mgt").exists())
    )


def _parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


class DSRSalesCodeListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DSRSalesCodeSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["branch", "role", "department"]
    search_fields = ["pf_number", "sales_code", "salesperson", "branch", "role", "team_leader"]
    ordering_fields = ["sales_code", "salesperson", "branch", "created_at"]
    queryset = DSRSalesCode.objects.all()


class DSRSalesCodeLookupView(APIView):
    """Check a PF before allocating: existing code, or an autofilled preview."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        pf = (request.query_params.get("pf_number") or "").strip()
        if not pf:
            return Response({"detail": "pf_number is required."}, status=status.HTTP_400_BAD_REQUEST)

        existing = DSRSalesCode.objects.filter(pf_number=pf).first()
        if existing:
            return Response({
                "allocated": True,
                "record": DSRSalesCodeSerializer(existing).data,
            })

        return Response({
            "allocated": False,
            "next_sales_code": next_sales_code(),
            "suggested": {"pf_number": pf, **autofill_from_roster(pf)},
        })


class DSRSalesCodeAllocateView(APIView):
    """Allocate the next DSR code to a PF. Returns the existing one if already set."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_admin(request.user):
            return Response({"detail": "Administrators only."}, status=status.HTTP_403_FORBIDDEN)

        pf = str(request.data.get("pf_number") or "").strip()
        if not pf:
            return Response({"pf_number": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)

        existing = DSRSalesCode.objects.filter(pf_number=pf).first()
        if existing:
            return Response({
                "already_allocated": True,
                "detail": f"PF {pf} already has sales code {existing.sales_code}.",
                "record": DSRSalesCodeSerializer(existing).data,
            }, status=status.HTTP_200_OK)

        payload = {
            "pf_number": pf,
            "salesperson": str(request.data.get("salesperson") or "").strip(),
            "branch": str(request.data.get("branch") or "").strip(),
            "department": str(request.data.get("department") or "").strip(),
            "role": str(request.data.get("role") or "").strip(),
            "team_leader": str(request.data.get("team_leader") or "").strip(),
            "date_of_employment": _parse_date(request.data.get("date_of_employment")),
            "allocation_date": _parse_date(request.data.get("allocation_date")) or datetime.now().date(),
        }

        # Generate + save atomically; retry once if another allocation grabbed the
        # same number between read and write (unique constraint is the backstop).
        for _ in range(5):
            code = next_sales_code()
            try:
                with transaction.atomic():
                    record = DSRSalesCode.objects.create(sales_code=code, **payload)
                return Response({
                    "already_allocated": False,
                    "record": DSRSalesCodeSerializer(record).data,
                }, status=status.HTTP_201_CREATED)
            except IntegrityError:
                # PF race → someone allocated this PF first; return theirs.
                dup = DSRSalesCode.objects.filter(pf_number=pf).first()
                if dup:
                    return Response({
                        "already_allocated": True,
                        "detail": f"PF {pf} already has sales code {dup.sales_code}.",
                        "record": DSRSalesCodeSerializer(dup).data,
                    }, status=status.HTTP_200_OK)
                # else sales_code race → loop and try the next number.
                continue

        return Response(
            {"detail": "Could not allocate a unique code, please retry."},
            status=status.HTTP_409_CONFLICT,
        )


class DSRSalesCodeCSVUploadView(APIView):
    """Bulk import the DSR listing. Upserts on PF number; headers are case-insensitive.

    Recognised columns: PF_NO, SALESCODE, SALESPERSON, Branch, Role, Team Leader,
    DATE OF EMPLOYMENT, ALLOCATION DATE.
    """

    permission_classes = [IsAuthenticated]

    HEADER_MAP = {
        "pf_no": "pf_number", "pf_number": "pf_number", "pf": "pf_number",
        "salescode": "sales_code", "sales_code": "sales_code",
        "salesperson": "salesperson", "name": "salesperson",
        "branch": "branch",
        "role": "role",
        "department": "department",
        "team leader": "team_leader", "team_leader": "team_leader",
        "date of employment": "date_of_employment", "date_of_employment": "date_of_employment",
        "allocation date": "allocation_date", "allocation_date": "allocation_date",
    }

    def post(self, request):
        if not _is_admin(request.user):
            return Response({"detail": "Administrators only."}, status=status.HTTP_403_FORBIDDEN)

        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            text = upload.read().decode("latin-1")

        reader = csv.DictReader(io.StringIO(text))
        created = updated = skipped = 0
        errors = []

        with transaction.atomic():
            for i, raw in enumerate(reader, start=2):
                row = {}
                for key, val in raw.items():
                    if key is None:
                        continue
                    mapped = self.HEADER_MAP.get(str(key).strip().lower())
                    if mapped:
                        row[mapped] = (val or "").strip()

                pf = row.get("pf_number", "").strip()
                code = row.get("sales_code", "").strip()
                if not pf or not code:
                    skipped += 1
                    continue

                fields = {
                    "sales_code": code,
                    "salesperson": row.get("salesperson", ""),
                    "branch": row.get("branch", ""),
                    "department": row.get("department", ""),
                    "role": row.get("role", ""),
                    "team_leader": row.get("team_leader", ""),
                    "date_of_employment": _parse_date(row.get("date_of_employment")),
                    "allocation_date": _parse_date(row.get("allocation_date")),
                }
                try:
                    _, was_created = DSRSalesCode.objects.update_or_create(
                        pf_number=pf, defaults=fields,
                    )
                    created += int(was_created)
                    updated += int(not was_created)
                except IntegrityError:
                    # sales_code already used by a different PF — flag, don't abort.
                    errors.append(f"Row {i}: sales code {code} already used by another PF.")
                    skipped += 1

        return Response({
            "created": created, "updated": updated, "skipped": skipped,
            "errors": errors[:50],
        }, status=status.HTTP_200_OK)
