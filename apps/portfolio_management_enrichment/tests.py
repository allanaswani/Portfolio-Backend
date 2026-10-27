from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
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


# ── CustomerAllocationBase CSV upload (cust_id upsert + changed_fields + ZIP) ────

def _alloc_csv(rows):
    """CSV covering every editable column of CustomerAllocationBase with type-valid fills."""
    import csv
    import io
    from django.db import models as dm

    fields = [f for f in CustomerAllocationBase._meta.concrete_fields if f.editable and f.name != "id"]
    cols = [f.name for f in fields]

    def default_for(f):
        if isinstance(f, dm.EmailField):
            return "a@b.com"
        if isinstance(f, (dm.IntegerField, dm.BigIntegerField, dm.DecimalField, dm.FloatField)):
            return "0"
        return "x"

    by_name = {f.name: f for f in fields}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r[c] if c in r else default_for(by_name[c]) for c in cols})
    return SimpleUploadedFile("alloc.csv", buf.getvalue().encode("utf-8"), content_type="text/csv")


class CustomerAllocationBaseUploadTests(TestCase):
    def setUp(self):
        self.client = _client(_user("up1", "portfolio_mgt", "PM1"))

    def test_create_then_update_tracks_changed_fields(self):
        url = f"{PME}api/csv-upload/"
        r = self.client.post(url, {"file": _alloc_csv([{"cust_id": "C1", "customer_name": "Alpha", "rm_name": "RM A"}])}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("application/zip", r["Content-Type"])
        self.assertEqual(CustomerAllocationBase.objects.filter(cust_id="C1").count(), 1)
        self.assertEqual(CustomerAllocationBase.objects.get(cust_id="C1").rm_name, "RM A")

        # Re-upload with a changed rm_name → updates same row (no duplicate).
        r = self.client.post(url, {"file": _alloc_csv([{"cust_id": "C1", "customer_name": "Alpha", "rm_name": "RM B"}])}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(CustomerAllocationBase.objects.filter(cust_id="C1").count(), 1)
        self.assertEqual(CustomerAllocationBase.objects.get(cust_id="C1").rm_name, "RM B")

    def test_missing_columns_rejected(self):
        bad = SimpleUploadedFile("bad.csv", b"cust_id\nC9\n", content_type="text/csv")
        r = self.client.post(f"{PME}api/csv-upload/", {"file": bad}, format="multipart")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("missing", str(r.data).lower())


class AllocationReachesTheReallocationPagesTests(TestCase):
    """An allocation changed on /management/portfolio-allocations has to show
    on the Portfolio Reallocation pages.

    It did not, and the reason was not a cache or a delay. That dialog writes
    ``retail_allocated_portfolio``; these pages read
    ``customer_allocation_base``. Two tables, nothing joining them, so a
    customer moved to a new RM went on reading "Allocated: Unmanaged" on the
    reallocation page for ever.
    """

    FIELDS = dict(
        group_id="G1", customer_name="WILBUR AMARA", segment="ULTIMATE",
        main_segment_prev="ULTIMATE", main_segment="ULTIMATE",
        customer_branch_name="THIKA ROAD MALL-TRM BRANCH", cust_branch="260",
        proposed_segment="ULTIMATE", aum_group=Decimal("0"),
        aum_cust_id=Decimal("0"), rm_code_prev="Unmanaged",
        rm_name_prev="Unmanaged", rm_role_prev="", rm_branch_prev="",
        rm_segment_prev="", rank_branch=1, rank_rm_code=1,
        rm_code="Unmanaged", rm_name="Unmanaged", rm_role="",
        rm_branch_name="", rm_branch_code="", rm_active_status="Active",
        source="etl", active_one_month=Decimal("0"),
        active_two_month=Decimal("0"), active_three_month=Decimal("0"))

    class Row:
        """What the serializer hands perform_update, with only the fields the
        mirror reads."""
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def mirror(self, row):
        from apps.staff_management.legacy_views import (
            RetailAllocatedPortfolioDetailView)
        return RetailAllocatedPortfolioDetailView._move_allocation_base(row)

    def test_the_new_rm_reaches_the_reallocation_page(self):
        CustomerAllocationBase.objects.create(cust_id="1201871", **self.FIELDS)
        moved = self.mirror(self.Row(
            cust_id=1201871, sales_code="BAO3322", rm_name="Beldine Otieno",
            branch="260", main_segment="DIASPORA"))
        self.assertEqual(moved, 1)

        base = CustomerAllocationBase.objects.get(cust_id="1201871")
        self.assertEqual(base.rm_code, "BAO3322")
        self.assertEqual(base.rm_name, "Beldine Otieno")
        self.assertEqual(base.rm_branch_code, "260")
        self.assertEqual(base.main_segment, "DIASPORA")

    def test_the_etls_previous_columns_are_left_alone(self):
        """``*_prev`` is the ETL's own snapshot. The reallocation history
        people read comes from portfolio_customer_transfer_history, so there
        is no reason to write these - and overwriting an upstream column to
        make a page look right is how a feed starts lying."""
        CustomerAllocationBase.objects.create(cust_id="1201871", **self.FIELDS)
        self.mirror(self.Row(
            cust_id=1201871, sales_code="BAO3322", rm_name="Beldine Otieno",
            branch="260", main_segment="DIASPORA"))
        base = CustomerAllocationBase.objects.get(cust_id="1201871")
        self.assertEqual(base.rm_code_prev, "Unmanaged")
        self.assertEqual(base.rm_name_prev, "Unmanaged")

    def test_a_customer_with_no_base_row_is_not_an_error(self):
        """The allocation itself has already been saved by this point. Losing
        it because no base row exists would be the worse outcome."""
        self.assertEqual(self.mirror(self.Row(
            cust_id=999999, sales_code="BAO3322", rm_name="Beldine Otieno",
            branch="260", main_segment="DIASPORA")), 0)

    def test_the_text_and_numeric_cust_ids_still_match(self):
        """cust_id is numeric on one table and text on the other."""
        CustomerAllocationBase.objects.create(cust_id="1201871", **self.FIELDS)
        self.assertEqual(self.mirror(self.Row(
            cust_id="1201871 ", sales_code="BAO3322", rm_name="Beldine Otieno",
            branch="260", main_segment="DIASPORA")), 1)


class RmListStatusTests(TestCase):
    """An RM whose status is spelt differently must not vanish."""

    def rows(self):
        for code, name, status in (("BAO3322", "Beldine Otieno", "Active"),
                                   ("DN3998", "Doris Njuki", "ACTIVE"),
                                   ("EK4188", "Edward Kosgei", " active "),
                                   ("XX0001", "Gone Away", "Inactive")):
            RmAllocationList.objects.create(
                rm_code=code, rm_name=name, rm_role="DIASPORA RM",
                rm_branch_name="Diaspora", rm_branch_code="260",
                rm_active_status=status, source="etl", rm_segment="DIASPORA")

    def test_case_and_spacing_no_longer_decide_who_is_active(self):
        self.rows()
        user = _user("alloc.user", "portfolio_mgt", "BAO3322")
        client = APIClient()
        client.force_authenticate(user)
        body = client.get(PME + "rm_list/").data
        rows = body["results"] if isinstance(body, dict) else body
        codes = {r["rm_code"] for r in rows}
        self.assertEqual(codes, {"BAO3322", "DN3998", "EK4188"})
        self.assertNotIn("XX0001", codes)
