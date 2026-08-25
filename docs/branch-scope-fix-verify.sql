-- ============================================================================
-- Verify the branch re-scoping BEFORE trusting the dashboards.
--
-- Diagnosed 25 Aug 2026: branch_portfolio scoped its movement/trend/revenue
-- queries with
--     brn_code::text IN (SELECT DISTINCT branch_code FROM hf_customer
--                        WHERE branch ILIKE '%MOMBASA%')
-- and that subquery resolved to 32 branches / 60.26B of the bank's 60.52B.
-- Every branch dashboard was showing bank-wide figures.
--
-- Fixed by scoping on the customer set instead, matching what
-- dashboard_summary/ and the NPL view already did.
--
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DW_PASSWORD" psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" \
--     -U "$DW_USER" -d "$DW_NAME" -f docs/branch-scope-fix-verify.sql
--
\set branch 'MOMBASA'
-- ============================================================================

\echo '== 1. OLD vs NEW scoping, side by side =='
-- old_* is what the dashboards showed until now. new_* is what they will show.
-- new_deposits should land in the same order of magnitude as this branch is,
-- and must be a small fraction of the bank total in query 3.
WITH codes AS (
    SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
),
custs AS (
    SELECT cust_id FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
)
SELECT
    (SELECT COUNT(*) FROM codes)                                     AS branch_codes_matched,
    (SELECT COUNT(*) FROM custs)                                     AS customers_matched,
    (SELECT SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
       FROM daily_balance_movement
      WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS','VIRTUAL')
        AND brn_code::text IN (SELECT branch_code FROM codes))       AS old_deposits,
    (SELECT SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
       FROM daily_balance_movement
      WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS','VIRTUAL')
        AND cust_cif IN (SELECT cust_id FROM custs))                 AS new_deposits;

\echo ''
\echo '== 2. The number on the screenshot: YTD movement, old vs new =='
-- Old deposit movement read KSh 4.72B against a KSh 232.12M book. The new
-- figure must be smaller than the branch book, or something is still wrong.
WITH custs AS (
    SELECT cust_id FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
)
SELECT
    SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)                AS current_total,
    SUM(dec_25_bal)   FILTER (WHERE dec_25_bal   > 0)                AS dec_2025_total,
    SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
      - SUM(dec_25_bal) FILTER (WHERE dec_25_bal > 0)                AS ytd_movement
FROM daily_balance_movement
WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS','VIRTUAL')
  AND cust_cif IN (SELECT cust_id FROM custs);

\echo ''
\echo '== 3. Sanity: this branch as a share of the bank =='
-- One branch of ~25 should be a single-digit or low-double-digit percentage.
-- Anything near 100% means the scoping is still bank-wide.
WITH custs AS (
    SELECT cust_id FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
),
branch AS (
    SELECT SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS v
    FROM daily_balance_movement
    WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS','VIRTUAL')
      AND cust_cif IN (SELECT cust_id FROM custs)
),
bank AS (
    SELECT SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS v
    FROM daily_balance_movement
    WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS','VIRTUAL')
)
SELECT branch.v AS branch_deposits, bank.v AS bank_deposits,
       ROUND(100.0 * branch.v / NULLIF(bank.v, 0), 1) AS pct_of_bank
FROM branch, bank;

\echo ''
\echo '== 4. Does the movement table agree with hf_customer on this branch? =='
-- dashboard_summary/ ("Total Deposits") sums hf_customer.total_depost_balance.
-- The movement tiles read daily_balance_movement. Now that both scope on the
-- same customers, a large remaining gap is a genuine ETL disagreement between
-- the two tables and worth raising separately -- it is no longer a scoping bug.
WITH custs AS (
    SELECT cust_id, total_depost_balance FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
)
SELECT
    (SELECT SUM(total_depost_balance) FROM custs)                    AS hf_customer_deposits,
    (SELECT SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
       FROM daily_balance_movement
      WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS','VIRTUAL')
        AND cust_cif IN (SELECT cust_id FROM custs))                 AS movement_table_deposits;

\echo ''
\echo '== 5. Same check for loans =='
WITH custs AS (
    SELECT cust_id FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
)
SELECT
    SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)                AS current_total,
    SUM(dec_25_bal)   FILTER (WHERE dec_25_bal   > 0)                AS dec_2025_total,
    SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)
      - SUM(dec_25_bal) FILTER (WHERE dec_25_bal > 0)                AS ytd_movement
FROM loan_daily_balance_movement
WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS')
  AND cust_cif IN (SELECT cust_id FROM custs);

\echo ''
\echo '== 6. Root cause, for the record: which codes does the branch name resolve to? =='
SELECT COALESCE(NULLIF(TRIM(branch_code), ''), '(blank)') AS branch_code,
       COUNT(*) AS customers_in_this_branch,
       (SELECT COUNT(DISTINCT h2.branch)
          FROM hf_customer h2
         WHERE COALESCE(NULLIF(TRIM(h2.branch_code), ''), '(blank)')
             = COALESCE(NULLIF(TRIM(h1.branch_code), ''), '(blank)')) AS branches_sharing_this_code
FROM hf_customer h1
WHERE branch ILIKE '%' || :'branch' || '%'
GROUP BY 1, h1.branch_code
ORDER BY customers_in_this_branch DESC;
