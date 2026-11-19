"""Finance's Branch Accounts workbook → the branch manager's Operating Profit.

19 Nov 2026: the desk's September figure for all 22 branches is Branch_PBT_Movement's
monthly PBT (in thousands) summed from January, plus the Bancassurance sheet's
commission (in shillings) - River Road 188,045,701.29 exactly.
"""
import datetime
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from . import bb_live_feeds as bb
from . import branch_accounts as ba

URL = "/staff_management/scorecard-automation/branch-accounts/"


def workbook(months=("Jan 2026 MTD", "Feb 2026 MTD", "March 2026 MTD")):
    import openpyxl

    wb = openpyxl.Workbook()
    pbt = wb.active
    pbt.title = "Branch_PBT_Movement"
    pbt.append([None, None, None, None, "PBT after Provisions (ex-HQ cost, Income & Bancassurance) "])
    pbt.append([None, "Rank", "Branch Code", "Branch", *months, "PBT Movement MoM", "Comment"])
    # River Road's real January and February (KES '000), and a March.
    pbt.append([None, 1, 20, "River Road ", 6619.654771976569, 10561.292968019494, 100.0, 5, "x"])
    pbt.append([None, 2, 200, "Rehani ", 32058.0, 26678.0, None, 0, "x"])
    pbt.append([None, None, None, "Total", 38677.0, 37239.0, 100.0, 0, None])
    banca = wb.create_sheet("Bancassurance ")
    banca.append([None, "Bancassurance Commission", datetime.datetime(2026, 1, 1),
                  datetime.datetime(2026, 2, 1), datetime.datetime(2026, 3, 1), "Totals"])
    banca.append([20, "RIVERROAD", 0, 0, 2850, 2850])
    banca.append([200, "REHANI", 138932, 159827, 0, 298759])
    prov = wb.create_sheet("Provisions")
    prov.append(["CC", "CC1"])
    prov.append([None, None, "YTD P&L Charge", "YTD Int. Adj", "YTD Loan Loss",
                 "March 2026 Loan Loss", "February 2026 Loan Loss", "January 2026 Loan Loss"])
    prov.append([20, "RIVERROAD", 0, 0, 600.0, 100.0, 200.0, 300.0])
    prov.append([None, "Total", 0, 0, 600.0, 100.0, 200.0, 300.0])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


class ReadTests(TestCase):
    def test_year_to_date_is_pbt_in_thousands_plus_the_commission(self):
        found = ba.read(BytesIO(workbook()))
        self.assertEqual((found["year"], found["latest_month"]), (2026, 3))
        river = found["ytd"][20]
        self.assertEqual(river[0], 6619654.77)           # the desk's January
        self.assertEqual(river[1], 17180947.74)          # the desk's February
        self.assertEqual(river[2], 17180947.74 + 100000 + 2850)
        self.assertEqual(river[3:], [None] * 9)          # nothing past Finance's month
        rehani = found["ytd"][200]
        self.assertEqual(rehani[1], (32058 + 26678) * 1000 + 138932 + 159827)
        self.assertNotIn(None, found["ytd"])             # the Total row is not a branch

    def test_the_loan_loss_runs_from_january_in_the_templates_sign(self):
        found = ba.read(BytesIO(workbook()))
        self.assertEqual(found["loss_ytd"][20][:3], [300.0, 500.0, 600.0])
        ba.save(found, "Branch Accounts.xlsx", "root")
        feed = {"kind": "finance_loss", "sheet": "PL_Charge"}
        totals = bb._totals(feed, 2026, 2, 60_000)
        # The template holds the loss positive; the card's formula shows it
        # negative (River Road: -20,485,640.48 on the card).
        self.assertEqual(bb._branch_total(totals, "RiverRoad", feed), 500.0)
        self.assertEqual(bb.DEFINITIONS["PL_Charge"][0][1], "finance_loss")

    def test_a_workbook_without_the_sheet_is_refused(self):
        import openpyxl

        wb, out = openpyxl.Workbook(), BytesIO()
        wb.save(out)
        with self.assertRaisesRegex(ValueError, "branch_pbt_movement"):
            ba.read(BytesIO(out.getvalue()))

    def test_the_proof_reads_its_month_and_a_card_the_latest_closed(self):
        ba.save(ba.read(BytesIO(workbook())), "Branch Accounts.xlsx", "root")
        self.assertEqual(ba.figures(2026, 2)[1][20], 17180947.74)
        self.assertEqual(ba.figures(2026, 11), (None, {}))          # the proof: not closed
        month, found = ba.figures(2026, 11, exact=False)            # a November card
        self.assertEqual(month, 3)
        self.assertEqual(found[20], 17180947.74 + 102850)

    def test_the_branch_feed_puts_it_on_the_branch(self):
        ba.save(ba.read(BytesIO(workbook())), "Branch Accounts.xlsx", "root")
        feed = {"kind": "finance_pbt", "sheet": "Revenue_Contribution"}
        totals = bb._totals(feed, 2026, 2, 60_000)
        self.assertEqual(bb._branch_total(totals, "RiverRoad", feed), 17180947.74)
        self.assertEqual(bb.DEFINITIONS["Revenue_Contribution"][0][1], "finance_pbt")
        self.assertNotIn("no warehouse source", bb.why_not_live("Revenue_Contribution", 0))


