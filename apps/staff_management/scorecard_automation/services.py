"""
Scorecard automation services — ported from the legacy backend.

The engine consumes the new backend's existing staff models as inputs
(StaffEmployeeData, EmployeeRoleHistory, LeaveRecord, RmKPIBaseSummary,
MissingEmployeeActual, BranchFinalEmployeeDmcData) and the ``Sc*`` models for its
own definitions/output. Calculators are loaded at runtime by mode name from
``apps.staff_management.scorecard_automation.kpi_calculations``.
"""
import importlib
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db import connection, transaction
from django.db.models import Max, Sum

from apps.staff_management.models import (
    StaffEmployeeData, EmployeeRoleHistory, LeaveRecord, RmKPIBaseSummary,
    MissingEmployeeActual, BranchFinalEmployeeDmcData,
)
from apps.staff_management.scorecard_automation.models import (
    ScKpi, ScRole, ScRoleKpiMapping, ScEmployeePerformanceActual,
    ScEmployeeMonthlyPerformance,
)


class KPIService:
    @staticmethod
    def get_kpi_by_kpi_code(kpi_code):
        return ScKpi.objects.filter(kpi_code=kpi_code).first()

    @staticmethod
    def get_all_active_kpis():
        return ScKpi.objects.filter(is_active=True)


class RoleService:
    @staticmethod
    def get_active_roles():
        return ScRole.objects.filter(is_active=True)

    @staticmethod
    def get_role_by_role_code(role_code):
        return ScRole.objects.filter(role_code=role_code).first()


class LeaveRecordService:
    @staticmethod
    def get_active_leave(sales_code):
        today = date.today()
        return LeaveRecord.objects.filter(
            sales_code=sales_code, start_date__lte=today, end_date__gte=today,
        ).first()

    @staticmethod
    def get_staff_current_year_leave_months(sales_code):
        current_year = date.today().year
        leaves = LeaveRecord.objects.filter(
            sales_code=sales_code, start_date__year=current_year
        ).order_by("-start_date")
        total_months = 0
        for leave in leaves:
            start, end = leave.start_date, leave.end_date
            total_months += (end.year - start.year) * 12 + (end.month - start.month) + 1
        return total_months


class StaffEmployeeService:
    @staticmethod
    def get_active_employees():
        return StaffEmployeeData.objects.filter(is_active=True)

    @staticmethod
    def get_employee_by_sales_code(sales_code):
        data = StaffEmployeeData.objects.filter(sales_code=sales_code).first()
        if not data:
            return None
        line_manager_details = BranchFinalEmployeeDmcData.objects.filter(
            staff_unit=data.staff_org_unit
        ).first()
        setattr(data, "line_manager", line_manager_details.staff_name if line_manager_details else None)
        setattr(data, "line_manager_title", line_manager_details.staff_role if line_manager_details else None)
        return data

    @staticmethod
    def get_employee_target_proration_details(sales_code, start_date):
        employee = StaffEmployeeService.get_employee_by_sales_code(sales_code)
        if not employee:
            return {"sales_code": sales_code, "leave_months": 0, "active_months": 12}

        year_start = date(start_date.year, 1, 1)
        year_end = date(start_date.year, 12, 31)

        if start_date > year_end:
            total_months = 0
        else:
            effective_start = max(start_date, year_start)
            total_months = (year_end.year - effective_start.year) * 12 + \
                (year_end.month - effective_start.month) + 1

        leave_months = LeaveRecordService.get_staff_current_year_leave_months(sales_code)
        active_months = max(total_months - leave_months, 0)
        return {
            "sales_code": employee.sales_code,
            "leave_months": leave_months,
            "active_months": active_months,
        }


