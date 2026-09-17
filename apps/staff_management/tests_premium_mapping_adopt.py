"""The adopt path in migration 0019 — the one that runs on production.

Two earlier versions of this migration failed on the host, and both failures
were the same mistake: assuming the shape of a table this repo did not build.

    1. a plain CreateModel   -> relation "premium_types_mapping" already exists
    2. adopt, but expecting Django's implicit ``id`` -> its own guard stopped
       the deploy and printed the real columns

Production's table is five text columns and no surrogate key::

    product | vic_check | life_policy_check | premium_type | policy_category

That branch cannot be exercised by building the test database — migrations run
once there, against nothing — so the migration's own functions are driven
directly here against tables shaped the way production might be.
"""
from importlib import import_module

from django.db import connection
from django.test import TransactionTestCase

# Migration module names start with a digit, so they cannot be imported with
# `from ... import`. Named in full rather than discovered, so renaming the
# migration breaks this loudly instead of silently testing nothing.
_m = import_module(
    "apps.staff_management.migrations"
    ".0019_premiumtypemapping_historicalpremiumtypemapping"
)
COLUMNS, TABLE, CREATE = _m.COLUMNS, _m.TABLE, _m.CREATE
adopt, _columns = _m.adopt, _m._columns


class _Editor:
    """The one attribute the migration functions use."""
    class _Conn:
        def cursor(self):
            return connection.cursor()
    connection = _Conn()


def _drop():
    with connection.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")


def _cols():
    with connection.cursor() as cur:
        return _columns(cur)


def _index_exists():
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('uniq_premium_types_mapping_product')")
        return cur.fetchone()[0] is not None


class AdoptTests(TransactionTestCase):
    """TransactionTestCase: these create and drop real tables."""

    def tearDown(self):
        # Put the table back the way the rest of the suite expects it.
        _drop()
        with connection.cursor() as cur:
            cur.execute(CREATE)

    # ── the shape production actually has ──────────────────────────────────

    def test_the_production_shape_is_left_completely_alone(self):
        """Five text columns, no id. Nothing altered, nothing dropped."""
        _drop()
        with connection.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE {TABLE} (
                    product varchar(255),
                    vic_check varchar(100),
                    life_policy_check varchar(100),
                    premium_type varchar(100),
                    policy_category varchar(100)
                )""")
            cur.execute(f"INSERT INTO {TABLE} (product, premium_type) "
                        f"VALUES ('EXISTING PRODUCT', 'motor')")
        before = _cols()
        adopt(None, _Editor())
        self.assertEqual(_cols(), before)
        with connection.cursor() as cur:
            cur.execute(f"SELECT product, premium_type FROM {TABLE}")
            self.assertEqual(cur.fetchall(), [("EXISTING PRODUCT", "motor")])

    def test_it_creates_the_table_when_it_is_genuinely_absent(self):
        _drop()
        self.assertIsNone(_cols())
        adopt(None, _Editor())
        self.assertEqual(_cols(), set(COLUMNS))

    def test_missing_columns_are_added_and_existing_rows_survive(self):
        """A table that predates the classification columns."""
        _drop()
        with connection.cursor() as cur:
            cur.execute(f"CREATE TABLE {TABLE} (product varchar(255))")
            cur.execute(f"INSERT INTO {TABLE} (product) VALUES ('ipp')")
        adopt(None, _Editor())
        self.assertTrue(set(COLUMNS).issubset(_cols()))
        with connection.cursor() as cur:
            cur.execute(f"SELECT product, premium_type FROM {TABLE}")
            # The row is still there; the new column defaulted rather than
            # failing the ALTER on a populated table.
            self.assertEqual(cur.fetchall(), [("ipp", "")])

    def test_extra_columns_this_repo_does_not_know_about_are_kept(self):
        """Including an id, if whoever owns the table ever adds one."""
        _drop()
        with connection.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE {TABLE} (
                    id bigserial PRIMARY KEY,
                    product varchar(255),
                    some_upstream_column text
                )""")
        adopt(None, _Editor())
        self.assertIn("id", _cols())
        self.assertIn("some_upstream_column", _cols())

    def test_a_table_with_no_product_stops_rather_than_half_working(self):
        """`product` is the model's primary key. Without it there is nothing to
        adopt, and inventing a key column on somebody else's table is not this
        migration's call. Fail with the real column list: a stopped migrate is
        recoverable, a screen that 500s on a missing column is a support
        ticket."""
        _drop()
        with connection.cursor() as cur:
            cur.execute(f"CREATE TABLE {TABLE} (premium_type varchar(100))")
        with self.assertRaises(RuntimeError) as caught:
            adopt(None, _Editor())
        message = str(caught.exception)
        self.assertIn('no "product" column', message)
        self.assertIn("premium_type", message)   # the real columns, for diagnosis

    def test_running_it_twice_changes_nothing(self):
        _drop()
        adopt(None, _Editor())
        first = _cols()
        adopt(None, _Editor())
        self.assertEqual(_cols(), first)

    # ── the unique index ───────────────────────────────────────────────────

    def test_the_index_is_created_on_clean_data(self):
        _drop()
        with connection.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE {TABLE} (
                    product varchar(255),
                    vic_check varchar(100),
                    life_policy_check varchar(100),
                    premium_type varchar(100),
                    policy_category varchar(100)
                )""")
            cur.execute(f"INSERT INTO {TABLE} (product) VALUES ('ipp'), ('IDD')")
        adopt(None, _Editor())
        self.assertTrue(_index_exists())

    def test_existing_case_duplicates_do_not_fail_the_deploy(self):
        """The table already holds rows this repo has never seen. If two differ
        only in case the index cannot be built — a data question for
        Bancassurance, not a reason to stop a release. The API refuses new
        duplicates either way."""
        _drop()
        with connection.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE {TABLE} (
                    product varchar(255),
                    vic_check varchar(100),
                    life_policy_check varchar(100),
                    premium_type varchar(100),
                    policy_category varchar(100)
                )""")
            cur.execute(f"INSERT INTO {TABLE} (product) VALUES ('ipp'), ('IPP')")
        adopt(None, _Editor())          # must not raise
        self.assertFalse(_index_exists())
