"""Back-office Dormancy and CASA, read the way the desk measures them.

**Dormancy** (the cards' RE_activation sheet) - the share of a branch's
accounts that are dormant: dormant accounts in the month over the branch's
December 2025 total. The desk's "2026_BO_Branch_Dormancy_Score - H2" sheet is
the record - Buru Buru January 1,417 / 4,846 = 0.2924, the template's figure,
and every month of every branch on the template agrees with it. Its December
totals are the base for the whole year (the business, 12 Nov 2026).

The dormant count is ``accounts`` with ``account_status = 'DORMANT'`` by
``current_branch``: on 12 Nov 2026 Buru Buru 1,659, Eldoret 2,750, Embu
1,877, Rehani 7,677 against the desk's October 1,660, 2,729, 1,867, 7,672.
``accounts`` is today's book, so it gives the month being lived through; the
months before it are the desk's sheet.

A BOM, CSO or teller gets the branch's rate; the Ultimate CSO and the Diaspora
CSM their segment's, as the template's RE_activation row puts them
("ULTIMATE", "DIASPORA"). Segments are on the desk's sheet only: no segment
count has been matched to it yet, so the month being lived through has none.

**CASA** ("Open 4 funded accounts") - accounts the person opened this year
that are funded, are not take-on accounts and are not on the STAFF customer
segment (the business, 12 Nov 2026), from
``daily_sales`` + ``product_mapping`` as the daily sales report reads them
(``daily_sales_report.py``: funded = this year's month-end balances and the
recent daily ones not all nought). Against the desk's August figures for
twelve people the count never falls below the desk's and matches it for
those whose accounts were all funded by August.
"""
from __future__ import annotations

import datetime

#: The desk's sheet: December 2025 total, then dormant accounts Jan-Oct 2026.
_SHEET = {
    "BURUBURU": (4846, [1417, 1427, 1477, 1490, 1510, 1519, 1478, 1606, 1627, 1660]),
    "ELDORET": (6266, [2488, 2498, 2561, 2597, 2619, 2633, 2538, 2605, 2631, 2729]),
    "EMBU": (3651, [1831, 1662, 1691, 1714, 1735, 1770, 1689, 1836, 1858, 1867]),
    "HARAMBEE": (7839, [2566, 2631, 2739, 2772, 2829, 2861, 2741, 2918, 3033, 3154]),
    "HURLINGHAM": (5166, [1529, 1558, 1619, 1642, 1669, 1695, 1663, 1785, 1802, 1826]),
    "KISUMU": (7142, [2779, 2802, 2854, 2899, 2927, 2930, 2668, 2877, 3007, 2983]),
    "KITENGELA": (3741, [1629, 1649, 1693, 1294, 1323, 1363, 1349, 1430, 1484, 1525]),
    "KOMAROCK": (3573, [1463, 1514, 1598, 1627, 1671, 1699, 1622, 1757, 1790, 1814]),
    "MACHAKOS": (3596, [1169, 1183, 1223, 1239, 1305, 1333, 1059, 1137, 1182, 1214]),
    "MERU": (2486, [1072, 1080, 1151, 1186, 1191, 1196, 1166, 1208, 1239, 1234]),
    "MOMBASA": (7862, [2524, 2532, 2640, 2666, 2674, 2689, 2575, 2894, 2924, 2919]),
    "NAIVASHA": (3119, [1538, 1579, 1605, 1621, 1645, 1668, 1622, 1674, 1692, 1471]),
    "NAKURU": (7412, [2672, 2701, 2727, 2777, 2799, 2826, 2182, 2479, 2598, 2646]),
    "NANYUKI": (2749, [956, 975, 1008, 1038, 1061, 1079, 1061, 1111, 1125, 1131]),
    "NYERI": (4827, [2028, 2015, 1891, 1844, 1867, 1893, 1852, 1995, 2019, 2032]),
    "REHANI": (28330, [7243, 7286, 7416, 7528, 7620, 7677, 7422, 7413, 7626, 7672]),
    "RIVERROAD": (4026, [1442, 1473, 1515, 1541, 1569, 1428, 1205, 1326, 1393, 1461]),
    "RONGAI": (2087, [614, 650, 682, 711, 725, 747, 733, 800, 810, 871]),
    "SAMEERPARK": (3522, [1384, 1399, 1294, 1168, 1051, 1095, 1100, 1192, 1215, 1245]),
    "THIKA": (4191, [1542, 1549, 1544, 1572, 1622, 1666, 1616, 1703, 1729, 1752]),
    "TRM": (4426, [1295, 1337, 1428, 1476, 1535, 1282, 1309, 1479, 1548, 1614]),
    "WESTLANDS": (3029, [993, 1017, 1023, 886, 929, 949, 909, 1019, 1055, 1068]),
}
_SEGMENTS = {
    "ULTIMATE": (5050, [885, 885, 917, 927, 947, 956, 875, 1007, 985, 1006]),
    "DIASPORA": (4476, [993, 1130, 1455, 1535, 1597, 1589, 1485, 1606, 1590, 1606]),
    "COMMERCIAL": (904, [183, 188, 188, 197, 201, 200, 167, 213, 244, 243]),
}
SHEET_YEAR = 2026


