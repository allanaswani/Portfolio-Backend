"""
HFDI dashboard aggregations (raw SQL, ported from the legacy backend).

Each function reads the managed HFDI tables that exist in this backend
(hfdi_sales_data, projects, hfdi_target_feedback, hfdi_performance_target_feedback,
hfdi_legacy_projects/_sales_data, hfdi_crm_projects/_sales_data, hfdi_manual_sales_data)
and returns plain lists of dicts for the chart endpoints.
"""
from django.db import connection

# Month-pivot summaries (Jan..Dec) keyed by project. The three legacy helpers
# were identical except for the measured column, so they share one query here.
_MONTH_PIVOT_MEASURES = {"mtd_volume", "mtd_value", "ytd_income"}


def _rows_as_dicts(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def monthly_pivot_summary(measure: str):
    """Per-project Jan..Dec totals of `measure` for the current year."""
    if measure not in _MONTH_PIVOT_MEASURES:
        raise ValueError(f"Unsupported measure: {measure}")
    months = ["jan", "feb", "march", "apr", "may", "june", "july", "aug", "sept", "oct", "nov", "dec"]
    cases = ",\n".join(
        f"""sum(CASE WHEN date_trunc('month', month::date) =
                (date_trunc('month', date_trunc('year', current_date)::date) + INTERVAL '{i} month')::date
                THEN {measure} ELSE 0 END) AS {name}"""
        for i, name in enumerate(months)
    )
    sql = f"""
        SELECT project_id AS project_id_data, {cases}
        FROM hfdi_sales_data
        WHERE date_trunc('year', month::date) = date_trunc('year', current_date)::date
        GROUP BY project_id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return _rows_as_dicts(cursor)


def months_already_entered():
    """Latest recording date per (project, month) in hfdi_sales_data."""
    sql = """
        SELECT hsd.project_id, hp.name AS project_name, month,
               max(recording_date) AS max_record_date
        FROM hfdi_sales_data hsd
        LEFT JOIN projects hp ON hsd.project_id = hp.id
        GROUP BY month, hsd.project_id, hp.name
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return _rows_as_dicts(cursor)


def projects_monthly_performance():
    """Bank-wide monthly actuals (volume/value/income) with income MoM lag."""
    sql = """
        WITH MonthlySummary AS (
            SELECT month AS dates_months,
                   SUM(mtd_volume) AS volume_actual,
                   SUM(mtd_value) AS value_actual,
                   SUM(ytd_income) AS income_actual
            FROM hfdi_sales_data
            GROUP BY month
        )
        SELECT dates_months, volume_actual, value_actual, income_actual,
               LAG(income_actual) OVER (ORDER BY dates_months ASC) AS income_lags,
               income_actual - LAG(income_actual) OVER (ORDER BY dates_months ASC) AS income_difference
        FROM MonthlySummary
        ORDER BY dates_months ASC
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return _rows_as_dicts(cursor)


# Shared CTE body for the YTD revenue-point summaries. The aggregate and
# per-project variants group `original_target` differently (the legacy aggregate
# grouped by project_name only; the per-project one also kept the target dates),
# so the GROUP BY is parameterised to preserve each variant's exact result.
def _revenue_ctes(*, per_project: bool) -> str:
    if per_project:
        extra_cols = "htf.target_sales_end_date, htf.target_collections_end_date,"
        group_by = "GROUP BY x.project_name, htf.target_sales_end_date, htf.target_collections_end_date"
    else:
        extra_cols = ""
        group_by = "GROUP BY x.project_name"
    return f"""
    WITH project_data_names AS (
        SELECT project_id, project_name FROM hfdi_legacy_projects
        UNION SELECT project_id, project_name FROM hfdi_crm_projects
    ),
    original_target AS (
        SELECT x.project_name AS project_name,
               {extra_cols}
               max(htf.volume) AS volume_target, max(htf.value) AS value_target,
               max(htf.collections_value) AS collections_value_target,
               max(htf.income) AS income_target,
               max(extract(DOY FROM target_start_date::date)) AS target_start_day,
               max(extract(DOY FROM current_date)) AS current_date_day,
               max(extract(DOY FROM target_sales_end_date::date)) AS target_sales_end_day,
               max(extract(DOY FROM target_collections_end_date::date)) AS target_collections_end_day
        FROM hfdi_performance_target_feedback htf
        LEFT JOIN project_data_names x ON x.project_id = htf.project_id
        WHERE date_trunc('year', month::date) = date_trunc('year', current_date)
        {group_by}
    ),
    ytd_targets AS (
        SELECT project_name,
               CEIL(volume_target*(current_date_day/NULLIF(target_sales_end_day,0)))::INT AS ytd_volume_target,
               CEIL(value_target*(current_date_day/NULLIF(target_collections_end_day,0)))::INT AS ytd_value_target,
               CEIL(collections_value_target*(current_date_day/NULLIF(target_collections_end_day,0)))::INT AS ytd_collections_value_target,
               CEIL(income_target*(current_date_day/extract(DOY FROM MAKE_DATE(EXTRACT(YEAR FROM CURRENT_DATE)::INT, 12, 31))))::INT AS ytd_income_target
        FROM original_target
    ),
    hfdi_sales_union AS (
        SELECT project_id, sale_month, mtd_volume, mtd_value, ytd_volume, ytd_value FROM hfdi_legacy_sales_data
        UNION SELECT project_id, sale_month, mtd_volume, mtd_value, ytd_volume, ytd_value FROM hfdi_crm_sales_data
    ),
    actuals_sales_hfdi AS (
        SELECT hp.project_name AS project_name, ytd_volume AS actual_ytd_volume, ytd_value AS actual_ytd_value,
               row_number() OVER (PARTITION BY hsd.project_id ORDER BY sale_month::date DESC, hsd.project_id DESC) AS rank
        FROM hfdi_sales_union hsd
        LEFT JOIN project_data_names hp ON hsd.project_id = hp.project_id
        WHERE date_trunc('year', sale_month::date) = date_trunc('year', current_date)
    ),
    actual_achieved AS (SELECT * FROM actuals_sales_hfdi WHERE rank = 1),
    actuals_revenue AS (
        SELECT hp.project_name AS project_name, ytd_revenue_booked AS actual_income,
               row_number() OVER (PARTITION BY hsd.project_id ORDER BY sale_month::date DESC, hsd.project_id DESC) AS rank
        FROM hfdi_manual_sales_data hsd
        LEFT JOIN project_data_names hp ON hsd.project_id = hp.project_id
        WHERE date_trunc('year', sale_month::date) = date_trunc('year', current_date)
    ),
    actual_revenue AS (SELECT * FROM actuals_revenue WHERE rank = 1)
"""

_REVENUE_POINT_AGG_TAIL = """
    SELECT sum(ot.volume_target) AS volume_target, sum(ot.value_target) AS value_target,
           sum(ot.collections_value_target) AS collections_value_target,
           sum(ot.income_target) AS income_target,
           sum(yt.ytd_volume_target) AS ytd_volume_target,
           sum(yt.ytd_value_target) AS ytd_value_target,
           sum(yt.ytd_collections_value_target) AS ytd_collections_value_target,
           sum(yt.ytd_income_target) AS ytd_income_target,
           sum(at.actual_ytd_volume) AS actual_ytd_volume,
           sum(ar.actual_income) AS actual_income,
           sum(at.actual_ytd_value) AS actual_ytd_value
    FROM original_target ot
    LEFT JOIN ytd_targets yt ON ot.project_name = yt.project_name
    LEFT JOIN actual_achieved at ON ot.project_name = at.project_name
    LEFT JOIN actual_revenue ar ON ar.project_name = at.project_name
"""

_REVENUE_POINT_PER_PROJECT_TAIL = """
    SELECT ot.project_name, ot.target_sales_end_date, ot.target_collections_end_date,
           MAKE_DATE(EXTRACT(YEAR FROM CURRENT_DATE)::INT, 12, 31) AS target_revenue_end_date,
           sum(ot.volume_target) AS volume_target, sum(ot.value_target) AS value_target,
           sum(ot.collections_value_target) AS collections_value_target,
           sum(ot.income_target) AS income_target,
           sum(yt.ytd_volume_target) AS ytd_volume_target,
           sum(yt.ytd_value_target) AS ytd_value_target,
           sum(yt.ytd_collections_value_target) AS ytd_collections_value_target,
           sum(yt.ytd_income_target) AS ytd_income_target,
           sum(at.actual_ytd_volume) AS actual_ytd_volume,
           sum(ar.actual_income) AS actual_income,
           sum(at.actual_ytd_value) AS actual_ytd_value
    FROM original_target ot
    LEFT JOIN ytd_targets yt ON ot.project_name = yt.project_name
    LEFT JOIN actual_achieved at ON ot.project_name = at.project_name
    LEFT JOIN actual_revenue ar ON ar.project_name = at.project_name
    GROUP BY ot.project_name, ot.target_sales_end_date, ot.target_collections_end_date
"""


def revenue_point_ytd():
    with connection.cursor() as cursor:
        cursor.execute(_revenue_ctes(per_project=False) + _REVENUE_POINT_AGG_TAIL)
        return _rows_as_dicts(cursor)


def revenue_point_ytd_by_project():
    with connection.cursor() as cursor:
        cursor.execute(_revenue_ctes(per_project=True) + _REVENUE_POINT_PER_PROJECT_TAIL)
        return _rows_as_dicts(cursor)
