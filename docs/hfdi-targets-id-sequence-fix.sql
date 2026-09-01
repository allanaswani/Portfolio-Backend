-- ===========================================================================
-- Fix: POST /hfdi/hfdi-targets/ -> 500
--
--   django.db.utils.IntegrityError: null value in column "id" violates
--   not-null constraint
--   DETAIL: Failing row contains (null, 34, Grace Kanja, ...)
--
-- hfdi_performance_target_feedback.id is a NOT NULL primary key with no
-- sequence default and no identity. Django's BigAutoField leaves id out of
-- the INSERT on purpose and lets the database generate it, so Postgres
-- substitutes NULL and the constraint fires. Reads never touch the default,
-- which is why the list endpoint works and only writes fail.
--
-- Section 1 reports, section 2 sweeps for the same fault elsewhere, section 3
-- repairs. Run 1 and 2 first, read them, then run 3.
--
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DB_PASSWORD" psql -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" \
--        -U "$DB_USER" -d "$DB_NAME" -f docs/hfdi-targets-id-sequence-fix.sql
--
-- Section 3 is reversible: ALTER TABLE ... ALTER COLUMN id DROP DEFAULT.
-- ===========================================================================

\echo '=== 1. Current state of the two id columns ==='
SELECT c.relname                                   AS table_name,
       a.attname                                   AS column_name,
       format_type(a.atttypid, a.atttypmod)        AS type,
       CASE a.attidentity WHEN '' THEN 'no' ELSE 'yes' END AS is_identity,
       pg_get_expr(d.adbin, d.adrelid)             AS column_default
FROM   pg_class c
JOIN   pg_namespace n  ON n.oid = c.relnamespace
JOIN   pg_attribute a  ON a.attrelid = c.oid
LEFT   JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
WHERE  n.nspname = 'public'
  AND  ((c.relname = 'hfdi_performance_target_feedback' AND a.attname = 'id')
    OR  (c.relname = 'hfdi_historicalhfditargets'       AND a.attname = 'history_id'))
ORDER  BY c.relname;
-- A column_default of nextval(...) or is_identity = yes is healthy.
-- Empty on both counts is the bug.

\echo ''
\echo '=== 2. Every other table with the same fault ==='
-- A single-column integer primary key that neither is an identity column nor
-- carries a default cannot be inserted into by Django at all. Anything listed
-- here is an endpoint that will 500 on create the first time someone tries.
SELECT c.relname                            AS table_name,
       a.attname                            AS pk_column,
       format_type(a.atttypid, a.atttypmod) AS type,
       (SELECT n_live_tup FROM pg_stat_user_tables s WHERE s.relid = c.oid) AS approx_rows
FROM   pg_index i
JOIN   pg_class c     ON c.oid = i.indrelid
JOIN   pg_namespace n ON n.oid = c.relnamespace
JOIN   pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
WHERE  i.indisprimary
  AND  i.indnatts = 1
  AND  n.nspname = 'public'
  AND  c.relkind = 'r'
  AND  a.atttypid IN ('int2'::regtype, 'int4'::regtype, 'int8'::regtype)
  AND  a.attidentity = ''
  AND  NOT EXISTS (SELECT 1 FROM pg_attrdef d
                   WHERE d.adrelid = c.oid AND d.adnum = a.attnum)
ORDER  BY c.relname;

\echo ''
\echo '=== 3. Repair ==='
BEGIN;

-- hfdi_performance_target_feedback.id
CREATE SEQUENCE IF NOT EXISTS hfdi_performance_target_feedback_id_seq
    OWNED BY hfdi_performance_target_feedback.id;
SELECT setval('hfdi_performance_target_feedback_id_seq',
              COALESCE((SELECT max(id) FROM hfdi_performance_target_feedback), 0) + 1,
              false);
ALTER TABLE hfdi_performance_target_feedback
    ALTER COLUMN id SET DEFAULT nextval('hfdi_performance_target_feedback_id_seq');

-- hfdi_historicalhfditargets.history_id — simple_history writes a row here on
-- every create, so a create cannot succeed while this one is also broken. The
-- main INSERT failed first, so this was never reached and never reported.
CREATE SEQUENCE IF NOT EXISTS hfdi_historicalhfditargets_history_id_seq
    OWNED BY hfdi_historicalhfditargets.history_id;
SELECT setval('hfdi_historicalhfditargets_history_id_seq',
              COALESCE((SELECT max(history_id) FROM hfdi_historicalhfditargets), 0) + 1,
              false);
ALTER TABLE hfdi_historicalhfditargets
    ALTER COLUMN history_id SET DEFAULT nextval('hfdi_historicalhfditargets_history_id_seq');

COMMIT;

\echo ''
\echo '=== 4. Confirm both now generate ==='
SELECT c.relname AS table_name, a.attname AS column_name,
       pg_get_expr(d.adbin, d.adrelid) AS column_default
FROM   pg_class c
JOIN   pg_namespace n  ON n.oid = c.relnamespace
JOIN   pg_attribute a  ON a.attrelid = c.oid
LEFT   JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
WHERE  n.nspname = 'public'
  AND  ((c.relname = 'hfdi_performance_target_feedback' AND a.attname = 'id')
    OR  (c.relname = 'hfdi_historicalhfditargets'       AND a.attname = 'history_id'))
ORDER  BY c.relname;
