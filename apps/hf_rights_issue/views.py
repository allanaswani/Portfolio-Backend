from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count
from core.pagination import StandardPagination
import django_filters.rest_framework

from .models import RightsIssueApplication, SecurityDetail
from .serializers import RightsIssueApplicationSerializer, SecurityDetailSerializer


@extend_schema(tags=["HF Rights Issue"])
class RightsIssueApplicationListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RightsIssueApplicationSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["status", "payment_status", "application_date"]
    queryset = RightsIssueApplication.objects.all()


@extend_schema(tags=["HF Rights Issue"])
class RightsIssueApplicationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RightsIssueApplicationSerializer
    queryset = RightsIssueApplication.objects.all()


@extend_schema(tags=["HF Rights Issue"])
class RightsIssueSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = RightsIssueApplication.objects.all()
        return Response({
            "total_applications": qs.count(),
            "total_shares_applied": qs.aggregate(t=Sum("rights_applied"))["t"] or 0,
            "total_amount_paid": qs.aggregate(t=Sum("amount_paid"))["t"] or 0,
            "total_shares_allotted": qs.aggregate(t=Sum("shares_allotted"))["t"] or 0,
            "by_status": list(qs.values("status").annotate(count=Count("id"))),
        })


# ── Security detail / rights-uptake register (ported from the old backend) ──

@extend_schema(tags=["HF Rights Issue"])
class SecurityDetailImageRegistrasListView(generics.ListAPIView):
    """The rights-issue uptake register (security_detail). Returns the full set —
    the page renders/searches client-side, matching the old backend."""
    permission_classes = [IsAuthenticated]
    serializer_class = SecurityDetailSerializer
    pagination_class = None
    queryset = SecurityDetail.objects.all()


@extend_schema(tags=["HF Rights Issue"])
class SecurityDetailImageRegistrasCsvUpdateView(APIView):
    """Update rights-uptake columns (names, mobile, rights_taken, due, paid,
    balance, email) on existing security_detail rows, keyed on ``pal_no``. Ports
    the old RightTakenImageRegistrasDataSecurityDetailCSVUpdateView. security_detail
    is managed=False, so writes go through raw SQL (per-row savepoint). Returns a
    results ZIP (successful/failed), which the frontend downloads."""
    permission_classes = [IsAuthenticated]
    UPDATABLE = ["names", "mobile", "rights_taken", "due", "paid", "balance", "email"]

    def post(self, request, *args, **kwargs):
        import csv, io, zipfile
        from django.db import connection, transaction
        from django.http import HttpResponse

        f = request.FILES.get("file")
        if not f:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            decoded = f.read().decode("utf-8-sig", errors="replace").splitlines()
        except Exception as e:
            return Response({"error": f"Could not read file: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(decoded)
        fieldnames = reader.fieldnames or []
        if "pal_no" not in fieldnames:
            return Response({"error": "CSV must contain a 'pal_no' column."}, status=status.HTTP_400_BAD_REQUEST)

        success_buf, fail_buf = io.StringIO(), io.StringIO()
        sw = csv.DictWriter(success_buf, fieldnames=fieldnames)
        fw = csv.DictWriter(fail_buf, fieldnames=list(fieldnames) + ["error"])
        sw.writeheader(); fw.writeheader()
        updated = 0

        for row in reader:
            pal = (row.get("pal_no") or "").strip()
            if not pal:
                row["error"] = "Missing 'pal_no'"; fw.writerow(row); continue
            sets = {c: row[c] for c in self.UPDATABLE if c in row and (row.get(c) or "").strip() != ""}
            if not sets:
                row["error"] = "No updatable columns present"; fw.writerow(row); continue
            set_clause = ", ".join(f"{c}=%s" for c in sets)  # columns from a fixed whitelist
            params = list(sets.values()) + [pal]
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(f"UPDATE security_detail SET {set_clause} WHERE pal_no=%s", params)
                    if cur.rowcount == 0:
                        raise ValueError(f"security_detail with pal_no '{pal}' not found")
                updated += 1
                sw.writerow(row)
            except Exception as e:
                row["error"] = str(e); fw.writerow(row)

        resp = HttpResponse(content_type="application/zip")
        resp["Content-Disposition"] = 'attachment; filename="security_detail_update_results.zip"'
        with zipfile.ZipFile(resp, "w") as zf:
            zf.writestr("successful_updates.csv", success_buf.getvalue())
            zf.writestr("failed_updates.csv", fail_buf.getvalue())
        resp["X-Records-Updated"] = str(updated)
        return resp