def _key(name):
    from .cx_returns import branch_of

    return branch_of(name)


def _sheet():
    return {**{_key(k): v for k, v in _SHEET.items()},
            **{k.lower(): v for k, v in _SEGMENTS.items()}}


def _live_dormant():
    """Dormant accounts per branch key, now -> {key: n}."""
    from django.core.cache import cache
    from django.db import connection

    from django.db import transaction

    found = cache.get("bo_dormant_by_branch")
    if found is None:
        try:
            # A savepoint: an unreadable table must not poison the request.
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("""
                    SELECT current_branch, count(*) FROM accounts
                    WHERE upper(trim(account_status)) = 'DORMANT'
                    GROUP BY 1""")
                rows = cur.fetchall()
        except Exception:  # noqa: BLE001 - no deposit book, no live figure
            return {}
        found = {}
        for branch, n in rows:
            key = _key(branch)
            found[key] = found.get(key, 0) + int(n)
        cache.set("bo_dormant_by_branch", found, 3600)
    return found


def dormancy(as_at, places, today=None):
    """The dormancy rate at ``as_at``'s month -> (rate, how) or (None, "").

    ``places`` are tried in order (the template's own row first, then the
    card's branch); a segment name reads the segment's row.
    """
    today = today or datetime.date.today()
    sheet = _sheet()
    for place in places:
        if not place:
            continue
        key = str(place).strip().lower() if str(place).strip().upper() in _SEGMENTS \
            else _key(place)
        if key not in sheet:
            continue
        base, months = sheet[key]
        if as_at.year == SHEET_YEAR and as_at.month <= len(months):
            return months[as_at.month - 1] / base, "the desk's dormancy sheet"
        current = (as_at.year, as_at.month) == (today.year, today.month)
        if current and key not in {k.lower() for k in _SEGMENTS}:
            n = _live_dormant().get(key)
            if n is not None:
                return n / base, "dormant accounts in the deposit book today"
        return None, ""
    return None, ""


def funded_accounts(year, month):
    """Funded, non-take-on, non-staff accounts opened in ``year`` to ``month``'s end,
    per sales code -> {CODE: n}, or None when the table cannot be read."""
    from django.core.cache import cache
    from django.db import connection

    key = f"bo_funded_accounts:{year}-{month:02d}"
    found = cache.get(key)
    if found is not None:
        return found
    end = (datetime.date(year + (month == 12), month % 12 + 1, 1))
    yy = f"{year % 100:02d}"
    from django.db import transaction

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"""
            SELECT upper(trim(d.sale_code::text)), count(*)
            FROM daily_sales d
            LEFT JOIN product_mapping p ON p.code::text = d.prod_id::text
            WHERE d.open_date >= %s AND d.open_date < %s
              AND upper(trim(COALESCE(p.product_description, ''))) <> 'TAKE ON ACCOUNT'
              AND COALESCE(d.customer_segment, '') NOT ILIKE '%%STAFF%%'
              AND (SELECT COALESCE(sum(v::numeric), 0)
                   FROM jsonb_each_text(to_jsonb(d)) e(k, v)
                   WHERE (k ~ '^[a-z]{{3}}_{yy}_bal$' OR k ~ '^yester_[0-9]+_bal$')
                     AND v ~ '^-?[0-9.]+([eE][-+]?[0-9]+)?$') <> 0
            GROUP BY 1""", [datetime.date(year, 1, 1), end])
            found = {str(code or ""): int(n) for code, n in cur.fetchall()}
    except Exception:  # noqa: BLE001 - no sales table, no live figure
        return None
    cache.set(key, found, 3600)
    return found


