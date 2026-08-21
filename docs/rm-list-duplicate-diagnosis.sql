-- Why the RM lists showed duplicate RMs and off numbers, and how to confirm it
-- on prod. Run on the datawarehouse: psql -U datawarehouse -d datawarehouse -f this
-- Everything here is read-only.

-- 1. Join fan-out: retail_allocated_portfolio has no unique key on cust_id.
--    Any excess over 0 in dup_customers means hf_customer JOIN rap multiplied
--    those customers' deposits/loans/revenue by their number of rap rows.
SELECT COUNT(*)                                   AS rap_rows,
       COUNT(DISTINCT cust_id)                    AS distinct_customers,
       COUNT(*) - COUNT(DISTINCT cust_id)         AS surplus_rows
FROM retail_allocated_portfolio;

SELECT COUNT(*) AS dup_customers FROM (
    SELECT cust_id FROM retail_allocated_portfolio
    GROUP BY cust_id HAVING COUNT(*) > 1
) d;

-- 2. Over-grouping: the branch RM list grouped by (sales_code, rm_name, branch).
--    Every row below was one extra duplicate line for that RM in the table.
SELECT sales_code,
       COUNT(DISTINCT branch)                     AS n_branches,
       COUNT(DISTINCT BTRIM(rm_name))             AS n_name_variants,
       string_agg(DISTINCT branch::text, ', ')    AS branches
FROM retail_allocated_portfolio
GROUP BY sales_code
HAVING COUNT(DISTINCT branch) > 1 OR COUNT(DISTINCT BTRIM(rm_name)) > 1
ORDER BY n_branches DESC, sales_code
LIMIT 50;

-- 3. The reported case (Tony Cherono / 3914) — one line per old table row.
SELECT sales_code, rm_name, branch, COUNT(*) AS customers
FROM retail_allocated_portfolio
WHERE sales_code::text = '3914'
GROUP BY sales_code, rm_name, branch
ORDER BY customers DESC;

-- 4. Before/after for one branch. Replace the branch name as needed.
--    old_rows is what the page used to show, new_rows is what it shows now.
WITH old_q AS (
    SELECT sales_code, rap.rm_name, rap.branch,
           SUM(total_depost_balance) AS dep
    FROM hf_customer
    LEFT JOIN retail_allocated_portfolio rap ON hf_customer.cust_id = rap.cust_id
    WHERE hf_customer.branch = 'RONGAI BRANCH'
    GROUP BY sales_code, rap.rm_name, rap.branch
), alloc AS (
    SELECT DISTINCT ON (cust_id)
           cust_id, NULLIF(BTRIM(sales_code::text), '') AS sales_code
    FROM retail_allocated_portfolio
    WHERE cust_id IS NOT NULL
    ORDER BY cust_id, updated_at DESC NULLS LAST, ctid DESC
), new_q AS (
    SELECT a.sales_code, SUM(c.total_depost_balance) AS dep
    FROM hf_customer c
    LEFT JOIN alloc a ON c.cust_id = a.cust_id
    WHERE c.branch = 'RONGAI BRANCH'
    GROUP BY a.sales_code
)
SELECT (SELECT COUNT(*) FROM old_q)      AS old_rows,
       (SELECT COUNT(*) FROM new_q)      AS new_rows,
       (SELECT SUM(dep) FROM old_q)      AS old_deposits,
       (SELECT SUM(dep) FROM new_q)      AS new_deposits;

-- 5. Ground truth for the branch: rap is not involved, so this is the number
--    new_deposits above must equal.
SELECT COUNT(*) AS customers, SUM(total_depost_balance) AS deposits
FROM hf_customer WHERE branch = 'RONGAI BRANCH';
