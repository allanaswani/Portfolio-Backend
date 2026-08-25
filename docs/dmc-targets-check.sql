-- ============================================================================
-- DMC performance targets — verify what the new target-vs-actual KPI tiles read
--
-- Run on the prod host (the container image has no psql client):
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DW_PASSWORD" psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" \
--     -U "$DW_USER" -d "$DW_NAME" -f docs/dmc-targets-check.sql
--
-- What the API does, so you can check it by hand:
--   * branch / zone / bank targets  -> SUM over branch_final_employee_dmc_data
--     (one row per branch, so every branch is counted exactly once)
--   * RM / team-leader targets      -> SUM over branch_employee_dmc_data
--     (one row per sales staff member)
--   * the two are NEVER added together for the same metric — that would roughly
--     double every branch, zone and bank figure on screen.
-- ============================================================================

\echo '== 1. Grain check: is the branch table really one row per branch? =='
-- Expect rows = branches (22 in production, Aug 2026). If rows > branches the
-- ETL has started writing per-employee rows and the bank/zone rollups will
-- double-count — that is the one thing that would silently break these tiles.
SELECT COUNT(*)                        AS rows,
       COUNT(DISTINCT staff_branch)    AS branches,
       COUNT(DISTINCT brn_code)        AS branch_codes,
       COUNT(DISTINCT staff_zone)      AS zones
FROM branch_final_employee_dmc_data
WHERE COALESCE(active, 1) = 1 AND COALESCE(exit, 0) <> 1;

\echo ''
\echo '== 2. Staff table grain (RM / team-leader scopes) =='
SELECT COUNT(*)                        AS rows,
       COUNT(DISTINCT sales_code)      AS sales_codes,
       COUNT(DISTINCT team_leader)     AS team_leaders,
       COUNT(DISTINCT staff_branch)    AS branches
FROM branch_employee_dmc_data
WHERE COALESCE(active, 1) = 1 AND COALESCE(staff_exit, 0) <> 1;

\echo ''
\echo '== 3. Which planning cycle is loaded? =='
-- The API filters on EXTRACT(YEAR FROM start_date). If the current year is not
-- here it falls back to every row rather than showing a screen of zeros, and
-- reports that as "year_filtered": false.
SELECT EXTRACT(YEAR FROM start_date)::int AS cycle_year,
       COUNT(*) AS rows,
       MAX(updated_at) AS last_updated
FROM branch_final_employee_dmc_data
GROUP BY 1 ORDER BY 1 DESC;

\echo ''
\echo '== 4. Bank-wide plan (what the GCEO tiles show) =='
SELECT SUM(target_deposits_value)      AS deposits_growth_fy,
       ROUND(SUM(target_deposits_value) * EXTRACT(DOY FROM CURRENT_DATE) / 365) AS deposits_growth_ytd,
       SUM(target_asset_growth_value)  AS asset_growth_fy,
       SUM(target_pbt_revenue)         AS pbt_revenue_fy,
       SUM(target_new_customers)       AS new_customers_fy,
       SUM(target_loan_disbursement)   AS loan_disbursement_fy
FROM branch_final_employee_dmc_data
WHERE COALESCE(active, 1) = 1 AND COALESCE(exit, 0) <> 1;

\echo ''
\echo '== 5. Per branch — compare against each BM dashboard =='
SELECT staff_branch,
       brn_code,
       staff_zone,
       target_deposits_value                                              AS deposits_growth_fy,
       ROUND(target_deposits_value * EXTRACT(DOY FROM CURRENT_DATE) / 365) AS deposits_growth_ytd,
       target_asset_growth_value                                          AS asset_growth_fy,
       target_new_customers                                               AS new_customers_fy
FROM branch_final_employee_dmc_data
WHERE COALESCE(active, 1) = 1 AND COALESCE(exit, 0) <> 1
ORDER BY target_deposits_value DESC NULLS LAST;

\echo ''
\echo '== 6. Double-count check: branch row vs the sum of its own RMs =='
-- These two columns measure the SAME thing at different grains. They should be
-- roughly equal. The API deliberately reports the branch row (bbm_target); if
-- it summed both you would see bbm_target + rm_sum on screen.
SELECT b.staff_branch,
       b.target_deposits_value                    AS bbm_target,
       COALESCE(SUM(s.target_deposits_value), 0)  AS rm_sum,
       COUNT(s.id)                                AS rm_rows
FROM branch_final_employee_dmc_data b
LEFT JOIN branch_employee_dmc_data s
       ON UPPER(BTRIM(s.staff_branch)) = UPPER(BTRIM(b.staff_branch))
      AND COALESCE(s.active, 1) = 1 AND COALESCE(s.staff_exit, 0) <> 1
WHERE COALESCE(b.active, 1) = 1 AND COALESCE(b.exit, 0) <> 1
GROUP BY b.staff_branch, b.target_deposits_value
ORDER BY b.staff_branch;

\echo ''
\echo '== 7. Metrics with nothing loaded (tiles will read "no target set") =='
SELECT 'target_pbt_revenue'        AS metric, COUNT(*) FILTER (WHERE COALESCE(target_pbt_revenue, 0)        <> 0) AS branches_with_a_target FROM branch_final_employee_dmc_data
UNION ALL SELECT 'target_deposits_value',     COUNT(*) FILTER (WHERE COALESCE(target_deposits_value, 0)     <> 0) FROM branch_final_employee_dmc_data
UNION ALL SELECT 'target_asset_growth_value', COUNT(*) FILTER (WHERE COALESCE(target_asset_growth_value, 0) <> 0) FROM branch_final_employee_dmc_data
UNION ALL SELECT 'target_new_customers',      COUNT(*) FILTER (WHERE COALESCE(target_new_customers, 0)      <> 0) FROM branch_final_employee_dmc_data
UNION ALL SELECT 'target_npl',                COUNT(*) FILTER (WHERE COALESCE(target_npl, 0)                <> 0) FROM branch_final_employee_dmc_data
UNION ALL SELECT 'target_forex',              COUNT(*) FILTER (WHERE COALESCE(target_forex, 0)              <> 0) FROM branch_final_employee_dmc_data;