class ScreenTests(TestCase):
    def client_for(self, *groups, superuser=False):
        user = (User.objects.create_superuser("root.admin", password="x") if superuser
                else User.objects.create_user("_".join(groups) or "plain", password="x"))
        for name in groups:
            user.groups.add(Group.objects.get_or_create(name=name)[0])
        client = APIClient()
        client.force_authenticate(user)
        return client

    def upload(self):
        return {"file": SimpleUploadedFile(
            "Branch Accounts October 2026 - share.xlsx", workbook(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    def test_administration_loads_it(self):
        client = self.client_for(superuser=True)
        r = client.post(URL, self.upload(), format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["year"], r.data["latest_month"], r.data["branches"]),
                         (2026, 3, 2))
        listed = client.get(URL).data["years"][0]
        self.assertEqual((listed["year"], listed["latest_month"]), (2026, 3))

    def test_others_cannot_load_it(self):
        self.assertEqual(self.client_for("portfolio_mgt").post(
            URL, self.upload(), format="multipart").status_code, 403)
        viewer = self.client_for("admin_viewer")
        self.assertEqual(viewer.get(URL).status_code, 200)
        self.assertEqual(viewer.post(URL, self.upload(), format="multipart").status_code, 403)
        self.assertIsNone(ba.stored(2026))


class OtherBancaTests(TestCase):
    """The branch card's "Other Bancassurance Premiums" reads the template's
    Banca_Assurance_Income table #4 = #5 (all premiums) - #3 (VIC): River Road
    September 8,672,212 - 6,001,110 = 2,671,102 (19 Nov 2026)."""

    def test_the_residual_is_everything_but_the_two_vic_tables(self):
        from unittest import mock

        policies = [("RIVER ROAD", "S1", "vic_life", 100.0),
                    ("RIVER ROAD", "S1", "vic_non_life", 40.0),
                    ("RIVER ROAD", "S1", "non_vic", 25.0),
                    ("RIVER ROAD", "S2", None, 10.0)]     # a product with no mapping row
        with mock.patch.object(bb, "_banca_policies", return_value=policies), \
                mock.patch.dict(bb.BANCA_BRANCH, {"RIVER ROAD": "RIVERROAD"}):
            self.assertEqual(bb._banca(2026, 9, "residual", 60_000), {"riverroad": 35.0})
            self.assertEqual(bb._banca(2026, 9, "non_vic", 60_000), {"riverroad": 25.0})
        self.assertEqual(bb.DEFINITIONS["Banca_Assurance_Income#4"][0][2]["part"], "residual")

    def test_a_line_on_an_unproven_table_names_what_was_tried(self):
        self.assertEqual(set(bb.defined_blocks()["bancaassuranceincome"]), {1, 2, 4})
        self.assertNotIn("no warehouse source",
                         bb.why_not_live("Banca_Assurance_Income", 4))
