from datetime import datetime

# Treat January 1-9 as still belonging to previous year (ETL grace period)
current_year = (
    datetime.now().year - 1
    if datetime.now().month == 1 and datetime.now().day < 10
    else datetime.now().year
)
previous_year = current_year - 1
year_before_last = current_year - 2

cy = str(current_year)[-2:]
py = str(previous_year)[-2:]
ybl = str(year_before_last)[-2:]

# Ordered list of (date_key, column_alias) for monthly balance movement
MONTH_DATES = [
    (f"{year_before_last}-01-01", f"dec_{ybl}"),
    (f"{previous_year}-03-01",    f"mar_{py}"),
    (f"{previous_year}-06-01",    f"jun_{py}"),
    (f"{previous_year}-09-01",    f"sep_{py}"),
    (f"{previous_year}-12-01",    f"dec_{py}"),
    (f"{current_year}-01-01",     f"jan_{cy}"),
    (f"{current_year}-02-01",     f"feb_{cy}"),
    (f"{current_year}-03-01",     f"mar_{cy}"),
    (f"{current_year}-04-01",     f"apr_{cy}"),
    (f"{current_year}-05-01",     f"may_{cy}"),
    (f"{current_year}-06-01",     f"jun_{cy}"),
    (f"{current_year}-07-01",     f"jul_{cy}"),
    (f"{current_year}-08-01",     f"aug_{cy}"),
    (f"{current_year}-09-01",     f"sep_{cy}"),
    (f"{current_year}-10-01",     f"oct_{cy}"),
    (f"{current_year}-11-01",     f"nov_{cy}"),
    (f"{current_year}-12-01",     f"dec_{cy}"),
]


def _yester_case(table_alias: str, col: str, cy: str, py: str) -> str:
    """Return the CASE expression for yester_1_bal / yester_2_bal fallback logic."""
    prefix = f"{table_alias}." if table_alias else ""
    return f"""
        CASE
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 2)  THEN SUM({prefix}jan_{cy}_bal) FILTER (WHERE {prefix}jan_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 3)  THEN SUM({prefix}feb_{cy}_bal) FILTER (WHERE {prefix}feb_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 4)  THEN SUM({prefix}mar_{cy}_bal) FILTER (WHERE {prefix}mar_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 5)  THEN SUM({prefix}apr_{cy}_bal) FILTER (WHERE {prefix}apr_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 6)  THEN SUM({prefix}may_{cy}_bal) FILTER (WHERE {prefix}may_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 7)  THEN SUM({prefix}jun_{cy}_bal) FILTER (WHERE {prefix}jun_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 8)  THEN SUM({prefix}jul_{cy}_bal) FILTER (WHERE {prefix}jul_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 9)  THEN SUM({prefix}aug_{cy}_bal) FILTER (WHERE {prefix}aug_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 10) THEN SUM({prefix}sep_{cy}_bal) FILTER (WHERE {prefix}sep_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 11) THEN SUM({prefix}oct_{cy}_bal) FILTER (WHERE {prefix}oct_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 12) THEN SUM({prefix}nov_{cy}_bal) FILTER (WHERE {prefix}nov_{cy}_bal > 0)
            WHEN (SUM({prefix}{col}) = 0 AND EXTRACT(month FROM current_date) = 1)  THEN SUM({prefix}dec_{py}_bal) FILTER (WHERE {prefix}dec_{py}_bal > 0)
            ELSE SUM({prefix}{col}) FILTER (WHERE {prefix}{col} > 0)
        END
    """


def _prev_month_case(table_alias: str, cy: str, py: str) -> str:
    """Return CASE expression selecting the previous calendar month balance."""
    prefix = f"{table_alias}." if table_alias else ""
    return f"""
        CASE
            WHEN EXTRACT(month FROM current_date) = 2  THEN SUM({prefix}jan_{cy}_bal) FILTER (WHERE {prefix}jan_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 3  THEN SUM({prefix}feb_{cy}_bal) FILTER (WHERE {prefix}feb_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 4  THEN SUM({prefix}mar_{cy}_bal) FILTER (WHERE {prefix}mar_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 5  THEN SUM({prefix}apr_{cy}_bal) FILTER (WHERE {prefix}apr_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 6  THEN SUM({prefix}may_{cy}_bal) FILTER (WHERE {prefix}may_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 7  THEN SUM({prefix}jun_{cy}_bal) FILTER (WHERE {prefix}jun_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 8  THEN SUM({prefix}jul_{cy}_bal) FILTER (WHERE {prefix}jul_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 9  THEN SUM({prefix}aug_{cy}_bal) FILTER (WHERE {prefix}aug_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 10 THEN SUM({prefix}sep_{cy}_bal) FILTER (WHERE {prefix}sep_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 11 THEN SUM({prefix}oct_{cy}_bal) FILTER (WHERE {prefix}oct_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 12 THEN SUM({prefix}nov_{cy}_bal) FILTER (WHERE {prefix}nov_{cy}_bal > 0)
            WHEN EXTRACT(month FROM current_date) = 1  THEN SUM({prefix}dec_{py}_bal) FILTER (WHERE {prefix}dec_{py}_bal > 0)
            ELSE SUM({prefix}dec_{py}_bal) FILTER (WHERE {prefix}dec_{py}_bal > 0)
        END
    """


BRN_CASE = f"""
    CASE
        WHEN brn_code::text = '230' THEN 'BURUBURU BRANCH'
        WHEN brn_code::text = '410' THEN 'ELDORET BRANCH'
        WHEN brn_code::text = '25'  THEN 'EMBU BRANCH'
        WHEN brn_code::text = '220' THEN 'HARAMBEE AVE BRANCH'
        WHEN brn_code::text = '100' THEN 'HEAD OFFICE'
        WHEN brn_code::text = '109' THEN 'HF WHIZZ'
        WHEN brn_code::text = '19'  THEN 'HURLINGHAM BRANCH'
        WHEN brn_code::text = '600' THEN 'KISII BRANCH'
        WHEN brn_code::text = '16'  THEN 'KITENGELA BRANCH'
        WHEN brn_code::text = '23'  THEN 'KOMAROCK BRANCH'
        WHEN brn_code::text = '24'  THEN 'MACHAKOS BRANCH'
        WHEN brn_code::text = '520' THEN 'MERU BRANCH'
        WHEN brn_code::text = '300' THEN 'MOMBASA BRANCH'
        WHEN brn_code::text = '17'  THEN 'NAIVASHA BRANCH'
        WHEN brn_code::text = '400' THEN 'NAKURU BRANCH'
        WHEN brn_code::text = '22'  THEN 'NANYUKI BRANCH'
        WHEN brn_code::text = '510' THEN 'NYERI BRANCH'
        WHEN brn_code::text = '200' THEN 'REHANI BRANCH'
        WHEN brn_code::text = '20'  THEN 'RIVERROAD BRANCH'
        WHEN brn_code::text = '250' THEN 'RONGAI BRANCH'
        WHEN brn_code::text = '270' THEN 'SAMEER BRANCH'
        WHEN brn_code::text = '500' THEN 'THIKA BRANCH'
        WHEN brn_code::text = '260' THEN 'TRM BRANCH'
        WHEN brn_code::text = '280' THEN 'WESTLANDS BRANCH'
        ELSE 'HEAD OFFICE'
    END
"""
