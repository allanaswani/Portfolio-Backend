-- ===========================================================================
-- Why does POST /hfdi/hfdi-targets/ return 500 while GET works?
--
-- The Django model (apps/hfdi/models.py: HfdiTargets) writes exactly these
-- columns to hfdi_performance_target_feedback:
--
--   id, project_id, pm, rm, sales_manager, team_leader, is_active, month,
--   target_start_date, target_sales_end_date, target_collections_end_date,
--   volume, value, income, collections_value, historical_value,
--   current_sales_value, recording_date
--
-- A SELECT names only those columns, so a stale/legacy table still reads fine.
-- An INSERT is where a mismatch shows up: any OTHER column that is NOT NULL
-- with no default, a missing id sequence, or a missing history table will
-- raise and Django returns 500.
--
-- Run with:
--   set -a; . /etc/hf/prod.env; set +a
--   PGPASSWORD="$DB_PASSWORD" psql -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" \
--        -U "$DB_USER" -d "$DB_NAME" -f docs/hfdi-targets-500-check.sql
-- ===========================================================================

\echo '=== 1. Do the two tables the write path touches exist? ==='
SELECT tablename
FROM   pg_tables
WHERE  tablename IN ('hfdi_performance_target_feedback',
                     'hfdi_historicalhfditargets')
ORDER  BY tablename;
-- Both must be listed. simple_history writes a row to the historical table on
-- every create, so if only the first is present every POST dies there.

\echo ''
\echo '=== 2. Columns Django does NOT write that would reject an INSERT ==='
SELECT column_name, data_type, is_nullable, column_default
FROM   information_schema.columns
WHERE  table_name = 'hfdi_performance_target_feedback'
  AND  is_nullable = 'NO'
  AND  column_default IS NULL
  AND  column_name NOT IN ('id','project_id','pm','rm','sales_manager',
                           'team_leader','is_active','month',
                           'target_start_date','target_sales_end_date',
                           'target_collections_end_date','volume','value',
                           'income','collections_value','historical_value',
                           'current_sales_value','recording_date')
ORDER  BY column_name;
-- Any row here is a NOT NULL column with no default that Django never fills:
-- the INSERT fails with "null value in column ... violates not-null constraint".

\echo ''
\echo '=== 3. Model columns that are missing from the table ==='
SELECT c.name AS missing_column
FROM   (VALUES ('id'),('project_id'),('pm'),('rm'),('sales_manager'),
               ('team_leader'),('is_active'),('month'),('target_start_date'),
               ('target_sales_end_date'),('target_collections_end_date'),
               ('volume'),('value'),('income'),('collections_value'),
               ('historical_value'),('current_sales_value'),('recording_date')) AS c(name)
WHERE  NOT EXISTS (
         SELECT 1 FROM information_schema.columns
         WHERE table_name = 'hfdi_performance_target_feedback'
           AND column_name = c.name);
-- Anything listed means the migration never reached this database.

\echo ''
\echo '=== 4. Does id auto-generate? ==='
SELECT column_name, data_type, is_identity, column_default
FROM   information_schema.columns
WHERE  table_name = 'hfdi_performance_target_feedback'
  AND  column_name = 'id';
-- Needs either is_identity = YES or a nextval(...) default. If both are empty
-- the table was created by hand / by an ETL and every INSERT fails on id.

\echo ''
\echo '=== 5. Same three checks for the history table ==='
SELECT column_name, data_type, is_nullable, column_default
FROM   information_schema.columns
WHERE  table_name = 'hfdi_historicalhfditargets'
  AND ((is_nullable = 'NO' AND column_default IS NULL)
       OR column_name IN ('history_id','history_date','history_type','history_user_id'))
ORDER  BY column_name;

\echo ''
\echo '=== 6. Has the hfdi app been migrated here at all? ==='
SELECT name, applied
FROM   django_migrations
WHERE  app = 'hfdi'
ORDER  BY id;
-- Compare against apps/hfdi/migrations/: 0001 .. 0007 must all be listed.
