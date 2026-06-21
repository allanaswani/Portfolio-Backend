from abc import ABC, abstractmethod
from decimal import Decimal
from datetime import datetime

from apps.staff_management.scorecard_automation.services import (
    KPIService, StaffEmployeeService,
)


class KPIException(Exception):
    """Base exception for KPI calculation errors."""
    pass


class DataUnavailableError(KPIException):
    """Raised when required data is missing."""
    pass


class CalculatorBase(ABC):
    def __init__(self, sales_code, kpi, period_start, period_end):
        self.sales_code = sales_code
        self.kpi = kpi
        if isinstance(period_start, str):
            self.period_start = datetime.strptime(period_start, "%Y-%m-%d").date()
        else:
            self.period_start = period_start

        if isinstance(period_end, str):
            self.period_end = datetime.strptime(period_end, "%Y-%m-%d").date()
        else:
            self.period_end = period_end

        proration_details = StaffEmployeeService.get_employee_target_proration_details(
            sales_code, self.period_start
        )
        self.leave_months = proration_details.get("leave_months", 0)
        self.active_months = proration_details.get("active_months", 12)
        self.ytd_months = max(self._get_ytd_months() - self.leave_months, 0)

    def _get_ytd_months(self):
        return (self.period_end.year - self.period_start.year) * 12 + \
            (self.period_end.month - self.period_start.month) + 1

    def _kpi_target(self):
        return self.kpi["kpi_target"]

    def _fy_target(self):
        return self.kpi["curr_year_value"]

    def _prorate_target(self):
        if self.ytd_months == 0:
            return 0
        return (self._fy_target() / 12) * self.active_months

    def _ytd_target(self):
        return (
            self._fetch_base_value() + (self._kpi_target() / (self.ytd_months / self.active_months))
            if self.kpi["kpi_code"] == "portfolio_aum"
            else (
                (
                    (self._kpi_target() if self.kpi["kpi_code"] == "deposit_growth" else self._fy_target())
                    * (self.ytd_months / self.active_months)
                )
                if (self.kpi["target_category"] == "full_year" and self.kpi["prorate"])
                else self._fy_target()
            )
        )

    def _fetch_base_value(self):
        return self.kpi["prev_year_value"]

    def _apply_capping(self, raw_score):
        cap = KPIService.get_kpi_by_kpi_code(self.kpi["kpi_code"]).score_cap
        if cap == 0:
            return 0
        return max(0, min(raw_score, cap))

    def _apply_weighting(self, final_score):
        return Decimal(final_score) * Decimal(str(self.kpi["kpi_weight"]))

    @abstractmethod
    def fetch_actual_value(self):
        pass

    def calculate(self, curr_month_actuals):
        try:
            return self.do_calculate(curr_month_actuals)
        except Exception as exc:
            raise Exception(
                f"Error calculating KPI '{getattr(self.kpi, 'kpi_code', None) or self.kpi.get('kpi_code', None)}' "
                f"for employee '{self.sales_code}': {exc}"
            ) from exc

    @abstractmethod
    def do_calculate(self, curr_month_actuals):
        pass
