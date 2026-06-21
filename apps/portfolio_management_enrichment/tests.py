from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from apps.portfolio.models import Profile
from apps.portfolio_management_enrichment.models import (
    CustomerAllocationBase, RmAllocationList, TeamLeaderMovementApprovers,
    CustomerTransferHistory,
)

User = get_user_model()
PME = "/portfolio_management_enrichment/"


def _user(username, group, sales_code, segment=""):
    u = User.objects.create_user(username=username, password="pw12345")
    Group.objects.get_or_create(name=group)
    u.groups.add(Group.objects.get(name=group))
    # Profile is auto-created by a post_save signal; update it.
    p = Profile.objects.get(user=u)
    p.sales_code = sales_code
    p.segment = segment
    p.save()
    return u


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _rm(code, name, segment="retail"):
    return RmAllocationList.objects.create(
        rm_code=code, rm_name=name, rm_role="RM", rm_branch_name="Branch A",
        rm_branch_code="A1", rm_active_status="Active", source="seed", rm_segment=segment,
    )


def _customer(cust_id="C1", owner="RM002", segment="retail"):
    return CustomerAllocationBase.objects.create(
        group_id="G1", cust_id=cust_id, customer_name="Acme Ltd", segment=segment,
        main_segment_prev=segment, main_segment=segment, customer_branch_name="Branch A",
        cust_branch="A1", proposed_segment=segment, aum_group=Decimal("0"), aum_cust_id=Decimal("100"),
        rm_code_prev=owner, rm_name_prev="Bob", rm_role_prev="RM", rm_branch_prev="Branch A",
        rm_segment_prev=segment, rank_branch=1, rank_rm_code=1,
        rm_code=owner, rm_name="Bob", rm_role="RM", rm_branch_name="Branch A",
        rm_branch_code="A1", rm_active_status="Active", source="seed",
        active_one_month=Decimal("1"), active_two_month=Decimal("1"), active_three_month=Decimal("1"),
    )


class ReallocationWorkflowTests(TestCase):
    def setUp(self):
        # RM001 wants the customer; RM002 currently owns it; TL001 finalises.
        self.rm1 = _user("rm1", "portfolio_mgt", "RM001", "retail")
        self.rm2 = _user("rm2", "portfolio_mgt", "RM002", "retail")
        self.tl = _user("tl1", "tl_portfolio", "TL001", "retail")
        _rm("RM001", "Alice")
        _rm("RM002", "Bob")
        TeamLeaderMovementApprovers.objects.create(segment="retail", sales_code="TL001", name="Tara", branch_code="A1")
        self.customer = _customer()

    def _initiate(self):
        return _client(self.rm1).post(
            f"{PME}customer/C1/transfer/", {"to_rm_code": "RM002", "requesting_comments": "please"}, format="json",
        )

    def test_full_lifecycle_moves_customer(self):
        # 1. RM1 requests
        r = self._initiate()
        self.assertEqual(r.status_code, 201, r.content)
        tid = r.data["id"]
        self.assertEqual(r.data["approval_status"], "under_review")

        # 2. Counter-RM (RM2, current owner) approves
        r = _client(self.rm2).post(f"{PME}customer/C1/transfer/{tid}/approve/", {"approval_comments": "ok"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["approval_status"], "rm_approved")

        # 3. TL finalises → customer moves to the requesting RM (from_rm = RM001)
        r = _client(self.tl).post(f"{PME}customer/C1/transfer/{tid}/team-leader-approve/", {"approval_comments": "done"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["approval_status"], "approved")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.rm_code, "RM001")

    def test_reject(self):
        tid = self._initiate().data["id"]
        r = _client(self.rm2).post(f"{PME}customer/C1/transfer/{tid}/reject/", {"approval_comments": "no"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["approval_status"], "rejected")

    def test_tl_direct_reallocation_moves_customer(self):
        r = _client(self.tl).post(
            f"{PME}customer/C1/tl_reallocate/", {"to_rm_code": "RM001", "approval_comments": "strategic"}, format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["approval_status"], "tl_reallocation")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.rm_code, "RM001")

    def test_worklist_to_shows_pending_for_counter_rm(self):
        self._initiate()
        r = _client(self.rm2).get(f"{PME}transfers/to/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(any(t["cust_id"] == "C1" for t in r.data))

    def test_rm_list_and_filter_customer(self):
        c = _client(self.rm1)
        r = c.get(f"{PME}rm_list/")
        self.assertEqual(r.status_code, 200, r.content)
        r = c.get(f"{PME}filter-customer/?customer_name=Acme")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("total_pages", r.data)
        self.assertEqual(r.data["count"], 1)

    def test_transfer_history_and_feedback_history(self):
        tid = self._initiate().data["id"]
        c = _client(self.rm1)
        r = c.get(f"{PME}customer/C1/transfer-history/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["count"], 1)
        r = c.get(f"{PME}feedback/{tid}/history/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(len(r.data), 1)

    def test_update_allocation_blocked_in_split_db(self):
        # EXCO user; endpoint returns 501 with the split-DB explanation.
        exco = _user("exco1", "exco", "EX001", "retail")
        r = _client(exco).post(f"{PME}api/update-portfolio-allocation/", {}, format="json")
        self.assertEqual(r.status_code, 501, r.content)
