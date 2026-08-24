-- Why the TL Portfolio dashboard shows real Deposits/Loans/RMs but ZERO for
-- Total Customers, Active, New YTD, Allocated, Unallocated, Product/Customer,
-- Revenue and NFI (reported 2026-08-24 for BUSINESS BANKING). Read-only.
--
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DW_PASSWORD" psql -h "${DW_HOST:-127.0.0.1}" -p "${DW_PORT:-5432}" \
--     -U "$DW_USER" -d "$DW_NAME" -f docs/tl-segment-zeros.sql
--
-- The split is exact and it is not a coincidence:
--   WORKING tiles read daily_balance_movement / loan_daily_balance_movement and
--     derive the banking segment with a CASE over customer_segment.
--   ZERO tiles read hf_customer and filter on the STORED column
--     hf_customer.banking_segment = <profile.segment>.
-- So profile.segment is right (it matched the CASE, and it matched 54 RM
-- profiles) and the stored column is what does not match. These queries say why.

\pset footer off

-- 1. The vocabulary actually stored in hf_customer.banking_segment.
--    If this comes back empty / all NULL, the ETL never populates the column and
--    EVERY segment's TL dashboard is zeroed, not just Business Banking.
SELECT COALESCE(banking_segment, '<NULL>') AS banking_segment,
       COUNT(*) AS customers
FROM hf_customer
GROUP BY 1 ORDER BY customers DESC LIMIT 30;

SELECT COUNT(*) AS total_rows,
       COUNT(banking_segment) AS non_null,
       COUNT(*) FILTER (WHERE NULLIF(TRIM(banking_segment), '') IS NULL) AS null_or_blank
FROM hf_customer;

-- 2. The raw core-banking segment on the same table. hf_customer.segment holds
--    'MEDIUM ENTERPRISES' / 'SMALL ENTERPRISES' etc., which the app's CASE maps
--    to 'BUSINESS BANKING'. If this column is populated while banking_segment is
--    not, the backend can derive the label instead of waiting for the ETL.
SELECT COALESCE(segment, '<NULL>') AS segment, COUNT(*) AS customers
FROM hf_customer
GROUP BY 1 ORDER BY customers DESC LIMIT 30;

-- 3. Cross-tab: for the raw segments that make up Business Banking, what does
--    the stored banking_segment say?
SELECT COALESCE(segment, '<NULL>')          AS raw_segment,
       COALESCE(banking_segment, '<NULL>')  AS stored_banking_segment,
       COUNT(*)                             AS customers
FROM hf_customer
WHERE segment IN ('MEDIUM ENTERPRISES', 'SMALL ENTERPRISES')
GROUP BY 1, 2 ORDER BY customers DESC;

-- 4. Is it merely case/whitespace? exact_match is what the app does today.
--    If loose_match is large while exact_match is 0, the fix is to compare
--    case-insensitively. If BOTH are 0, the column simply does not carry the
--    label and case-folding would change nothing.
SELECT COUNT(*) FILTER (WHERE banking_segment = 'BUSINESS BANKING')            AS exact_match,
       COUNT(*) FILTER (WHERE UPPER(TRIM(banking_segment)) = 'BUSINESS BANKING') AS loose_match,
       COUNT(*) FILTER (WHERE segment IN ('MEDIUM ENTERPRISES','SMALL ENTERPRISES')) AS raw_segment_match
FROM hf_customer;

-- 5. Proof the working side works: the CASE output over the movement table.
--    'BUSINESS BANKING' appearing here with a real count is why the deposit and
--    loan tiles render 4.13B / 8.67B while the customer tiles render 0.
SELECT case when customer_segment in ('MEDIUM ENTERPRISES', 'SMALL ENTERPRISES') then 'BUSINESS BANKING'
            when customer_segment in ('LARGE ENTERPRISES') then 'COMMERCIAL'
            when customer_segment in ('MASS', 'STANDARD') then 'PB'
            when customer_segment in ('PRIVATE', 'ULTIMATE') then 'ULTIMATE'
            when customer_segment in ('DIASPORA', 'NON RESIDENT KENYANS') then 'DIASPORA'
            else 'other' end AS mapped_banking_segment,
       COUNT(*) AS accounts
FROM daily_balance_movement
GROUP BY 1 ORDER BY accounts DESC;

-- 6. What the TL profiles are set to (app DB; DW_* and DB_* point at the same
--    physical Postgres in prod). Confirms the value being passed in.
SELECT COALESCE(segment, '<NULL>') AS profile_segment, COUNT(*) AS users
FROM portfolio_profile
GROUP BY 1 ORDER BY users DESC;

-- 7. Revenue / NFI use the same filter through a join, so they zero for the
--    same reason. This shows whether revenue itself has current-year rows at all
--    (an empty result here would be a SECOND, independent problem).
SELECT COUNT(*) AS revenue_rows_this_year,
       COUNT(DISTINCT r.cust_id) AS customers,
       COUNT(DISTINCT r.income_category) AS categories
FROM revenue r
WHERE date_trunc('year', tmstamp) = date_trunc('year', now());
