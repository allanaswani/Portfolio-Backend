from apps.staff_management.scorecard_automation.kpi_calculations.base import (
    CalculatorBase, DataUnavailableError,
)


class TieredRangeCalculator(CalculatorBase):
    """KPI score from a tiered range table keyed by kpi_code."""
    score_ranges = {
        "audit": [
            {"min": 0, "max": 1.65, "score": 1},
            {"min": 1.66, "max": 2.49, "score": 0.8},
            {"min": 2.50, "max": float("inf"), "score": 0},
        ],
        "branch_tat_ao_pb": [
            {"min": 0, "max": 1, "score": 1},
            {"min": 1, "max": 2, "score": 0.5},
            {"min": 2, "max": float("inf"), "score": 0},
        ],
        "branch_tat_ao_bb": [
            {"min": 0, "max": 1, "score": 1},
            {"min": 1, "max": 2, "score": 0.5},
            {"min": 2, "max": float("inf"), "score": 0},
        ],
        "branch_tat_loan": [
            {"min": 0, "max": 5, "score": 1},
            {"min": 5, "max": 10, "score": 0.5},
            {"min": 10, "max": float("inf"), "score": 0},
        ],
        "rm_tat_ao": [
            {"min": 0, "max": 7, "score": 1},
            {"min": 7, "max": 10, "score": 0.5},
            {"min": 10, "max": float("inf"), "score": 0},
        ],
        "rm_tat_loan": [
            {"min": 0, "max": 10, "score": 1},
            {"min": 10, "max": 13, "score": 0.5},
            {"min": 13, "max": float("inf"), "score": 0},
        ],
        "pl_charge_disbursements": [
            {"min": 0, "max": 0.02, "score": 1},
            {"min": 0.02, "max": 0.05, "score": 0.5},
            {"min": 0.05, "max": float("inf"), "score": 0},
        ],
    }

    def assign_score(self, actual_value, score_ranges):
        for r in score_ranges:
            if r["min"] <= actual_value <= r["max"]:
                return r["score"]
        return None

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

        kpi_target = self._kpi_target()
        kpi_code = self.kpi["kpi_code"]
        raw_score = self.assign_score(actual_value, self.score_ranges.get(kpi_code, []))
        if raw_score is None:
            raw_score = 0
        capped_score = self._apply_capping(raw_score)
        weighted_score = self._apply_weighting(capped_score)

        return {
            "prev_year_value": 0,
            "fy_target": kpi_target,
            "curr_year_value": kpi_target,
            "ytd_target": kpi_target,
            "ytd_actual": actual_value,
            "ytd_score": capped_score,
            "weighted_score": weighted_score,
        }
