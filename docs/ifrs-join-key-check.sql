-- STEP 2 after docs/loan-arrears-grade-blank.sql.
--
-- That script established CAUSE A: loans_mom_ifrs_movement holds ONLY 2025 rows
-- (93,971, latest eom 2025-07-01), so rows_this_year = 0 and every Grade / YTD
-- Loan Loss is blank. Its "matched = 0 of 8,317" line does NOT additionally
-- prove a key mismatch — that query filtered the movement side to the current
-- year as well, so it could only ever return 0.
--
-- This script asks the question that actually matters: WHEN the ETL loads 2026,
-- will the account numbers join? It drops the year filter and tests every
-- plausible key pairing against the 2025 data. Read-only.
--
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DW_PASSWORD" psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" \
--     -U "$DW_USER" -d "$DW_NAME" -f docs/ifrs-join-key-check.sql

\pset footer off

-- A. loans.loan_account_no  <->  ifrs.lns_account   (what the app joins on today)
--    If matched is close to arrears_loans, the key is fine and loading 2026 is
--    the whole fix. If matched is ~0, the join is ALSO broken and loading the
--    ETL alone will not populate the Grade column.
WITH mov AS (
    SELECT DISTINCT REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS acct
    FROM loans_mom_ifrs_movement
)
SELECT 'loan_account_no -> lns_account' AS pairing,
       COUNT(*)                         AS arrears_loans,
       COUNT(mov.acct)                  AS matched,
       COUNT(*) - COUNT(mov.acct)       AS unmatched
FROM loans lns
LEFT JOIN mov ON REGEXP_REPLACE(TRIM(lns.loan_account_no), '^0+', '') = mov.acct
WHERE lns.days_in_arrears > 0;

-- B. Same, but against the OTHER account column on loans.
WITH mov AS (
    SELECT DISTINCT REGEXP_REPLACE(TRIM(lns_account), '^0+', '') AS acct
    FROM loans_mom_ifrs_movement
)
SELECT 'account_no -> lns_account' AS pairing,
       COUNT(*)                    AS arrears_loans,
       COUNT(mov.acct)             AS matched,
       COUNT(*) - COUNT(mov.acct)  AS unmatched
FROM loans lns
LEFT JOIN mov ON REGEXP_REPLACE(TRIM(lns.account_no), '^0+', '') = mov.acct
WHERE lns.days_in_arrears > 0;

-- C. Customer-level fallback: loans.cust_id <-> ifrs.cust_code. Grade is a
--    per-facility attribute so this is a worse key, but if only this matches it
--    tells us lns_account is a different numbering system entirely.
WITH mov AS (
    SELECT DISTINCT REGEXP_REPLACE(TRIM(cust_code), '^0+', '') AS code
    FROM loans_mom_ifrs_movement
    WHERE NULLIF(TRIM(cust_code), '') IS NOT NULL
)
SELECT 'cust_id -> cust_code' AS pairing,
       COUNT(*)               AS arrears_loans,
       COUNT(mov.code)        AS matched,
       COUNT(*) - COUNT(mov.code) AS unmatched
FROM loans lns
LEFT JOIN mov ON REGEXP_REPLACE(TRIM(lns.cust_id::text), '^0+', '') = mov.code
WHERE lns.days_in_arrears > 0;

-- D. Shape of each key: length and leading digit. Two different numbering
--    schemes show up here as disjoint length/prefix profiles.
SELECT 'loans.loan_account_no' AS src,
       LENGTH(REGEXP_REPLACE(TRIM(loan_account_no), '^0+', '')) AS len,
       LEFT(REGEXP_REPLACE(TRIM(loan_account_no), '^0+', ''), 1) AS lead,
       COUNT(*) AS n
FROM loans WHERE days_in_arrears > 0
GROUP BY 2, 3 ORDER BY n DESC LIMIT 15;

SELECT 'ifrs.lns_account' AS src,
       LENGTH(REGEXP_REPLACE(TRIM(lns_account), '^0+', '')) AS len,
       LEFT(REGEXP_REPLACE(TRIM(lns_account), '^0+', ''), 1) AS lead,
       COUNT(*) AS n
FROM loans_mom_ifrs_movement
GROUP BY 2, 3 ORDER BY n DESC LIMIT 15;

-- E. Raw overlap, ignoring the leading-zero strip entirely, in case the strip
--    is what breaks it.
SELECT COUNT(*) AS exact_untrimmed_matches
FROM loans lns
JOIN loans_mom_ifrs_movement m ON m.lns_account = lns.loan_account_no
WHERE lns.days_in_arrears > 0;
