"""A retail back office person's own card file fills the lines whose return
has no row for them (Sarah Nzeli: CRM 95, engagement 0.57 on her H1 June
card, neither on the CX returns). Loaded onto exactly one List person."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from . import workbook_cards as wc

URL = "/staff_management/scorecard-automation/manual-figures/bo-actuals/"


def own_card(name="Sarah Nzeli"):
    wb = Workbook()
    ws = wb.active
    ws.title = "RO_COMMERCIAL"
    ws["C2"], ws["E2"], ws["C4"] = name, "RELATIONSHIP OFFICER - COMMERCIAL", "H1_Jun_2026"
    ws["H16"], ws["K16"] = 95, "Commercial_CRM"
    ws["H24"], ws["K24"] = 0.57, "Commercial_Contactability"
    ws["H20"], ws["K20"] = "n/a", "HFDI_Value"            # not a number: not kept
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class RboPersonCardTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient

        wc.save_file(wc.SPECS[wc.RETAIL_BO].files[0], {
            "book": wc.RETAIL_BO, "cards": {}, "tables": {"List": [
                ["staff_pf", "sales_code", "staff_name", "staff_role", "staff_branch"],
                [3521, "SN3521", "Sarah Nzeli", "RELATIONSHIP OFFICER - COMMERCIAL",
                 "Head Office"]]}}, "rbo.xlsm", "t", year=2026)
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_superuser("root.admin", password="x"))

    def test_read(self):
        card = wc.read_rbo_person_card(own_card())
        self.assertEqual((card["name"], card["month"]), ("Sarah Nzeli", "2026-06"))
        self.assertEqual(card["figures"], {"Commercial_CRM": 95.0,
                                           "Commercial_Contactability": 0.57})

    def test_load_onto_the_one_person_then_the_figure_is_there(self):
        r = self.client.post(URL, {"file": SimpleUploadedFile("Sarah Nzeli_H1_Jun_2026_Scorecard.xlsx",
                                                              own_card()), "apply": "1"},
                             format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("Sarah Nzeli (SN3521)", r.data["detail"])
        self.assertEqual(wc.rbo_card_figure("sn3521", "Commercial_CRM"), (95.0, "2026-06"))
        self.assertEqual(wc.rbo_card_figure("SN3521", "Other"), (None, None))

    def test_a_name_not_on_the_list_is_refused(self):
        r = self.client.post(URL, {"file": SimpleUploadedFile("x.xlsx", own_card("Nobody Here")),
                                   "apply": "1"}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(wc.saved(wc.RBO_CARD_FIGURES))
