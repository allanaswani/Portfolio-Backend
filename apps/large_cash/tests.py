import datetime
import decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from . import lake
from .models import LargeCashDay, LargeCashTransaction

D = decimal.Decimal
NOV20 = datetime.date(2026, 11, 20)


def row(code, kes, sn, day=NOV20, branch="REHANI BRANCH", cust="101",
        reversed_=False, currency="KENYAN SHILLING", amount=None):
    return {"trx_date": day, "unit": 200, "teller": "T1", "user_sn": sn,
            "internal_sn": 1, "posted_at": None, "branch": branch,
            "teller_name": "", "account_number": "9" + cust, "customer_id": cust,
            "account_name": "A CUSTOMER", "justific_id": code,
            "transaction_type": lake.CASH_CODES[code],
            "direction": "deposit" if code in lake.DEPOSITS else "withdrawal",
            "currency": currency, "amount": D(amount if amount is not None else kes),
            "amount_kes": D(kes), "channel": "", "comments": "",
            "reversed": reversed_}


class LoadTests(TestCase):

    def test_every_day_read_is_recorded_and_reversals_leave_the_totals(self):
        rows = [row(31001, 600_000, 1), row(32001, 2_000_000, 2),
                row(31615, 700_000, 3, reversed_=True)]
        self.assertEqual(lake.save(rows, NOV20 - datetime.timedelta(days=1), NOV20), 3)
        day = LargeCashDay.objects.get(day=NOV20)
        self.assertEqual((day.transactions, day.total_kes), (2, D("2600000")))
        # The day before was read and had none: a row saying so, not a gap.
        self.assertEqual(LargeCashDay.objects.get(day=NOV20 - datetime.timedelta(days=1))
                         .transactions, 0)
        # Reading the day again replaces it.
        lake.save([row(31001, 900_000, 9)], NOV20, NOV20)
        self.assertEqual(LargeCashTransaction.objects.filter(trx_date=NOV20).count(), 1)

    def test_which_days_a_run_reads(self):
        # First run: a month back from the lake's newest day.
        self.assertEqual(lake.days_to_read(NOV20),
                         (NOV20 - datetime.timedelta(days=30), NOV20))
        # Then from the last day read, less the days read again.
        lake.save([], datetime.date(2026, 11, 18), datetime.date(2026, 11, 18))
        self.assertEqual(lake.days_to_read(NOV20),
                         (datetime.date(2026, 11, 16), NOV20))
        self.assertIsNone(lake.days_to_read(None))

    def test_the_query_holds_the_rules(self):
        sql = lake.SQL.format(start="2026-11-20", end="2026-11-20")
        for code in (31001, 31004, 31002, 32001, 31615, 31617):
            self.assertIn(str(code), sql)
        self.assertNotIn("31809", sql)                       # petty cash journal
        self.assertIn(">= 500000", sql)
        self.assertIn("o_fixing_rate", sql)                  # foreign cash in KES
        self.assertIn("GROUP BY 1, 2, 3, 4, 5", sql)         # one row per transaction


class ViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        lake.save([row(31001, 600_000, 1), row(32001, 2_000_000, 2, branch="THIKA BRANCH",
                                              cust="202"),
                   row(31001, 2_600_000, 3, currency="UNITED STATES DOLLAR", amount=20_000),
                   row(31615, 700_000, 4, reversed_=True)], NOV20, NOV20)
        patcher = mock.patch.object(lake, "refresh_in_background", return_value="recent")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_administrators_and_the_viewer_group(self):
        user = User.objects.create_user("rm", password="x")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get("/large_cash/summary/").status_code, 403)
        user.groups.add(Group.objects.get_or_create(name="large_cash_viewer")[0])
        self.assertEqual(self.client.get("/large_cash/summary/").status_code, 200)

    def test_the_summary_of_the_newest_day(self):
        self.client.force_authenticate(User.objects.create_superuser("a", "a@a", "x"))
        got = self.client.get("/large_cash/summary/").json()
        self.assertEqual(got["start"], "2026-11-20")
        self.assertTrue(got["read"])
        self.assertEqual(got["all"], {"transactions": 3, "total_kes": 5_200_000.0})
        self.assertEqual(got["deposits"]["transactions"], 2)
        self.assertEqual(got["withdrawals"]["total_kes"], 2_000_000.0)
        self.assertEqual(got["reversed"]["transactions"], 1)
        self.assertEqual(got["foreign_currency"]["transactions"], 1)
        self.assertEqual(got["by_branch"][0]["branch"], "REHANI BRANCH")
        self.assertEqual(got["customers"], 2)

    def test_the_list_filters_and_downloads_whole(self):
        self.client.force_authenticate(User.objects.create_superuser("a", "a@a", "x"))
        page = self.client.get("/large_cash/transactions/",
                               {"date": "2026-11-20", "branch": "thika"}).json()
        self.assertEqual(page["count"], 1)
        got = self.client.get("/large_cash/transactions/",
                              {"date": "2026-11-20", "download": "csv"})
        self.assertEqual(got.status_code, 200)
        text = b"".join(got.streaming_content).decode("utf-8-sig")
        self.assertEqual(len(text.strip().splitlines()), 1 + 4)   # header + rows
        self.assertIn("Amount Kes", text.splitlines()[0])
        got = self.client.get("/large_cash/transactions/",
                              {"date": "2026-11-20", "download": "xlsx"})
        import io

        from openpyxl import load_workbook

        sheet = load_workbook(io.BytesIO(b"".join(got.streaming_content))).active
        self.assertEqual(sheet.max_row, 1 + 4)
        self.assertEqual(sheet.cell(1, 1).value, "Id")