class EmployeeRoleHistoryService:
    @staticmethod
    def get_current_role(sales_code):
        role_history = EmployeeRoleHistory.objects.filter(
            sales_code=sales_code, start_date__lte=date.today(), end_date__gte=date.today(),
        ).first()
        if not role_history:
            return None
        role = ScRole.objects.filter(role_code=role_history.role_code).first()
        setattr(role_history, "role_name", role.role_name if role else None)
        return role_history

    @staticmethod
    def get_employees_with_current_role(role_code):
        today = date.today()
        sales_codes = EmployeeRoleHistory.objects.filter(
            role_code=role_code, start_date__lte=today, end_date__gte=today,
        ).values_list("sales_code", flat=True)
        return StaffEmployeeService.get_active_employees().filter(sales_code__in=list(sales_codes))

    @staticmethod
    def get_all_current_roles(sales_codes, ref_date=None):
        if ref_date is None:
            ref_date = date.today()
        if isinstance(ref_date, str):
            ref_date = datetime.strptime(ref_date, "%Y-%m-%d").date()
        roles = EmployeeRoleHistory.objects.filter(
            sales_code__in=sales_codes, start_date__lte=ref_date, end_date__gte=ref_date,
        ).values("sales_code", "role_code", "start_date", "end_date")
        return list(roles)


class RoleKPIMappingService:
    @staticmethod
    def get_mappings_for_role(role_code, effective_date=None):
        curr_date = effective_date if effective_date else date.today()
        if isinstance(curr_date, str):
            curr_date = datetime.strptime(curr_date, "%Y-%m-%d").date()
        return ScRoleKpiMapping.objects.filter(
            role_code=role_code, effective_from__lte=curr_date, effective_to__gte=curr_date,
        ).order_by("-effective_from", "-plan_category", "kpi_order")

    @staticmethod
    def get_all_current_role_kpi_mappings(ref_date=None):
        if ref_date is None:
            ref_date = date.today()
        if isinstance(ref_date, str):
            ref_date = datetime.strptime(ref_date, "%Y-%m-%d").date()
        main_qs = ScRoleKpiMapping.objects.filter(
            is_bonus=False, effective_from__lte=ref_date, effective_to__gte=ref_date,
        )
        bonus_qs = ScRoleKpiMapping.objects.filter(
            is_bonus=True, bonus_effective_from__lte=ref_date, bonus_effective_to__gte=ref_date,
        )
        return (main_qs | bonus_qs).order_by("role_code", "-effective_from", "-plan_category", "kpi_order")

    @staticmethod
    def get_kpi_target_values(sales_code, role_start_date, kpi_details, role_kpi_mapping_details, year=None):
        if year is None:
            year = date.today().year

        base_summary = RmKPIBaseSummary.objects.filter(
            sales_code=sales_code, kpi_code=kpi_details.kpi_code, eom_date__year=year,
        ).first()
        base_value = float(base_summary.kpi_value) if base_summary else 0.0
        prev_year_value = base_value

        proration_details = StaffEmployeeService.get_employee_target_proration_details(sales_code, role_start_date)
        active_months = proration_details.get("active_months", 12)
        kpi_target = role_kpi_mapping_details.kpi_target

        if kpi_details.has_base_value:
            if 0 < kpi_target < 1:
                kpi_target = base_value * kpi_target * (
                    active_months if (role_kpi_mapping_details.target_category == "monthly" and role_kpi_mapping_details.prorate)
                    else ((active_months / 12) if role_kpi_mapping_details.prorate else 1)
                )
                curr_year_value = kpi_target if kpi_details.kpi_code == "active_customers" else (
                    (base_value + abs(kpi_target)) if kpi_details.is_increasing else (base_value - kpi_target)
                )
            elif kpi_target > 1:
                kpi_target = (
                    kpi_target * (
                        active_months if role_kpi_mapping_details.target_category == "monthly"
                        else ((active_months / 12) if role_kpi_mapping_details.prorate else 1)
                    )
                ) if role_kpi_mapping_details.prorate else kpi_target
                curr_year_value = (base_value + kpi_target) if kpi_details.is_increasing else (base_value - kpi_target)
            else:
                curr_year_value = base_value
        else:
            KPIS_TO_CHECK = ["leave_management", "hfdi_property_sales"]
            kpi_target = (
                kpi_target * (
                    active_months if role_kpi_mapping_details.target_category == "monthly"
                    else ((active_months / 12) if role_kpi_mapping_details.prorate else 1)
                )
            ) if (role_kpi_mapping_details.prorate and kpi_details.kpi_code not in KPIS_TO_CHECK) else kpi_target
            curr_year_value = kpi_target

        return {
            "has_base_value": kpi_details.has_base_value,
            "prev_year_value": prev_year_value,
            "kpi_target": abs(kpi_target),
            "curr_year_value": curr_year_value,
        }


