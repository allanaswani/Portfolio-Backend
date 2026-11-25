"""Internal accounts are left out of the CEO deposit and loan figures, in the
endpoints themselves (25 Nov 2026), and a row with no segment is not taken
for an internal one."""
from django.contrib.auth.models import User
from django.db import connection, connections
from django.test import TestCase
from rest_framework.test import APIClient

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
          "nov", "dec")


def _make(table, alias="default"):
    cols = ", ".join(f"{m}_{y}_bal numeric" for y in range(23, 29) for m in MONTHS)
    with connections[alias].cursor() as cur:
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            id bigserial PRIMARY KEY, cust_cif bigint, acc_num varchar(40),
            rm_code varchar(40), customer_segment varchar(60), {cols},
            yester_1_bal numeric, yester_2_bal numeric)""")
        cur.execute(f"DELETE FROM {table}")
        every = [f"{m}_{y}_bal" for y in range(23, 29) for m in MONTHS]
        for cif, rm, seg, bal in ((1, "RM1", "MASS", 100.0),
                                  (2, "Unmanaged", "INTERNAL ACCOUNTS", 50.0),
                                  (3, "RM1", None, 10.0)):
            cur.execute(
                f"INSERT INTO {table} (cust_cif, acc_num, rm_code, customer_segment, "
                f"{', '.join(every)}, yester_1_bal, yester_2_bal) VALUES "
                f"(%s, %s, %s, %s, {', '.join(['%s'] * len(every))}, %s, %s)",
                [cif, str(cif), rm, seg] + [bal] * len(every) + [bal, bal])


class InternalAccountsLeftOutTests(TestCase):
    #: The monthly views read through the warehouse alias (a routed model),
    #: which the dev settings point at PRODUCTION. Never there: the router is
    #: sent to the test database for the length of each test.

    def setUp(self):
        from unittest import mock

        from django.db import router

        patcher = mock.patch.object(router, "db_for_read", return_value="default")
        patcher.start()
        self.addCleanup(patcher.stop)
        for table in ("daily_balance_movement", "loan_daily_balance_movement"):
            _make(table)
        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS retail_allocated_portfolio (
                cust_id bigint, rm_name varchar(100), updated_at timestamptz)""")
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_superuser("a", "a@a", "x"))

    def test_the_monthly_movement_has_no_internal_accounts(self):
        for url in ("/ceo/monthly_movement/", "/ceo/loan_monthly_movement/"):
            with self.subTest(url):
                got = self.client.get(url)
                self.assertEqual(got.status_code, 200)
                segments = {r["customer_segment"] for r in got.json()}
                self.assertNotIn("INTERNAL ACCOUNTS", segments)
                # A row with no segment is kept, not dropped with them.
                self.assertEqual(segments, {"MASS", "New-Unsegmented"})

    def test_rm_ytd_movement_has_no_internal_accounts(self):
        got = self.client.get("/ceo/rm_ytd_movement/")
        self.assertEqual(got.status_code, 200)
        rows = got.json()
        rows = rows if isinstance(rows, list) else rows.get("results", rows)
        codes = {r["rm_code"] for r in rows}
        self.assertNotIn("Unmanaged", codes)          # the internal account's
        rm1 = next(r for r in rows if r["rm_code"] == "RM1")
        self.assertAlmostEqual(float(rm1["yester_1_bal"]), 110.0)
