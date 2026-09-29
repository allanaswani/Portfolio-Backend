"""Written against what an RM and a Team Leader would notice."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient, APITestCase

from apps.portfolio.models import Profile
from .models import PipelineEntry as P

BASE = "/commercial_pipeline/"


def user(username, sales_code="", segment="COMMERCIAL", group=None):
    u = get_user_model().objects.create_user(username=username, password="x")
    Profile.objects.update_or_create(
        user=u, defaults={"sales_code": sales_code, "segment": segment,
                          "branch": "Commercial"})
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


class PipelineTests(APITestCase):
    def setUp(self):
        self.rm = user("rm_one", sales_code="CM001")
        self.other_rm = user("rm_two", sales_code="CM002")
        self.tl = user("tl_one", sales_code="CM900", group="tl_portfolio")

        self.mine = P.objects.create(
            kind=P.KIND_ASSET, customer_name="Technomasters Limited",
            sales_code="CM001", rm_name="RM One", segment="COMMERCIAL",
            amount=Decimal("10000000"), amount_to_disburse=Decimal("6000000"),
            product="Contract Finance", broad_stage=P.BROAD_APPROVED)
        self.theirs = P.objects.create(
            kind=P.KIND_ASSET, customer_name="Estina Green Limited",
            sales_code="CM002", rm_name="RM Two", segment="COMMERCIAL",
            amount=Decimal("7500000"))

    def as_(self, who):
        c = APIClient()
        c.force_authenticate(who)
        return c

    # ── who sees what ────────────────────────────────────────────────
    def test_an_rm_sees_only_their_own_lines(self):
        res = self.as_(self.rm).get(f"{BASE}entries/")
        names = [r["customer_name"] for r in res.data["results"]]
        self.assertEqual(names, ["Technomasters Limited"])

    def test_a_team_leader_sees_the_whole_segment(self):
        res = self.as_(self.tl).get(f"{BASE}entries/")
        names = sorted(r["customer_name"] for r in res.data["results"])
        self.assertEqual(names, ["Estina Green Limited", "Technomasters Limited"])

    def test_an_rm_cannot_open_another_rms_line(self):
        res = self.as_(self.rm).get(f"{BASE}entries/{self.theirs.id}/")
        self.assertEqual(res.status_code, 404)

    def test_a_segment_is_matched_through_its_synonyms_not_by_equality(self):
        """COMMERCIAL and LARGE ENTERPRISES are the same segment here."""
        tl = user("tl_large", sales_code="CM901", segment="LARGE ENTERPRISES",
                  group="tl_portfolio")
        res = self.as_(tl).get(f"{BASE}entries/")
        self.assertEqual(res.data["count"], 2)

    # ── the rules the spreadsheet could not enforce ──────────────────
    def test_a_stage_must_belong_to_its_broad_stage(self):
        res = self.as_(self.rm).post(f"{BASE}entries/", {
            "kind": "asset", "customer_name": "Skillman Construction",
            "amount": "30000000", "product": "Contract finance",
            "broad_stage": P.BROAD_DISBURSED, "stage": "at_credit_risk",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("stage", res.data)

    def test_a_matching_stage_pair_is_accepted(self):
        res = self.as_(self.rm).post(f"{BASE}entries/", {
            "kind": "asset", "customer_name": "Skillman Construction",
            "amount": "30000000", "product": "Contract finance",
            "broad_stage": P.BROAD_APPLICATION, "stage": "at_credit_risk",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_cannot_disburse_more_than_was_requested(self):
        res = self.as_(self.rm).post(f"{BASE}entries/", {
            "kind": "asset", "customer_name": "Almasi Financial",
            "amount": "10000000", "amount_to_disburse": "50000000",
            "product": "Working Capital",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("amount_to_disburse", res.data)

    def test_a_deposit_needs_casa_or_fd(self):
        res = self.as_(self.rm).post(f"{BASE}entries/", {
            "kind": "deposit", "customer_name": "Modern Precast",
            "amount": "654000000",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("deposit_product", res.data)

    def test_a_liability_accepts_new_to_bank_as_an_account_number(self):
        """The file has 'New to bank' and 'tba'. Both are real answers."""
        res = self.as_(self.rm).post(f"{BASE}entries/", {
            "kind": "liability", "customer_name": "Sameer Group ltd",
            "amount": "50000000", "account_no": "New to bank",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    # ── ownership on create ──────────────────────────────────────────
    def test_a_new_line_is_stamped_with_the_rms_own_code(self):
        self.as_(self.rm).post(f"{BASE}entries/", {
            "kind": "trade", "customer_name": "Experian Limited",
            "amount": "50000000", "revenue": "500000", "product": "LC",
        }, format="json")
        row = P.objects.get(customer_name="Experian Limited")
        self.assertEqual(row.sales_code, "CM001")
        self.assertEqual(row.segment, "COMMERCIAL")

    # ── removing a line ──────────────────────────────────────────────
    def test_deleting_clears_rather_than_erases(self):
        res = self.as_(self.rm).delete(f"{BASE}entries/{self.mine.id}/")
        self.assertEqual(res.status_code, 204)
        self.mine.refresh_from_db()
        self.assertFalse(self.mine.is_active)

        listed = self.as_(self.rm).get(f"{BASE}entries/")
        self.assertEqual(listed.data["count"], 0, "cleared rows are out by default")

        kept = self.as_(self.rm).get(f"{BASE}entries/", {"is_active": "false"})
        self.assertEqual(kept.data["count"], 1, "and can still be looked at")

    # ── what the TL opens it for ─────────────────────────────────────
    def test_the_summary_totals_the_team(self):
        res = self.as_(self.tl).get(f"{BASE}summary/")
        self.assertEqual(res.data["scope"], "team")
        assets = next(r for r in res.data["by_kind"] if r["kind"] == "asset")
        self.assertEqual(assets["count"], 2)
        self.assertEqual(assets["total_amount"], Decimal("17500000"))

    def test_the_summary_for_an_rm_covers_only_their_own(self):
        res = self.as_(self.rm).get(f"{BASE}summary/")
        self.assertEqual(res.data["scope"], "mine")
        assets = next(r for r in res.data["by_kind"] if r["kind"] == "asset")
        self.assertEqual(assets["total_amount"], Decimal("10000000"))

    def test_export_is_scoped_the_same_way_as_the_list(self):
        body = self.as_(self.rm).get(f"{BASE}export/").content.decode()
        self.assertIn("Technomasters Limited", body)
        self.assertNotIn("Estina Green Limited", body)

    def test_options_offers_the_stages_under_each_broad_stage(self):
        res = self.as_(self.rm).get(f"{BASE}options/")
        self.assertIn("at_credit_risk",
                      res.data["stages_under_broad"][P.BROAD_APPLICATION])
        self.assertFalse(res.data["can_see_team"])
        self.assertTrue(self.as_(self.tl).get(f"{BASE}options/").data["can_see_team"])


class WorkbookUploadTests(APITestCase):
    """Loading the workbook without a shell on the host."""

    def setUp(self):
        self.rm = user("up_rm", sales_code="CM010")
        self.tl = user("up_tl", sales_code="CM911", group="tl_portfolio")

    def as_(self, who):
        c = APIClient()
        c.force_authenticate(who)
        return c

    def book(self, name="pipeline.xlsx"):
        """A workbook shaped like the real one, built in memory."""
        import io as _io

        import openpyxl
        from django.core.files.uploadedfile import SimpleUploadedFile

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Assets Pipeline"
        ws.append(["Branch", "Sales Person Name", "Customer Name",
                   "Loan Amount Requested", "Amount to be Disbursed", "Product",
                   "Broad Application stage", "Additional comments"])
        ws.append(["Commercial", "Anne Kimani", "Technomasters Limited",
                   10000000, 6000000, "Contract Finance", "Approved", "Limit in place"])
        # 'Credit Risk' is not a broad stage; the importer must place it properly.
        ws.append(["Commercial", "Irene Njenga", "Cloudarc Solutions Ltd",
                   10000000, 10000000, "Contract Financing", "Credit Risk", ""])
        # A row with no customer is skipped, not imported blank.
        ws.append(["Commercial", "Nobody", "", 500, 500, "x", "Approved", ""])

        trade = wb.create_sheet("Trade Pipeline")
        trade.append(["Branch", "Sales Person Name", "Customer Name", "Amount ",
                      "Revenues", "Type", "Application Stage", "Comments"])
        trade.append(["Commercial", "Lilian Biwott", "Experian Limited",
                      50000000, 500000, "LC", "Approved", "Issued."])

        buf = _io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile(
            name, buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def post(self, who, **extra):
        payload = {"file": self.book()}
        payload.update(extra)
        return self.as_(who).post(f"{BASE}upload/", payload, format="multipart")

    def test_an_rm_cannot_load_everybody_elses_rows(self):
        self.assertEqual(self.post(self.rm).status_code, 403)

    def test_the_first_upload_reports_and_writes_nothing(self):
        res = self.post(self.tl)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(res.data["applied"])
        self.assertEqual(res.data["total"], 3)
        self.assertEqual(res.data["skipped"], 1, "the row with no customer")
        self.assertEqual(P.objects.count(), 0, "nothing saved on a dry run")

    def test_applying_saves_and_places_the_stages_properly(self):
        res = self.post(self.tl, apply="true")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(P.objects.count(), 3)

        row = P.objects.get(customer_name="Cloudarc Solutions Ltd")
        self.assertEqual(row.broad_stage, P.BROAD_APPLICATION,
                         "'Credit Risk' is a specific stage, not a broad one")
        self.assertEqual(row.stage, "at_credit_risk")

    def test_replace_removes_imported_rows_but_never_somebody_s_own(self):
        self.post(self.tl, apply="true")
        typed = P.objects.create(kind=P.KIND_ASSET, customer_name="Typed by an RM",
                                 segment="COMMERCIAL", amount=1, created_by=self.rm)

        self.post(self.tl, apply="true", replace="true")
        self.assertTrue(P.objects.filter(pk=typed.pk).exists(),
                        "a row an RM typed must survive a re-upload")
        self.assertEqual(P.objects.filter(created_by__isnull=True).count(), 3,
                         "the previous import was replaced, not doubled")

    def test_a_file_that_is_not_a_workbook_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        res = self.as_(self.tl).post(
            f"{BASE}upload/",
            {"file": SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")},
            format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Excel", str(res.data))