class EmployeePerformanceActualService:
    @staticmethod
    def get_performance_actuals_for_employees_by_eom(sales_codes, eom_date=None):
        qs = ScEmployeePerformanceActual.objects.filter(sales_code__in=sales_codes)
        if eom_date:
            if isinstance(eom_date, str):
                eom_date = datetime.strptime(eom_date, "%Y-%m-%d").date()
            eom_date = eom_date.replace(day=1)
            qs = qs.filter(eom_date=eom_date)
        else:
            latest = qs.order_by("-eom_date").first()
            qs = qs.filter(eom_date=latest.eom_date) if latest else qs.none()
        return qs


class MissingEmployeeActualService:
    @staticmethod
    def is_table_empty_for_employees(sales_codes):
        return not MissingEmployeeActual.objects.filter(sales_code__in=sales_codes).exists()

    @staticmethod
    def update_missing_actuals_for_month(eom_date):
        if isinstance(eom_date, str):
            eom_date = datetime.strptime(eom_date, "%Y-%m-%d").date()
        MissingEmployeeActual.objects.filter(eom_date=eom_date).delete()
        new_records = []
        for employee in StaffEmployeeService.get_active_employees():
            current_role = EmployeeRoleHistoryService.get_current_role(employee.sales_code)
            if not current_role:
                continue
            kpi_mappings = RoleKPIMappingService.get_mappings_for_role(current_role.role_code, eom_date)
            for mapping in kpi_mappings:
                has_actual = ScEmployeePerformanceActual.objects.filter(
                    sales_code=employee.sales_code, kpi_code=mapping.kpi_code, eom_date=eom_date,
                ).exists()
                if not has_actual:
                    new_records.append(MissingEmployeeActual(
                        sales_code=employee.sales_code,
                        staff_name=employee.staff_name,
                        role_code=current_role.role_code,
                        kpi_code=mapping.kpi_code,
                        eom_date=eom_date,
                    ))
        with transaction.atomic():
            MissingEmployeeActual.objects.bulk_create(new_records)
        return new_records


