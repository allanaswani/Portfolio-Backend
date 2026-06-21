from apps.staff_management.scorecard_automation.kpi_calculations.base import (
    CalculatorBase, DataUnavailableError,
)


class ActualOverTargetCalculator(CalculatorBase):
    """KPI score = actual / target, capped and weighted."""
    score_ranges = {
        "active_customers": [
            {"min": 0, "max": 0.30, "score": 0.40},
            {"min": 0.30, "max": 0.40, "score": 0.50},
            {"min": 0.40, "max": 0.50, "score": 0.60},
            {"min": 0.50, "max": 0.60, "score": 0.80},
            {"min": 0.60, "max": float("inf"), "score": 1.00},
        ],
    }

    def assign_score(self, actual_value, score_ranges):
        for r in score_ranges:
            if r["min"] < actual_value <= r["max"]:
                return r["score"]
        return None

    def calculate_negative_base_score(self, base_value, ytd_target, actual_value, score_cap):
        return max(0, min(
            score_cap,
            1 - ((ytd_target - actual_value) / (ytd_target - (base_value * (self.period_end.month / 12)))),
        ))

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

        kpi_code = self.kpi["kpi_code"]
        base_value = self._fetch_base_value()
        kpi_target = self._kpi_target()
        fy_target = self._fy_target()
        ytd_target = self._ytd_target()

        if kpi_code == "income_contribution":
            raw_score = (
                self.calculate_negative_base_score(base_value, ytd_target, actual_value, score_cap=1.2)
                if ytd_target < 0 else (actual_value / ytd_target)
            )
        elif kpi_code == "active_customers":
            raw_score = self.assign_score(actual_value / base_value, self.score_ranges.get(kpi_code, []))
        else:
            raw_score = actual_value / ytd_target if ytd_target else 0
        capped_score = self._apply_capping(raw_score)
        weighted_score = self._apply_weighting(capped_score)

        return {
            "prev_year_value": base_value,
            "fy_target": kpi_target,
            "curr_year_value": fy_target,
            "ytd_target": ytd_target,
            "ytd_actual": actual_value,
            "ytd_score": capped_score,
            "weighted_score": weighted_score,
        }
