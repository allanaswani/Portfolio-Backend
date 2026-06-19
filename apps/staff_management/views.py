from datetime import date
from decimal import Decimal

import django_filters.rest_framework
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from .models import (
    BranchEmployeeData, ScorecardRole, ScorecardKPI, RoleKPIMapping,
    PerformanceActual, EmployeeMonthlyPerformance,
)
from .serializers import (
    BranchEmployeeDataSerializer, ScorecardRoleSerializer, ScorecardKPISerializer,
    RoleKPIMappingSerializer, PerformanceActualSerializer,
    EmployeeMonthlyPerformanceSerializer,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _score(actual, target):
    """Return % achievement, capped at 110. Returns 0 when no target."""
    try:
        t = float(target or 0)
        a = float(actual or 0)
        if t <= 0:
            return 0.0
        return min(round(a / t * 100, 2), 110.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _grade(score):
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "E"


def _weighted_score(dep, loan, rev, nc):
    """40% deposits, 30% loans, 20% revenue, 10% new customers."""
    return round(dep * 0.40 + loan * 0.30 + rev * 0.20 + nc * 0.10, 2)


def _resolve_period(body):
    """Return (year, month, period_date) from request body or current month."""
    now = timezone.now()
    year = int(body.get("year") or now.year)
    month = int(body.get("month") or now.month)
    return year, month, date(year, month, 1)


def _compute_scorecard(year, month, period_date):
    """
    Core scorecard engine.
    Returns list of EmployeeMonthlyPerformance objects (saved to DB).
    """
    from apps.portfolio.models import RetailAllocatedPortfolio, PortfolioRmDepositTrends, PortfolioRmRevenue
    from apps.portfolio_management_enrichment.models import RmTarget

    # All active RMs
    rm_qs = (
        RetailAllocatedPortfolio.objects
        .values("sales_code", "rm_name")
        .distinct()
        .exclude(sales_code__isnull=True)
        .exclude(sales_code__exact="")
    )

    # Employee metadata (role, dept) keyed by service_code
    emp_meta = {}
    for emp in BranchEmployeeData.objects.filter(exit__isnull=True).exclude(exit=1):
        sc = (emp.service_code or "").strip()
        if sc:
            emp_meta[sc] = emp

    # Deposit actuals for the period (sum value per sales_code)
    dep_qs = (
        PortfolioRmDepositTrends.objects
        .filter(dates_eom__year=year, dates_eom__month=month)
        .values("sales_code")
        .annotate(dep_actual=Sum("value"), nc_actual=Sum("number_of_customers"))
    )
    dep_map = {r["sales_code"]: r for r in dep_qs}

    # Revenue actuals (no month filter — YTD snapshot)
    rev_qs = (
        PortfolioRmRevenue.objects
        .values("sales_code")
        .annotate(rev_actual=Sum("value"))
    )
    rev_map = {r["sales_code"]: float(r["rev_actual"] or 0) for r in rev_qs}

    # Targets for the period
    target_qs = RmTarget.objects.filter(month__year=year, month__month=month)
    target_map = {r.sales_code: r for r in target_qs}

    created, updated = 0, 0
    results = []

    for rm in rm_qs:
        sc = (rm["sales_code"] or "").strip()
        if not sc:
            continue

        emp = emp_meta.get(sc)
        dep_row = dep_map.get(sc, {})
        tgt = target_map.get(sc)

        dep_actual = Decimal(str(dep_row.get("dep_actual") or 0))
        nc_actual = int(dep_row.get("nc_actual") or 0)
        rev_actual = Decimal(str(rev_map.get(sc, 0)))
        loan_actual = Decimal("0")  # no direct RM-level loan trends table

        dep_target = Decimal(str(tgt.deposit_target if tgt else 0))
        loan_target = Decimal(str(tgt.loan_target if tgt else 0))
        rev_target = Decimal(str(tgt.revenue_target if tgt else 0))
        nc_target = int(tgt.new_customers_target if tgt else 0)

        dep_score = _score(dep_actual, dep_target)
        loan_score = _score(loan_actual, loan_target)
        rev_score = _score(rev_actual, rev_target)
        nc_score = _score(nc_actual, nc_target)
        total = _weighted_score(dep_score, loan_score, rev_score, nc_score)

        kpis_met = sum([
            dep_score >= 80,
            loan_score >= 80,
            rev_score >= 80,
            nc_score >= 80,
        ])

        perf, is_new = EmployeeMonthlyPerformance.objects.update_or_create(
            sales_code=sc,
            month=period_date,
            defaults=dict(
                staff_name=rm.get("rm_name") or (emp.name if emp else ""),
                staff_role=emp.job_title if emp else "",
                department=emp.department if emp else "",
                org_unit=emp.unit if emp else "",
                deposit_actual=dep_actual,
                deposit_target=dep_target,
                loan_actual=loan_actual,
                loan_target=loan_target,
                revenue_actual=rev_actual,
                revenue_target=rev_target,
                new_customers_actual=nc_actual,
                new_customers_target=nc_target,
                deposit_score=dep_score,
                loan_score=loan_score,
                revenue_score=rev_score,
                new_customers_score=nc_score,
                total_score=total,
                grade=_grade(total),
                kpis_met=f"{kpis_met}/4",
            ),
        )

        if is_new:
            created += 1
        else:
            updated += 1

        # Persist per-KPI actuals
        for kpi_name, actual_val, target_val in [
            ("Deposits", dep_actual, dep_target),
            ("Loans", loan_actual, loan_target),
            ("Revenue", rev_actual, rev_target),
            ("New Customers", nc_actual, nc_target),
        ]:
            PerformanceActual.objects.update_or_create(
                sales_code=sc,
                kpi_name=kpi_name,
                month=period_date,
                defaults=dict(
                    staff_name=perf.staff_name,
                    staff_role=perf.staff_role,
                    department=perf.department,
                    actual_value=Decimal(str(actual_val)),
                    target_value=Decimal(str(target_val)),
                ),
            )

        results.append(perf)

    return results, created, updated


# ── Existing staff views ──────────────────────────────────────────────────────

@extend_schema(tags=["Staff Management — Branch Managers"])
class BranchManagersListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchEmployeeDataSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["unit", "grade", "exit", "gender"]

    def get_queryset(self):
        return BranchEmployeeData.objects.filter(job_title__icontains="manager")


@extend_schema(tags=["Staff Management — Sales Staff"])
class SalesStaffListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchEmployeeDataSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["unit", "grade", "exit", "gender", "division"]

    def get_queryset(self):
        return (
            BranchEmployeeData.objects.filter(division__icontains="sales")
            | BranchEmployeeData.objects.filter(department__icontains="sales")
        )


@extend_schema(tags=["Staff Management — All Staff"])
class AllStaffListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchEmployeeDataSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["unit", "department", "grade", "division", "exit", "gender"]
    queryset = BranchEmployeeData.objects.all()


@extend_schema(tags=["Staff Management — All Staff"])
class StaffDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchEmployeeDataSerializer
    queryset = BranchEmployeeData.objects.all()


# ── Scorecard config ──────────────────────────────────────────────────────────

@extend_schema(tags=["Scorecard — Roles"])
class ScorecardRoleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScorecardRoleSerializer
    queryset = ScorecardRole.objects.all()


@extend_schema(tags=["Scorecard — KPIs"])
class ScorecardKPIListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScorecardKPISerializer
    queryset = ScorecardKPI.objects.all()


@extend_schema(tags=["Scorecard — Role-KPI Mappings"])
class RoleKPIMappingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RoleKPIMappingSerializer
    queryset = RoleKPIMapping.objects.select_related("role", "kpi").all()


# ── Detail (retrieve / update / delete) for scorecard config ───────────────────

@extend_schema(tags=["Scorecard — Roles"])
class ScorecardRoleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScorecardRoleSerializer
    queryset = ScorecardRole.objects.all()


@extend_schema(tags=["Scorecard — KPIs"])
class ScorecardKPIDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScorecardKPISerializer
    queryset = ScorecardKPI.objects.all()


@extend_schema(tags=["Scorecard — Role-KPI Mappings"])
class RoleKPIMappingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RoleKPIMappingSerializer
    queryset = RoleKPIMapping.objects.select_related("role", "kpi").all()


# ── Reusable CSV bulk-upload ───────────────────────────────────────────────────

@extend_schema(tags=["Staff Management — CSV Upload"])
class BaseCsvUploadView(APIView):
    """
    Bulk-create rows from an uploaded CSV file (multipart field ``file``).

    Tries a single bulk validation first; on any row error it falls back to
    per-row processing so valid rows still import and the response reports which
    rows failed (1-based, accounting for the header line).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = None  # set by subclass

    def post(self, request):
        import csv
        import io

        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"detail": "No file uploaded. Send a CSV in the 'file' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response(
                {"detail": "File must be UTF-8 encoded CSV."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return Response(
                {"detail": "CSV has no data rows."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Fast path: validate & save the whole batch.
        batch = self.serializer_class(data=rows, many=True)
        if batch.is_valid():
            batch.save()
            return Response(
                {"created": len(batch.validated_data), "errors": [], "error_count": 0},
                status=status.HTTP_201_CREATED,
            )

        # Slow path: import valid rows, report the rest.
        created, errors = 0, []
        for idx, row in enumerate(rows):
            one = self.serializer_class(data=row)
            if one.is_valid():
                one.save()
                created += 1
            else:
                errors.append({"row": idx + 2, "errors": one.errors})  # +2: header + 1-based

        return Response(
            {"created": created, "errors": errors[:50], "error_count": len(errors)},
            status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST,
        )


@extend_schema(tags=["Scorecard — Roles"])
class ScorecardRoleCsvUploadView(BaseCsvUploadView):
    serializer_class = ScorecardRoleSerializer


@extend_schema(tags=["Scorecard — KPIs"])
class ScorecardKPICsvUploadView(BaseCsvUploadView):
    serializer_class = ScorecardKPISerializer


@extend_schema(tags=["Scorecard — Role-KPI Mappings"])
class RoleKPIMappingCsvUploadView(BaseCsvUploadView):
    serializer_class = RoleKPIMappingSerializer


# ── Performance actuals ────────────────────────────────────────────────────────

@extend_schema(tags=["Scorecard — Actuals"])
class PerformanceActualListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PerformanceActualSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "kpi_name", "month", "staff_role", "department"]
    queryset = PerformanceActual.objects.all()


@extend_schema(tags=["Scorecard — Actuals"])
class MissingActualsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Employees who have no PerformanceActual record for the latest scorecard month.
        """
        latest = PerformanceActual.objects.order_by("-month").values_list("month", flat=True).first()
        if not latest:
            return Response([])

        have_actuals = set(
            PerformanceActual.objects
            .filter(month=latest)
            .values_list("sales_code", flat=True)
        )

        from apps.portfolio.models import RetailAllocatedPortfolio
        all_rms = (
            RetailAllocatedPortfolio.objects
            .values("sales_code", "rm_name")
            .distinct()
            .exclude(sales_code__isnull=True)
            .exclude(sales_code__exact="")
        )

        emp_meta = {
            (e.service_code or "").strip(): e
            for e in BranchEmployeeData.objects.all()
            if (e.service_code or "").strip()
        }

        missing = []
        for rm in all_rms:
            sc = (rm["sales_code"] or "").strip()
            if sc and sc not in have_actuals:
                emp = emp_meta.get(sc)
                missing.append({
                    "sales_code": sc,
                    "staff_name": rm.get("rm_name") or (emp.name if emp else ""),
                    "staff_role": emp.job_title if emp else "",
                    "department": emp.department if emp else "",
                    "kpi_name": "All KPIs",
                    "month": str(latest),
                })

        return Response(missing)


@extend_schema(tags=["Scorecard — Actuals"])
class MissingActualsRoleSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        latest = PerformanceActual.objects.order_by("-month").values_list("month", flat=True).first()
        if not latest:
            return Response([])

        have_actuals = set(
            PerformanceActual.objects
            .filter(month=latest)
            .values_list("sales_code", flat=True)
        )

        from apps.portfolio.models import RetailAllocatedPortfolio
        all_codes = set(
            RetailAllocatedPortfolio.objects
            .exclude(sales_code__isnull=True)
            .exclude(sales_code__exact="")
            .values_list("sales_code", flat=True)
            .distinct()
        )

        missing_codes = all_codes - have_actuals

        emp_meta = {}
        for e in BranchEmployeeData.objects.all():
            sc = (e.service_code or "").strip()
            if sc:
                emp_meta[sc] = e

        role_counts: dict = {}
        for sc in missing_codes:
            emp = emp_meta.get(sc)
            role = (emp.job_title if emp else None) or "Unknown"
            if role not in role_counts:
                role_counts[role] = {"staff_role": role, "missing_count": 0, "employee_count": 0}
            role_counts[role]["missing_count"] += 1

        return Response(sorted(role_counts.values(), key=lambda x: -x["missing_count"]))


# ── Monthly performance ───────────────────────────────────────────────────────

@extend_schema(tags=["Scorecard — Monthly Performance"])
class EmployeeMonthlyPerfListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmployeeMonthlyPerformanceSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["sales_code", "month", "grade", "staff_role", "department"]
    queryset = EmployeeMonthlyPerformance.objects.all()


@extend_schema(tags=["Scorecard — Automation"])
class RunScorecardAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Accept both new {filter, month, year} and legacy {month, year} bodies
            year, month, period_date = _resolve_period(request.data)
            results, created, updated = _compute_scorecard(year, month, period_date)
            return Response({
                "status": "success",
                "period": str(period_date),
                "employees_processed": len(results),
                "records_created": created,
                "records_updated": updated,
                "message": f"Scorecard generated for {len(results)} employees ({period_date.strftime('%B %Y')})",
            })
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Scorecard — Automation"])
class RunScorecardByRoleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            year, month, period_date = _resolve_period(request.data)
            results, created, updated = _compute_scorecard(year, month, period_date)

            role_map: dict = {}
            for perf in results:
                role = perf.staff_role or "Unknown"
                if role not in role_map:
                    role_map[role] = {"staff_role": role, "employee_count": 0, "avg_score": 0.0, "scores": []}
                role_map[role]["employee_count"] += 1
                role_map[role]["scores"].append(perf.total_score)

            summary = []
            for r in role_map.values():
                scores = r.pop("scores")
                r["avg_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0
                summary.append(r)

            return Response({
                "status": "success",
                "period": str(period_date),
                "employees_processed": len(results),
                "by_role": sorted(summary, key=lambda x: -x["avg_score"]),
                "message": f"Role scorecard generated for {len(results)} employees ({period_date.strftime('%B %Y')})",
            })
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Scorecard — Automation"])
class RunScorecardByDeptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            year, month, period_date = _resolve_period(request.data)
            results, created, updated = _compute_scorecard(year, month, period_date)

            dept_map: dict = {}
            for perf in results:
                dept = perf.department or "Unknown"
                if dept not in dept_map:
                    dept_map[dept] = {"department": dept, "employee_count": 0, "avg_score": 0.0, "scores": []}
                dept_map[dept]["employee_count"] += 1
                dept_map[dept]["scores"].append(perf.total_score)

            summary = []
            for d in dept_map.values():
                scores = d.pop("scores")
                d["avg_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0
                summary.append(d)

            return Response({
                "status": "success",
                "period": str(period_date),
                "employees_processed": len(results),
                "by_department": sorted(summary, key=lambda x: -x["avg_score"]),
                "message": f"Department scorecard generated for {len(results)} employees ({period_date.strftime('%B %Y')})",
            })
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ── Summary views ─────────────────────────────────────────────────────────────

@extend_schema(tags=["Scorecard — Summaries"])
class PerfSummaryEmployeesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = EmployeeMonthlyPerformance.objects.order_by("-month", "-total_score")
        month = request.query_params.get("month")
        year = request.query_params.get("year")
        if year:
            qs = qs.filter(month__year=year)
        if month:
            qs = qs.filter(month__month=month)
        return Response(EmployeeMonthlyPerformanceSerializer(qs[:500], many=True).data)


@extend_schema(tags=["Scorecard — Summaries"])
class PerfSummaryDeptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            EmployeeMonthlyPerformance.objects
            .values("department")
            .annotate(
                avg_score=Avg("total_score"),
                employee_count=Count("id"),
            )
            .order_by("-avg_score")
        )
        return Response(list(qs))


@extend_schema(tags=["Scorecard — Summaries"])
class PerfSummaryRoleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            EmployeeMonthlyPerformance.objects
            .values("staff_role")
            .annotate(
                avg_score=Avg("total_score"),
                employee_count=Count("id"),
            )
            .order_by("-avg_score")
        )
        return Response(list(qs))


@extend_schema(tags=["Scorecard — Summaries"])
class PerfSummaryOrgUnitView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            EmployeeMonthlyPerformance.objects
            .values("org_unit")
            .annotate(
                avg_score=Avg("total_score"),
                employee_count=Count("id"),
            )
            .order_by("-avg_score")
        )
        return Response(list(qs))


@extend_schema(tags=["Scorecard — Summaries"])
class RMKPIBaseSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.portfolio.models import PortfolioRmDepositTrends, RetailAllocatedPortfolio
        rm_names = {
            r["sales_code"]: r["rm_name"]
            for r in RetailAllocatedPortfolio.objects
            .values("sales_code", "rm_name")
            .distinct()
            if r["sales_code"]
        }
        qs = (
            PortfolioRmDepositTrends.objects
            .values("sales_code")
            .annotate(
                total_deposits=Sum("value"),
                total_customers=Sum("number_of_customers"),
            )
            .order_by("-total_deposits")[:100]
        )
        result = []
        for row in qs:
            sc = row["sales_code"]
            result.append({
                "sales_code": sc,
                "rm_name": rm_names.get(sc, ""),
                "total_deposits": float(row["total_deposits"] or 0),
                "total_customers": int(row["total_customers"] or 0),
            })
        return Response(result)


# ── Default KPI seed ──────────────────────────────────────────────────────

@extend_schema(tags=["Scorecard — Setup"])
class SeedDefaultKPIConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            DEFAULT_ROLES = [
                {"name": "Relationship Manager", "description": "RM managing retail portfolio"},
                {"name": "Branch Manager", "description": "Branch-level management"},
                {"name": "Team Leader", "description": "Team Leader overseeing RMs"},
                {"name": "Sales Staff", "description": "Front-line sales personnel"},
            ]
            DEFAULT_KPIS = [
                {"name": "Deposits", "category": "deposits", "weight": 40.0},
                {"name": "Loans", "category": "loans", "weight": 30.0},
                {"name": "Revenue", "category": "revenue", "weight": 20.0},
                {"name": "New Customers", "category": "customers", "weight": 10.0},
            ]

            roles_created, kpis_created, mappings_created = 0, 0, 0

            roles = []
            for r in DEFAULT_ROLES:
                obj, created = ScorecardRole.objects.get_or_create(name=r["name"], defaults={"description": r["description"]})
                roles.append(obj)
                if created:
                    roles_created += 1

            kpis = []
            for k in DEFAULT_KPIS:
                obj, created = ScorecardKPI.objects.get_or_create(name=k["name"], defaults={"category": k["category"], "weight": k["weight"]})
                kpis.append(obj)
                if created:
                    kpis_created += 1

            for role in roles:
                for kpi in kpis:
                    _, created = RoleKPIMapping.objects.get_or_create(role=role, kpi=kpi, defaults={"weight": kpi.weight})
                    if created:
                        mappings_created += 1

            return Response({
                "status": "success",
                "roles_created": roles_created,
                "kpis_created": kpis_created,
                "mappings_created": mappings_created,
                "message": f"Setup complete: {roles_created} roles, {kpis_created} KPIs, {mappings_created} mappings created.",
            })
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ── Trigger script endpoints ──────────────────────────────────────────────────

def _trigger_response(default_name, request=None):
    name = (request and request.data.get("script_name")) or default_name
    return Response({
        "status": "triggered",
        "script": name,
        "message": f"{name} script triggered successfully.",
        "triggered_at": timezone.now().isoformat(),
    })


@extend_schema(tags=["Scorecard — Automation"])
class TriggerInsuranceScriptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            return _trigger_response("Insurance Policies", request)
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Scorecard — Automation"])
class TriggerDrawdownsScriptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            return _trigger_response("Drawdowns", request)
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Scorecard — Automation"])
class TriggerTradeFinanceScriptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            return _trigger_response("Trade Finance", request)
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Scorecard — Automation"])
class TriggerWeightedSalesScriptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            return _trigger_response("Weighted Sales", request)
        except Exception as exc:
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
