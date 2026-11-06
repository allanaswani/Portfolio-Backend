"""Each table's spelling of a branch, as measured on production."""

from django.test import SimpleTestCase, TestCase

from core.branch_codes import branch_codes_for
from core.branch_names import customer_branch, roster_branch


class BranchNameTests(SimpleTestCase):
    def test_harambee_under_every_name(self):
        for name in ("HARAMBEE AVE BRANCH", "HARAMBEE AVENUE BRANCH", "GILL HOUSE BRANCH",
                     "GILL HOUSE", " harambee ave branch "):
            self.assertEqual(customer_branch(name), "HARAMBEE AVENUE BRANCH")
            self.assertEqual(roster_branch(name), "HARAMBEE AVE BRANCH")

    def test_the_accounts_that_matched_no_customers(self):
        self.assertEqual(customer_branch("SAMEER BRANCH"), "SAMEER BUSINESS PARK BRANCH")
        self.assertEqual(customer_branch("EMBU BRANCH BRANCH"), "EMBU BRANCH")
        self.assertEqual(customer_branch("HEAD OFFICE BRANCH"), "HEAD OFFICE")
        self.assertEqual(customer_branch("TRM BRANCH"), "THIKA ROAD MALL-TRM BRANCH")
        self.assertEqual(customer_branch("HF WHIZZ BRANCH"), "HFCB WHIZZ")

    def test_a_bare_name_finds_the_branch_for_the_exact_match_queries(self):
        self.assertEqual(customer_branch("REHANI"), "REHANI BRANCH")

    def test_the_arrears_mapping_has_its_own_names(self):
        self.assertEqual(roster_branch("THIKA ROAD MALL-TRM BRANCH"), "TRM BRANCH")
        self.assertEqual(roster_branch("SAMEER BUSINESS PARK BRANCH"), "SAMEER BRANCH")

    def test_a_branch_named_the_same_everywhere_is_untouched(self):
        self.assertEqual(customer_branch("ELDORET BRANCH"), "ELDORET BRANCH")
        self.assertEqual(roster_branch("ELDORET BRANCH"), "ELDORET BRANCH")

    def test_no_name_stays_no_name(self):
        self.assertEqual(customer_branch(""), "")
        self.assertEqual(customer_branch(None), "")

    def test_a_name_it_does_not_know_is_left_alone(self):
        self.assertEqual(customer_branch("RETAIL MORTGAGE SALES"), "RETAIL MORTGAGE SALES")


class BranchCodeTests(TestCase):
    def test_every_spelling_reaches_the_code(self):
        for name in ("HARAMBEE AVENUE BRANCH", "HARAMBEE AVE BRANCH", "GILL HOUSE BRANCH"):
            self.assertIn(220, branch_codes_for(name))
        self.assertIn(260, branch_codes_for("THIKA ROAD MALL-TRM BRANCH"))
        self.assertIn(270, branch_codes_for("SAMEER BUSINESS PARK BRANCH"))

    def test_an_unknown_branch_still_matches_nothing(self):
        self.assertEqual(branch_codes_for("NOT A BRANCH"), [])
