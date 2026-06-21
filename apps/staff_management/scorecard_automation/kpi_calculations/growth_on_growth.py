from apps.staff_management.scorecard_automation.kpi_calculations.base import (
    CalculatorBase, DataUnavailableError,
)


class GrowthOnGrowthCalculator(CalculatorBase):
    """KPI score based on growth over a base value toward a YTD target."""

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

        base_value = self._fetch_base_value()
        fy_target = self.kpi["kpi_target"]
        ytd_target = self._fetch_base_value() + ((fy_target / 12) + self._get_ytd_months())

        raw_score = (actual_value - base_value) / (ytd_target - base_value) if (ytd_target - base_value) else 0
        capped_score = self._apply_capping(raw_score)
        weighted_score = self._apply_weighting(capped_score)

        return {
            "prev_year_value": base_value,
            "fy_target": fy_target,
            "curr_year_value": base_value + fy_target,
            "ytd_target": ytd_target,
            "ytd_actual": actual_value,
            "ytd_score": capped_score,
            "weighted_score": weighted_score,
        }