class EmployeeMonthlyPerformanceService:
    @staticmethod
    def _run_monthly_kpi_scorecard_for_queryset(employees_queryset, eom_date, note_tag=""):
        employees = list(employees_queryset)
        sales_codes = [emp.sales_code for emp in employees]

        if not MissingEmployeeActualService.is_table_empty_for_employees(sales_codes):
            raise Exception(
                "Cannot run monthly KPI scorecard: there are missing actuals for these "
                "employees that must be resolved first."
            )

        employees_roles = {
            item["sales_code"]: {"role_code": item["role_code"], "start_date": item["start_date"]}
            for item in EmployeeRoleHistoryService.get_all_current_roles(sales_codes, ref_date=eom_date)
        }

        all_kpi_mappings = RoleKPIMappingService.get_all_current_role_kpi_mappings(ref_date=eom_date)
        if not all_kpi_mappings:
            raise Exception("No KPI mappings found for the given roles and date.")
        kpi_mappings_by_role = {}
        for mapping in all_kpi_mappings:
            kpi_mappings_by_role.setdefault(mapping.role_code, []).append(mapping)

        all_actuals = EmployeePerformanceActualService.get_performance_actuals_for_employees_by_eom(sales_codes, eom_date)
        actuals_by_staff = {}
        for actual in all_actuals:
            actuals_by_staff.setdefault(actual.sales_code, []).append(actual)

        kpis_by_code = {kpi.kpi_code: kpi for kpi in KPIService.get_all_active_kpis()}

        eom_year = eom_date.year if not isinstance(eom_date, str) else \
            datetime.strptime(eom_date, "%Y-%m-%d").date().year

        for employee in employees:
            sales_code = employee.sales_code
            role_info = employees_roles.get(sales_code)
            if not role_info:
                continue
            role_code = role_info["role_code"]
            start_date = role_info["start_date"]

            active_leave = LeaveRecordService.get_active_leave(sales_code)
            if isinstance(active_leave, dict) or not role_code:
                # Matches legacy: skip only when the employee has no current role.
                # Leave is reflected through proration (active_months), not a skip.
                continue

            curr_month_actuals = actuals_by_staff.get(sales_code, [])
            for kpi_mapping in kpi_mappings_by_role.get(role_code, []):
                kpi_details = kpis_by_code.get(kpi_mapping.kpi_code)
                if kpi_details is None:
                    continue

                kpi_target_details = RoleKPIMappingService.get_kpi_target_values(
                    sales_code, start_date, kpi_details, kpi_mapping, eom_year,
                )
                kpi = {
                    "kpi_code": kpi_mapping.kpi_code,
                    "kpi_order": kpi_mapping.kpi_order,
                    "mapping_category": kpi_mapping.mapping_category,
                    "kpi_weight": kpi_mapping.kpi_weight,
                    "has_base_value": kpi_target_details["has_base_value"],
                    "prev_year_value": kpi_target_details["prev_year_value"],
                    "kpi_target": kpi_target_details["kpi_target"],
                    "curr_year_value": kpi_target_details["curr_year_value"],
                    "target_category": kpi_mapping.target_category,
                    "prorate": kpi_mapping.prorate,
                }

                mode = kpi_details.kpi_calculation_mode
                module_path = f"apps.staff_management.scorecard_automation.kpi_calculations.{mode}"
                try:
                    calc_module = importlib.import_module(module_path)
                except ModuleNotFoundError as exc:
                    raise Exception(f"Calculator module not found for mode '{mode}'.") from exc
                class_name = "".join(part.capitalize() for part in mode.split("_")) + "Calculator"
                CalculatorClass = getattr(calc_module, class_name)
                calculator = CalculatorClass(sales_code, kpi, start_date, eom_date)
                calc_result = calculator.calculate(curr_month_actuals)

                ScEmployeeMonthlyPerformance.objects.filter(
                    sales_code=sales_code, eom_date=eom_date,
                    kpi_code=kpi_mapping.kpi_code, kpi_order=kpi_mapping.kpi_order,
                ).delete()

                ScEmployeeMonthlyPerformance.objects.create(
                    sales_code=sales_code,
                    eom_date=eom_date,
                    kpi_order=kpi_mapping.kpi_order,
                    kpi_code=kpi_mapping.kpi_code,
                    role_code=role_code,
                    mapping_category=kpi_mapping.mapping_category,
                    kpi_name=kpi_details.kpi_name,
                    kpi_description=kpi_details.kpi_description,
                    kpi_weight=kpi_mapping.kpi_weight,
                    prev_year_value=calc_result["prev_year_value"],
                    kpi_target=calc_result["fy_target"],
                    curr_year_value=calc_result["curr_year_value"],
                    ytd_target=calc_result["ytd_target"],
                    ytd_actual=calc_result["ytd_actual"],
                    ytd_score=Decimal(str(calc_result["ytd_score"])).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP),
                    ytd_weighted_score=Decimal(str(calc_result["weighted_score"])).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP),
                    notes=f"Monthly KPI scorecard updated for {note_tag} for {eom_date}.",
                )
        return {"status": "completed", "employees_updated": len(employees)}

    @staticmethod
    def run_monthly_kpi_scorecard(eom_date):
        employees = StaffEmployeeService.get_active_employees().order_by("employment_date")
        return EmployeeMonthlyPerformanceService._run_monthly_kpi_scorecard_for_queryset(
            employees, eom_date, note_tag="all employees"
        )

    @staticmethod
    def run_monthly_kpi_scorecard_for_employee(sales_code, eom_date):
        employees = StaffEmployeeService.get_active_employees().filter(sales_code=sales_code)
        if not employees.exists():
            return {"status": "skipped", "reason": f"Employee {sales_code} not found or not active."}
        return EmployeeMonthlyPerformanceService._run_monthly_kpi_scorecard_for_queryset(
            employees, eom_date, note_tag=f"employee {sales_code}"
        )

    @staticmethod
    def run_monthly_kpi_scorecard_by_department(department, eom_date):
        employees = StaffEmployeeService.get_active_employees().filter(department=department, is_active=True)
        return EmployeeMonthlyPerformanceService._run_monthly_kpi_scorecard_for_queryset(
            employees, eom_date, note_tag=f"department {department}"
        )

    @staticmethod
    def run_monthly_kpi_scorecard_by_current_role(role_code, eom_date):
        employees = EmployeeRoleHistoryService.get_employees_with_current_role(role_code)
        return EmployeeMonthlyPerformanceService._run_monthly_kpi_scorecard_for_queryset(
            employees, eom_date, note_tag=f"current role {role_code}"
        )

    @staticmethod
    def get_performance_summary_for_queryset(employees_queryset):
        sales_codes = list(employees_queryset.values_list("sales_code", flat=True))
        empty = {"staff_count": 0, "average_latest_month_performance": 0, "high_performers_count": 0, "latest_month": None}
        if not sales_codes:
            return empty

        latest_month = (
            ScEmployeeMonthlyPerformance.objects.filter(sales_code__in=sales_codes)
            .aggregate(latest=Max("eom_date")).get("latest")
        )
        if not latest_month:
            return empty

        perf_qs = (
            ScEmployeeMonthlyPerformance.objects
            .filter(sales_code__in=sales_codes, eom_date=latest_month)
            .values("sales_code").annotate(total_weighted_score=Sum("ytd_weighted_score"))
        )
        total_scores = [float(row["total_weighted_score"] or 0) for row in perf_qs]
        if total_scores:
            average_score = sum(total_scores) / len(total_scores)
            high_performers_count = sum(1 for s in total_scores if s >= 80)
        else:
            average_score, high_performers_count = 0, 0

        return {
            "staff_count": perf_qs.count(),
            "average_latest_month_performance": round(average_score, 5),
            "high_performers_count": high_performers_count,
            "latest_month": latest_month,
        }

    @staticmethod
    def get_monthly_performance_for_queryset(employees_queryset, year=None):
        if year is None:
            year = date.today().year
        sales_codes = tuple(employees_queryset.values_list("sales_code", flat=True))
        if not sales_codes:
            return []

        raw_sql = """
            WITH latest_roles AS (
                SELECT erh.sales_code, staff.staff_name, staff.staff_org_unit, roles.role_name
                FROM employee_role_history erh
                LEFT JOIN sc_organization_roles roles ON erh.role_code = roles.role_code
                LEFT JOIN staff_employee_data staff ON erh.sales_code = staff.sales_code
                WHERE CURRENT_DATE >= erh.start_date
                  AND (erh.end_date IS NULL OR CURRENT_DATE <= erh.end_date)
                  AND erh.sales_code = ANY(%s)
            )
            SELECT latest.sales_code, latest.staff_name, latest.staff_org_unit,
                   latest.role_name AS current_role_name, emp.eom_date,
                   bfedd.staff_name AS line_manager, bfedd.staff_role AS line_manager_title,
                   SUM(emp.ytd_weighted_score) AS total_weighted_score
            FROM sc_employee_monthly_performance emp
            INNER JOIN latest_roles latest ON emp.sales_code = latest.sales_code
            LEFT JOIN branch_final_employee_dmc_data bfedd
                   ON lower(bfedd.staff_unit) = lower(latest.staff_org_unit)
            WHERE EXTRACT(YEAR FROM emp.eom_date) = %s
            GROUP BY latest.sales_code, latest.staff_name, latest.staff_org_unit,
                     latest.role_name, emp.eom_date, bfedd.staff_name, bfedd.staff_role
            ORDER BY emp.eom_date, total_weighted_score DESC;
        """
        with connection.cursor() as cursor:
            cursor.execute(raw_sql, [list(sales_codes), year])
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
