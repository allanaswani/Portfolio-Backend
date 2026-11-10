"""Targets for somebody the Summary Allocation sheet does not carry, and the
registration report's digital rule (10 Nov 2026, Valary Simiyu VS3759)."""
from django.test import SimpleTestCase


class OffSheetTargetTests(SimpleTestCase):
    def test_income_grows_twenty_percent_of_its_size(self):
        from .live_scorecard import OFF_SHEET_RULES, off_sheet_target

        rule = OFF_SHEET_RULES["income_contribution"]
        # The sheet's own row: 8,798,657.05 -> 10,558,388.46 (x1.2).
        target, how = off_sheet_target(rule, 8_798_657.048178162)
        self.assertAlmostEqual(target, 10_558_388.457813796, places=4)
        self.assertIn("grown 20%", how)
        # A negative base: x0.8 on the sheet.
        self.assertAlmostEqual(off_sheet_target(rule, -100.0)[0], -80.0)

    def test_loan_loss_falls_twenty_percent_of_its_size(self):
        from .live_scorecard import OFF_SHEET_RULES, off_sheet_target

        rule = OFF_SHEET_RULES["loan_loss_charge"]
        self.assertAlmostEqual(off_sheet_target(rule, 1_000.0)[0], 800.0)
        self.assertAlmostEqual(off_sheet_target(rule, -1_000.0)[0], -1_200.0)


class DigitalRuleTests(SimpleTestCase):
    def test_digital_is_the_registration_reports_trx_usr_rule(self):
        from .management.commands import load_activity_from_transactions as cmd

        self.assertEqual(cmd.DIGITAL_CHANNELS, ("%koce%", "%esb%"))
        self.assertIn("lower(t.trx_usr) LIKE ANY(%s)", cmd.SQL)
        self.assertNotIn("justific_name", cmd.SQL)


class TargetChangeTests(SimpleTestCase):
    """Mortgage Business TAT (Loan): < 7 days became < 14 days from October 2026."""

    def _card(self):
        row = [None] * 16
        row[2], row[3] = "TAT (Loan)", "< 7 Days (Binary 90%)"
        row[6] = row[7] = row[8] = 7.0
        return {"grid": [[None] * 16] * 13 + [row], "f": {}}

    def test_fourteen_days_from_october_seven_before(self):
        from . import workbook_cards as wc

        spec = wc.SPECS[wc.SALES]
        card = self._card()
        october = wc._target_changes(spec, card, "Mortgage_Business", 2026, 10)
        self.assertEqual(october[(13, spec.cols["ytd"])], 14.0)
        self.assertEqual(october[(13, spec.cols["fy"])], 14.0)
        self.assertEqual(october[(13, spec.cols["initiative"])], "< 14 Days (Binary 90%)")
        self.assertEqual(wc._target_changes(spec, card, "Mortgage_Business", 2026, 9), {})
        self.assertEqual(wc._target_changes(spec, card, "Personal_Banking", 2026, 10), {})
