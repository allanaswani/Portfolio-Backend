-- Why the Loan Arrears list shows an empty Grade column and KSh 0 YTD Loan Loss
-- on every row. Read-only. Run it over TCP (a plain "psql -U ..." hits the unix
-- socket and fails with "Peer authentication failed"):
--
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DW_PASSWORD" psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" \
--     -U "$DW_USER" -d "$DW_NAME" -f docs/loan-arrears-grade-blank.sql
--
-- Both columns come ONLY from loans_mom_ifrs_movement, filtered to the current
-- year:  WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
-- so there are exactly two possible causes. These queries tell them apart.

-- CAUSE A — the IFRS movement ETL has not loaded the current year.
-- If rows_this_year is 0, every Grade is NULL and every loan loss is 0 for the
-- whole app, and no backend change can fix it: the ETL has to run.
SELECT EXTRACT(YEAR FROM eom_date) AS yr,
       COUNT(*)                    AS rows,
       MAX(eom_date)               AS latest_eom
FROM loans_mom_ifrs_movement
GROUP BY 1 ORDER BY 1 DESC;

SELECT COUNT(*) AS rows_this_year
FROM loans_mom_ifrs_movement
WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE);

-- CAUSE B — the account numbers do not join. The queries strip leading zeros
-- from both sides; if the two tables format accounts differently (branch
-- prefix, numeric vs text, embedded spaces) nothing matches even when the data
-- is loaded. matched should be close to arrears_loans.
WITH mov AS (
    SELECT DISTINCT REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS acct
    FROM loans_mom_ifrs_movement
    WHERE EXTRACT(YEAR FROM eom_date) = EXTRACT(YEAR FROM CURRENT_DATE)
)
SELECT COUNT(*) AS arrears_loans,
       COUNT(mov.acct) AS matched,
       COUNT(*) - COUNT(mov.acct) AS unmatched
FROM loans lns
LEFT JOIN mov ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov.acct
WHERE lns.days_in_arrears > 0;

-- Side-by-side sample of how each table writes an account number.
SELECT 'loans' AS src, loan_account_no AS raw,
       REGEXP_REPLACE(TRIM(loan_account_no), '^0+', '') AS stripped
FROM loans WHERE days_in_arrears > 0 LIMIT 5;

SELECT 'ifrs_movement' AS src, lns_account AS raw,
       REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS stripped
FROM loans_mom_ifrs_movement LIMIT 5;

-- Separately: rows where the core banking system reports days in arrears but a
-- zero arrears amount (e.g. REFLEX FOOTWEAR, 2 days / KSh 0). This is source
-- data, not a reporting bug — the arrears cleared but the counter has not reset.
SELECT COUNT(*) AS zero_arrears_but_in_arrears
FROM loans WHERE days_in_arrears > 0 AND COALESCE(total_arrears, 0) = 0;

-- And the year-1 sentinel dates that used to render as "01 Jan 1".
SELECT COUNT(*) AS sentinel_next_installment_dates
FROM loans
WHERE days_in_arrears > 0
  AND (next_installment_date < DATE '1950-01-01' OR next_installment_date IS NULL);
