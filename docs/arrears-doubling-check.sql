-- Is the Loan Arrears KPI card doubling?  Run this on the warehouse and read
-- section 3.  Every query is read-only.
--
--   PGPASSWORD='…' psql -h 127.0.0.1 -p 5432 -U datawarehouse -d <db> \
--        -f docs/arrears-doubling-check.sql
--
-- Background: the arrears queries in services/arrears_managers.py join five
-- tables that carry NO unique constraint on the column they are joined by (all
-- are ETL-owned / managed=False mirrors). One extra row on the far side of any
-- of those joins repeats the loan, and every KPI card SUMs over that join — so
-- the money multiplies. Three of the five were collapsed in cef9d98
-- (2026-08-21); hf_customer and product_mapping were missed and are collapsed
-- now. This script proves which of them actually holds duplicates in prod.


-- ── 1. Which join keys are duplicated right now ──────────────────────────────
-- `extra_rows` is how many surplus rows exist. Anything above 0 was inflating
-- the arrears figures before the fix; the whole point of the fix is that these
-- can be non-zero without the KPI cards caring.

SELECT 'hf_customer.cust_id'                    AS join_key,
       count(*)                                 AS keys_with_dupes,
       coalesce(sum(n - 1), 0)                  AS extra_rows
FROM (SELECT cust_id, count(*) n FROM hf_customer
      WHERE cust_id IS NOT NULL GROUP BY cust_id HAVING count(*) > 1) d
UNION ALL
SELECT 'product_mapping.code',
       count(*), coalesce(sum(n - 1), 0)
FROM (SELECT code, count(*) n FROM product_mapping
      WHERE code IS NOT NULL GROUP BY code HAVING count(*) > 1) d
UNION ALL
SELECT 'retail_allocated_portfolio.cust_id',
       count(*), coalesce(sum(n - 1), 0)
FROM (SELECT cust_id, count(*) n FROM retail_allocated_portfolio
      WHERE cust_id IS NOT NULL GROUP BY cust_id HAVING count(*) > 1) d
UNION ALL
SELECT 'branch_final_employee_dmc_data.brn_code',
       count(*), coalesce(sum(n - 1), 0)
FROM (SELECT brn_code, count(*) n FROM branch_final_employee_dmc_data
      WHERE brn_code IS NOT NULL GROUP BY brn_code HAVING count(*) > 1) d
UNION ALL
SELECT 'bank_employee.bank_id',
       count(*), coalesce(sum(n - 1), 0)
FROM (SELECT trim(bank_id) k, count(*) n FROM bank_employee
      WHERE nullif(trim(bank_id), '') IS NOT NULL GROUP BY 1 HAVING count(*) > 1) d;


-- ── 2. Ground truth: the arrears book, straight off `loans`, no joins ────────
-- This is the number the KPI cards must agree with. Nothing here can fan out.

SELECT count(*)                  AS accounts_in_arrears,
       sum(total_arrears)        AS total_arrears,
       sum(euro_book_balance)    AS total_outstanding
FROM loans
WHERE days_in_arrears > 0;


-- ── 3. THE ANSWER: what the joined query produces, before and after ─────────
-- `fixed_*` is what the code now returns. `unfixed_*` is what it returned
-- while hf_customer / product_mapping were joined raw.
--
--   fixed_arrears = truth (section 2)   → the cards are correct
--   unfixed_arrears > truth             → they WERE inflated, by that ratio
--   both > truth                        → something else is fanning out; send
--                                         this output back rather than guessing

WITH truth AS (
    SELECT count(*) acc, sum(total_arrears) arr
    FROM loans WHERE days_in_arrears > 0
),
fixed AS (
    SELECT count(*) acc, sum(lns.total_arrears) arr
    FROM loans lns
    LEFT JOIN (SELECT DISTINCT ON (cust_id) cust_id, latin_surname
               FROM hf_customer WHERE cust_id IS NOT NULL
               ORDER BY cust_id, ctid DESC) c ON c.cust_id = lns.cust_id
    LEFT JOIN (SELECT DISTINCT ON (code) code, product_description
               FROM product_mapping WHERE code IS NOT NULL
               ORDER BY code, ctid DESC) pm ON lns.loan_product::integer = pm.code
    LEFT JOIN (SELECT DISTINCT ON (cust_id) cust_id, rm_name, sales_code
               FROM retail_allocated_portfolio WHERE cust_id IS NOT NULL
               ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC) rap
           ON rap.cust_id = lns.cust_id
    LEFT JOIN (SELECT DISTINCT ON (brn_code) brn_code, staff_branch
               FROM branch_final_employee_dmc_data WHERE brn_code IS NOT NULL
               ORDER BY brn_code, (staff_branch IS NULL), active DESC NULLS LAST,
                        date_update_etl DESC NULLS LAST, ctid DESC) bfedd
           ON bfedd.brn_code = lns.branch
    LEFT JOIN (SELECT DISTINCT ON (TRIM(bank_id)) TRIM(bank_id) AS bank_id, full_name
               FROM bank_employee WHERE nullif(trim(bank_id), '') IS NOT NULL
               ORDER BY TRIM(bank_id), ctid DESC) be
           ON be.bank_id = TRIM(lns.delay_officer)
    WHERE lns.days_in_arrears > 0
),
unfixed AS (
    SELECT count(*) acc, sum(lns.total_arrears) arr
    FROM loans lns
    LEFT JOIN hf_customer c ON c.cust_id = lns.cust_id
    LEFT JOIN product_mapping pm ON lns.loan_product::integer = pm.code
    LEFT JOIN (SELECT DISTINCT ON (cust_id) cust_id, rm_name, sales_code
               FROM retail_allocated_portfolio WHERE cust_id IS NOT NULL
               ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC) rap
           ON rap.cust_id = lns.cust_id
    LEFT JOIN (SELECT DISTINCT ON (brn_code) brn_code, staff_branch
               FROM branch_final_employee_dmc_data WHERE brn_code IS NOT NULL
               ORDER BY brn_code, (staff_branch IS NULL), active DESC NULLS LAST,
                        date_update_etl DESC NULLS LAST, ctid DESC) bfedd
           ON bfedd.brn_code = lns.branch
    LEFT JOIN (SELECT DISTINCT ON (TRIM(bank_id)) TRIM(bank_id) AS bank_id, full_name
               FROM bank_employee WHERE nullif(trim(bank_id), '') IS NOT NULL
               ORDER BY TRIM(bank_id), ctid DESC) be
           ON be.bank_id = TRIM(lns.delay_officer)
    WHERE lns.days_in_arrears > 0
)
SELECT t.acc   AS true_accounts,   t.arr AS true_arrears,
       f.acc   AS fixed_accounts,  f.arr AS fixed_arrears,
       u.acc   AS unfixed_accounts,u.arr AS unfixed_arrears,
       round(u.arr / nullif(t.arr, 0), 4) AS inflation_before_fix
FROM truth t, fixed f, unfixed u;
