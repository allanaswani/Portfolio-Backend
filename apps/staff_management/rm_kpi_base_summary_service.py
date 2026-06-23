"""
RM KPI base-summary service (ported from the legacy backend).

``rm_kpi_base_summary`` stores RM KPIs in LONG form — one row per
(sales_code, eom_date, kpi_code) with a single ``kpi_value``. Two ways in:

* CSV upsert (``RmKPIBaseSummaryCsvUploadView``) — one row per KPI.
* ``bulk_insert_from_kpi_query`` — the pivot/refresh: aggregates six KPIs per RM
  straight from ``customer_allocation_base`` and upserts them. Both source tables are
  managed (``default`` DB), so the raw SQL runs there.
"""
from datetime import datetime

from django.db import connection

from .models import RmKPIBaseSummary

# eom_date is the start of the current year (DATE_TRUNC('year', …)); the six KPIs are
# derived per rm_code and emitted as long-form rows via UNION ALL.
_KPI_PIVOT_SQL = """
WITH kpi_data AS (
    SELECT
        rm_code,
        SUM(net_after_expense) + SUM(ftp) - SUM(loan_loss) AS income_contribution,
        SUM(nfi) AS nfi,
        -SUM(loan_loss) AS loan_loss,
        COUNT(cust_id) AS active_two_month,
        SUM(deposit) AS deposit,
        SUM(aum_cust_id) AS aum,
        TO_CHAR(DATE_TRUNC('year', CURRENT_DATE), 'YYYY-MM-DD') AS eom_date
    FROM customer_allocation_base
    GROUP BY rm_code
)
SELECT rm_code AS sales_code, 'income_contribution' AS kpi_code, income_contribution AS kpi_value, eom_date FROM kpi_data
UNION ALL
SELECT rm_code AS sales_code, 'nfi_growth' AS kpi_code, nfi AS kpi_value, eom_date FROM kpi_data
UNION ALL
SELECT rm_code AS sales_code, 'loan_loss' AS kpi_code, loan_loss AS kpi_value, eom_date FROM kpi_data
UNION ALL
SELECT rm_code AS sales_code, 'active_customers' AS kpi_code, active_two_month AS kpi_value, eom_date FROM kpi_data
UNION ALL
SELECT rm_code AS sales_code, 'deposit_growth' AS kpi_code, deposit AS kpi_value, eom_date FROM kpi_data
UNION ALL
SELECT rm_code AS sales_code, 'portfolio_aum' AS kpi_code, aum AS kpi_value, eom_date FROM kpi_data
ORDER BY sales_code, kpi_code;
"""


def upsert_rm_kpi_base_summary(validated_data):
    """Update if (sales_code, eom_date, kpi_code) exists, else create."""
    return RmKPIBaseSummary.objects.update_or_create(
        sales_code=validated_data["sales_code"],
        eom_date=validated_data["eom_date"],
        kpi_code=validated_data["kpi_code"],
        defaults=validated_data,
    )


def bulk_insert_from_kpi_query():
    """
    Recompute the six RM KPIs from ``customer_allocation_base`` and upsert each as a
    long-form row. Returns ``{"inserted": n, "errors": [...]}``.
    """
    inserted = 0
    errors = []
    with connection.cursor() as cursor:
        try:
            cursor.execute(_KPI_PIVOT_SQL)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
        except Exception as db_exc:  # noqa: BLE001 — report DB error, don't 500
            return {"inserted": 0, "errors": [{"error": f"Database error: {db_exc}"}]}

        for row in rows:
            data = dict(zip(columns, row))
            try:
                eom_date = datetime.strptime(data["eom_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError) as date_exc:
                errors.append({"row": data, "error": f"Date parse error: {date_exc}"})
                continue
            try:
                RmKPIBaseSummary.objects.update_or_create(
                    sales_code=data["sales_code"],
                    eom_date=eom_date,
                    kpi_code=data["kpi_code"],
                    defaults={"kpi_value": data["kpi_value"]},
                )
                inserted += 1
            except Exception as orm_exc:  # noqa: BLE001 — collect per-row errors
                errors.append({"row": data, "error": f"ORM error: {orm_exc}"})
    return {"inserted": inserted, "errors": errors}
