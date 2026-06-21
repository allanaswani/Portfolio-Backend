"""
Legacy/experimental "inverse growth" strategy.

NOTE: ported verbatim from the legacy backend for completeness. It is NOT a
registered calculation mode (``ScKpi.CALCULATION_CHOICES`` has no
``inverse_growth``), so the orchestrator never loads it, and it references a
couple of helpers that the legacy base class never defined. Wire it up only
after those helpers are implemented.
"""
from apps.staff_management.scorecard_automation.kpi_calculations.base import (
    CalculatorBase, DataUnavailableError,
)


class InverseGrowthCalculator(CalculatorBase):
    def fetch_actual_value(self, curr_month_actuals):
        actual = next((a for a in curr_month_actuals if a.kpi_code == self.kpi["kpi_code"]), None)
        if actual is None:
            raise DataUnavailableError(
                f"No actual value found for {self.kpi['kpi_code']} and {self.period_end}."
            )
        return actual.kpi_value

    def do_calculate(self, curr_month_actuals):
        try:
            actual_value = self.fetch_actual_value(curr_month_actuals)
        except DataUnavailableError:
            actual_value = 0

        target = self.kpi["kpi_target"]
        fy_target = self._fy_target(target)
        prorated_target = self._prorate_target(target)
        validated_ytd_target = self._validate_inputs(prorated_target)
        raw_score = (2 - (actual_value / validated_ytd_target)) if validated_ytd_target else 0
        capped_score = self._apply_capping(raw_score)
        weighted_score = self._apply_weighting(capped_score)

        return {
            "prev_year_value": 0,
            "fy_target": fy_target,
            "curr_year_value": 0,
            "ytd_target": validated_ytd_target,
            "ytd_actual": actual_value,
            "ytd_score": capped_score,
            "weighted_score": weighted_score,
        }