# ── Digital Onboarding (the Digital_Customers sheet) ────────────────────────
# The CSO card: "Digital Onboarding - Onboard 15 Digital customers monthly".
# A CSO's digital customers are the customers mapped to them on weighted sales
# (daily_sales_accounts_with_cto - the report's accounts data: a customer
# belongs to the seller on its FIRST row this year, STAFF and INTERNAL
# ACCOUNTS out, the report's sales-code corrections) who are registered on
# the mobile app (routine_registration_data.py: mobile_customers_table joined
# to customers on national ID, one row per cust_id, earliest registration,
# HF WHIZZ / DUMMY UNIT out). A customer counts once, in the month both had
# happened - onboarded and registered.

DIGITAL_ONBOARDING_SQL = """
WITH reg AS (
    SELECT c.cust_id, MIN(m.datecreated) AS registered
    FROM mobile_customers_table m
    JOIN customers c
      ON REPLACE(trim(LEADING '0' FROM trim(m.docunumber)), ' ', '')
       = REPLACE(trim(LEADING '0' FROM trim(c.national_id)), ' ', '')
    WHERE c.branch IS NOT NULL AND c.branch NOT IN ('HF WHIZZ', 'DUMMY UNIT')
    GROUP BY c.cust_id
), w AS (
    SELECT DISTINCT ON (cust_cif) cust_cif, sale_code, cust_open_date
    FROM daily_sales_accounts_with_cto
    WHERE acc_open_date >= %(start)s
      AND COALESCE(customer_segment, '') NOT IN ('STAFF', 'INTERNAL ACCOUNTS')
    ORDER BY cust_cif, ctid
)
SELECT w.sale_code,
       extract(month FROM greatest(w.cust_open_date::date, r.registered::date))::int,
       count(*)
FROM w JOIN reg r ON r.cust_id::text = w.cust_cif::text
WHERE w.cust_open_date::date >= %(start)s AND w.cust_open_date::date < %(end)s
  AND greatest(w.cust_open_date::date, r.registered::date) < %(end)s
GROUP BY 1, 2
"""


def _clean_sale_code(code):
    from .weighted_sales_new_customers import SALE_CODE_FIXES

    code = str(code or "").replace(" ", "")
    return SALE_CODE_FIXES.get(code, code).strip().upper()


def digital_onboarded(year):
    """{SALES CODE: {"month": customers}} for ``year``, or None while it is
    first read (in the background) or when the tables cannot be read."""
    from .feed_cache import cached

    def compute():
        from django.db import connection, transaction

        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = 600000")
            cur.execute(DIGITAL_ONBOARDING_SQL, {"start": datetime.date(year, 1, 1),
                                                 "end": datetime.date(year + 1, 1, 1)})
            rows = cur.fetchall()
        out = {}
        for code, month, n in rows:
            months = out.setdefault(_clean_sale_code(code), {})
            months[str(int(month))] = months.get(str(int(month)), 0) + int(n)
        return out

    try:
        return cached(f"bo_digital_onboarded:{year}", compute)
    except Exception:  # noqa: BLE001 - no registration data, no live figure
        return None


def digital_onboarded_to(year, month, code):
    """The person's running total January to ``month`` -> int, or None when
    the figures are not read yet."""
    found = digital_onboarded(year)
    if found is None:
        return None
    months = found.get(_clean_sale_code(code), {})
    return sum(n for m, n in months.items() if int(m) <= month)
