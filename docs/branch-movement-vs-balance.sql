-- ============================================================================
-- Why is a branch's YTD MOVEMENT bigger than its whole deposit/loan BOOK?
--
--   Branch Portfolio, 25 Aug 2026, one branch:
--     Total Deposits       KSh 232.12M      Dep. YTD Movement   KSh 4.72B
--     Total Loans          KSh   1.68B      Loan YTD Movement   KSh 3.06B
--
-- Movement (this year minus last December) cannot exceed the book it moved, so
-- at least one side is wrong. This predates the target work — the movement tile
-- was already on that page; attaching a target is simply what made it obvious.
--
-- Run on the prod host:
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DW_PASSWORD" psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" \
--     -U "$DW_USER" -d "$DW_NAME" -f docs/branch-movement-vs-balance.sql
--
-- Set the branch you were looking at here:
\set branch 'MOMBASA'
-- ============================================================================

\echo '== 1. The two figures, side by side, from their own sources =='
-- LEFT  = dashboard_summary/  : SUM(hf_customer.total_depost_balance) for
--                               customers whose BRANCH NAME matches.
-- RIGHT = deposit_portfolio/  : daily_balance_movement rows whose BRN_CODE is in
--                               (SELECT branch_code FROM hf_customer WHERE
--                                branch ILIKE ...).
-- Those are different populations. If branch_code is not 1:1 with branch name,
-- the right-hand side quietly widens to other branches - or the whole bank.
WITH by_name AS (
    SELECT SUM(total_depost_balance) AS deposits_by_customer_branch,
           SUM(total_loans)          AS loans_by_customer_branch,
           COUNT(*)                  AS customers
    FROM hf_customer
    WHERE branch ILIKE '%' || :'branch' || '%'
),
codes AS (
    SELECT DISTINCT branch_code
    FROM hf_customer
    WHERE branch ILIKE '%' || :'branch' || '%'
),
by_code AS (
    SELECT SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS deposits_by_brn_code,
           COUNT(*)                                          AS movement_rows
    FROM daily_balance_movement
    WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
      AND brn_code::text IN (SELECT branch_code FROM codes)
)
SELECT * FROM by_name, by_code;

\echo ''
\echo '== 2. THE LIKELY CULPRIT: how many branch codes does that name resolve to? =='
-- Expect ONE. More than one means the brn_code IN (...) subquery is pulling in
-- other branches' accounts. A NULL or blank code is worse: it can match widely.
SELECT branch_code, COUNT(*) AS customers
FROM hf_customer
WHERE branch ILIKE '%' || :'branch' || '%'
GROUP BY branch_code
ORDER BY customers DESC;

\echo ''
\echo '== 3. And does that code belong to only this branch? =='
SELECT branch, COUNT(*) AS customers
FROM hf_customer
WHERE branch_code IN (
    SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
)
GROUP BY branch
ORDER BY customers DESC;

\echo ''
\echo '== 4. Is last December actually populated? =='
-- ytd_movement = yester_1_bal - SUM(dec_bal) FILTER (WHERE dec_bal > 0).
-- If dec_25_bal is mostly NULL or <= 0 the subtrahend collapses and the
-- "movement" becomes the whole book. Compare the two counts.
SELECT COUNT(*)                                             AS rows,
       COUNT(*) FILTER (WHERE yester_1_bal > 0)             AS with_current_balance,
       COUNT(*) FILTER (WHERE dec_25_bal   > 0)             AS with_dec_2025_balance,
       SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)    AS current_total,
       SUM(dec_25_bal)   FILTER (WHERE dec_25_bal   > 0)    AS dec_2025_total
FROM daily_balance_movement
WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL')
  AND brn_code::text IN (
      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
  );

\echo ''
\echo '== 5. Same two checks for loans =='
SELECT COUNT(*)                                             AS rows,
       COUNT(*) FILTER (WHERE yester_1_bal > 0)             AS with_current_balance,
       COUNT(*) FILTER (WHERE dec_25_bal   > 0)             AS with_dec_2025_balance,
       SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0)    AS current_total,
       SUM(dec_25_bal)   FILTER (WHERE dec_25_bal   > 0)    AS dec_2025_total
FROM loan_daily_balance_movement
WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS')
  AND brn_code::text IN (
      SELECT DISTINCT branch_code FROM hf_customer WHERE branch ILIKE '%' || :'branch' || '%'
  );

\echo ''
\echo '== 6. Sanity: the whole bank, so you can see how much of it one branch is claiming =='
SELECT SUM(yester_1_bal) FILTER (WHERE yester_1_bal > 0) AS bank_deposits_current,
       SUM(dec_25_bal)   FILTER (WHERE dec_25_bal   > 0) AS bank_deposits_dec_2025
FROM daily_balance_movement
WHERE customer_segment NOT IN ('INTERNAL ACCOUNTS', 'VIRTUAL');

-- How to read this
-- ----------------
-- Query 2 returns >1 code, or query 3 shows other branch names
--     -> the brn_code IN (...) scoping in deposit_portfolio/, loan_portfolio/
--        and rm_deposit_movement_ytd/ is too wide. Fix: scope movement on the
--        customer set (cust_cif IN this branch's cust_ids), the way
--        dashboard_summary/ and the NPL view already do.
-- Query 4/5 show with_dec_2025_balance far below with_current_balance
--     -> the FILTER (WHERE dec_bal > 0) is discarding the baseline, so
--        "movement" degenerates into the closing balance. Fix: COALESCE the
--        December side to 0 only for accounts that existed, and stop treating a
--        missing baseline as zero.
-- Both can be true at once, and both inflate the movement in the same direction.
