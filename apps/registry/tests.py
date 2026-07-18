"""Registry tests — Phase 1 custody loop + Phase 2 archives/retention/destruction."""

from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (
    ArchiveBox, ArchiveConsignment, DestructionBatch,
    FileRecord, MissingFileIncident, MovementCard, StockTake, StockTakeItem,
    MAX_OPEN_FILES_PER_BORROWER, _add_years,
)


class RegistryTests(APITestCase):
    def setUp(self):
        self.officer = User.objects.create_user("reg", password="x")
        self.officer.groups.add(Group.objects.get_or_create(name="registry_officer")[0])
        self.borrower = User.objects.create_user("rm1", password="x")
        self.other = User.objects.create_user("nobody", password="x")

    def _file(self, no="F-001", ftype=FileRecord.TYPE_LOAN):
        return FileRecord.objects.create(file_no=no, customer_name="Acme", file_type=ftype)

    # retention -------------------------------------------------------------
    def test_retention_auto_from_type(self):
        loan = self._file("L1", FileRecord.TYPE_LOAN)
        mortgage = self._file("M1", FileRecord.TYPE_MORTGAGE)
        self.assertEqual(loan.retention_class, FileRecord.RETENTION_SEVEN_YEAR)
        self.assertEqual(mortgage.retention_class, FileRecord.RETENTION_LIFE)

    # auth ------------------------------------------------------------------
    def test_non_staff_cannot_create_file(self):
        self.client.force_authenticate(self.borrower)
        resp = self.client.post("/registry/files/", {"file_no": "X", "customer_name": "Y"})
        self.assertEqual(resp.status_code, 403)

    def test_read_requires_auth(self):
        self.assertEqual(self.client.get("/registry/files/").status_code, 401)

    # issue / return --------------------------------------------------------
    def test_issue_then_return_cycle(self):
        f = self._file()
        self.client.force_authenticate(self.officer)

        r = self.client.post(
            f"/registry/files/{f.pk}/issue/",
            {"borrower": self.borrower.pk, "department": "Credit", "borrower_ack": True},
        )
        self.assertEqual(r.status_code, 201, r.content)
        f.refresh_from_db()
        self.assertEqual(f.status, FileRecord.STATUS_ON_LOAN)

        # cannot double-issue
        r2 = self.client.post(f"/registry/files/{f.pk}/issue/", {"borrower": self.borrower.pk})
        self.assertEqual(r2.status_code, 400)

        # due date is 4 weeks out
        card = f.open_card
        self.assertAlmostEqual(
            (card.due_at - card.issued_at).days, 28, delta=1,
        )

        r3 = self.client.post(f"/registry/files/{f.pk}/return/", {"returned_condition": "ok"})
        self.assertEqual(r3.status_code, 200, r3.content)
        f.refresh_from_db()
        self.assertEqual(f.status, FileRecord.STATUS_ACTIVE)
        self.assertIsNone(f.open_card)

    def test_return_when_not_on_loan_fails(self):
        f = self._file()
        self.client.force_authenticate(self.officer)
        r = self.client.post(f"/registry/files/{f.pk}/return/", {})
        self.assertEqual(r.status_code, 400)

    # 50-file cap -----------------------------------------------------------
    def test_fifty_file_cap(self):
        self.client.force_authenticate(self.officer)
        now = timezone.now()
        for i in range(MAX_OPEN_FILES_PER_BORROWER):
            f = self._file(f"C{i}")
            MovementCard.objects.create(
                file=f, borrower=self.borrower, issued_by=self.officer,
                due_at=now + timedelta(days=28),
            )
            f.status = FileRecord.STATUS_ON_LOAN
            f.save(update_fields=["status"])

        extra = self._file("C-EXTRA")
        r = self.client.post(f"/registry/files/{extra.pk}/issue/", {"borrower": self.borrower.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIn("max", str(r.content).lower())

    # overdue report --------------------------------------------------------
    def test_overdue_report_lists_only_overdue_open_cards(self):
        now = timezone.now()
        overdue_file = self._file("OD1")
        MovementCard.objects.create(
            file=overdue_file, borrower=self.borrower, issued_by=self.officer,
            issued_at=now - timedelta(days=40), due_at=now - timedelta(days=12),
        )
        overdue_file.status = FileRecord.STATUS_ON_LOAN
        overdue_file.save(update_fields=["status"])

        fresh_file = self._file("OK1")
        MovementCard.objects.create(
            file=fresh_file, borrower=self.borrower, issued_by=self.officer,
            due_at=now + timedelta(days=28),
        )

        self.client.force_authenticate(self.officer)
        r = self.client.get("/registry/overdue/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["file_no"], "OD1")

    # borrower lookup --------------------------------------------------------
    def test_user_lookup_requires_registry_staff(self):
        self.client.force_authenticate(self.borrower)  # not registry staff
        self.assertEqual(self.client.get("/registry/users/").status_code, 403)

    def test_user_lookup_searches_active_users(self):
        User.objects.create_user("jane", first_name="Jane", last_name="Doe", password="x")
        User.objects.create_user("inactive", is_active=False, password="x")
        self.client.force_authenticate(self.officer)

        r = self.client.get("/registry/users/?search=jane")
        self.assertEqual(r.status_code, 200)
        names = [u["username"] for u in r.data]
        self.assertIn("jane", names)
        self.assertEqual(r.data[0]["name"], "Jane Doe")

        # inactive users are excluded
        r2 = self.client.get("/registry/users/?search=inactive")
        self.assertEqual([u["username"] for u in r2.data], [])

    def test_my_files(self):
        f = self._file()
        MovementCard.objects.create(
            file=f, borrower=self.borrower, issued_by=self.officer,
            due_at=timezone.now() + timedelta(days=28),
        )
        self.client.force_authenticate(self.borrower)
        r = self.client.get("/registry/my-files/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)


class RegistryPhase2Tests(APITestCase):
    """Archives transfer (§3.5), retention clock, and destruction (§3.6)."""

    def setUp(self):
        self.officer = User.objects.create_user("reg2", password="x")
        self.officer.groups.add(Group.objects.get_or_create(name="registry_officer")[0])
        self.exec = User.objects.create_superuser("coo", password="x")  # admin tier
        self.outsider = User.objects.create_user("rm", password="x")

    def _file(self, no, ftype=FileRecord.TYPE_LOAN, opened=None, redeemed=None):
        return FileRecord.objects.create(
            file_no=no, customer_name="Acme", file_type=ftype,
            opened_on=opened or date.today(), redeemed_on=redeemed,
        )

    # retention clock -------------------------------------------------------
    def test_retention_due_on_computation(self):
        old_loan = self._file("R-OLD", opened=_add_years(date.today(), -8))
        fresh_loan = self._file("R-NEW", opened=date.today())
        mortgage = self._file("R-MTG", ftype=FileRecord.TYPE_MORTGAGE,
                              opened=_add_years(date.today(), -20))
        self.assertTrue(old_loan.is_destruction_due)
        self.assertFalse(fresh_loan.is_destruction_due)
        self.assertIsNone(mortgage.retention_due_on)        # life = never
        self.assertFalse(mortgage.is_destruction_due)

    def test_retention_due_endpoint(self):
        self._file("R-OLD", opened=_add_years(date.today(), -8))
        self._file("R-NEW", opened=date.today())
        self._file("R-MTG", ftype=FileRecord.TYPE_MORTGAGE,
                   opened=_add_years(date.today(), -20))
        self.client.force_authenticate(self.officer)
        r = self.client.get("/registry/retention-due/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["file_no"], "R-OLD")

    # archives transfer -----------------------------------------------------
    def test_transfer_to_archives(self):
        f1 = self._file("A-1", redeemed=date.today())
        f2 = self._file("A-2", redeemed=date.today())
        self.client.force_authenticate(self.officer)

        r = self.client.post("/registry/consignments/", {
            "source_unit": "Nairobi Branch",
            "file_ids": [f1.pk, f2.pk],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.data["id"]

        rec = self.client.post(f"/registry/consignments/{cid}/receive/", {
            "box_code": "BOX-001", "location": "Aisle 4",
        }, format="json")
        self.assertEqual(rec.status_code, 200, rec.content)

        for f in (f1, f2):
            f.refresh_from_db()
            self.assertEqual(f.status, FileRecord.STATUS_ARCHIVED)
            self.assertIsNotNone(f.archived_at)
        box = ArchiveBox.objects.get(code="BOX-001")
        self.assertEqual(box.files.count(), 2)

        # cannot re-receive
        again = self.client.post(f"/registry/consignments/{cid}/receive/",
                                 {"box_code": "BOX-002"}, format="json")
        self.assertEqual(again.status_code, 400)

    # destruction workflow --------------------------------------------------
    def test_destruction_requires_three_signoffs(self):
        f = self._file("D-1", opened=_add_years(date.today(), -8))
        self.client.force_authenticate(self.officer)

        r = self.client.post("/registry/destructions/", {"file_ids": [f.pk]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        bid = r.data["id"]
        self.assertTrue(r.data["reference"].startswith("DST-"))

        # unit sign-off by registry staff
        self.client.post(f"/registry/destructions/{bid}/approve/", {"stage": "unit"}, format="json")
        # head_ops sign-off must be admin-tier — officer is denied
        denied = self.client.post(f"/registry/destructions/{bid}/approve/",
                                  {"stage": "head_ops"}, format="json")
        self.assertEqual(denied.status_code, 400)

        # cannot destroy before full approval
        early = self.client.post(f"/registry/destructions/{bid}/destroy/",
                                 {"vendor": "Pulp Co"}, format="json")
        self.assertEqual(early.status_code, 400)

        # exec completes head_ops + coo
        self.client.force_authenticate(self.exec)
        self.client.post(f"/registry/destructions/{bid}/approve/", {"stage": "head_ops"}, format="json")
        appr = self.client.post(f"/registry/destructions/{bid}/approve/", {"stage": "coo"}, format="json")
        self.assertEqual(appr.data["status"], "approved")
        self.assertTrue(appr.data["is_fully_approved"])

        # destroy → files destroyed
        dz = self.client.post(f"/registry/destructions/{bid}/destroy/",
                              {"vendor": "Pulp Co", "destruction_location": "Athi"}, format="json")
        self.assertEqual(dz.status_code, 200, dz.content)
        f.refresh_from_db()
        self.assertEqual(f.status, FileRecord.STATUS_DESTROYED)

        # certify
        cert = self.client.post(f"/registry/destructions/{bid}/certify/",
                               {"certificate_ref": "CERT-9"}, format="json")
        self.assertEqual(cert.status_code, 200, cert.content)
        self.assertEqual(cert.data["status"], "certified")

    def test_archives_endpoints_require_registry_staff(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get("/registry/consignments/").status_code, 403)
        self.assertEqual(self.client.get("/registry/destructions/").status_code, 403)
        self.assertEqual(self.client.get("/registry/retention-due/").status_code, 403)


class RegistryPhase3Tests(APITestCase):
    """Stock-take & missing-file incidents (§3.7)."""

    def setUp(self):
        self.officer = User.objects.create_user("reg3", password="x")
        self.officer.groups.add(Group.objects.get_or_create(name="registry_officer")[0])
        self.outsider = User.objects.create_user("rm3", password="x")

    def _file(self, no, status=FileRecord.STATUS_ACTIVE, pocket=""):
        return FileRecord.objects.create(
            file_no=no, customer_name="Acme", file_type=FileRecord.TYPE_LOAN,
            status=status, pocket=pocket,
        )

    # stock-take scope + snapshot ------------------------------------------
    def test_open_stock_take_snapshots_shelf_and_issued_files(self):
        """§3.7 counts issued files too — they're verified with the officer."""
        self._file("S-1")
        self._file("S-2")
        self._file("S-ONLOAN", status=FileRecord.STATUS_ON_LOAN)
        self._file("S-ARCHIVED", status=FileRecord.STATUS_ARCHIVED)  # left registry
        self.client.force_authenticate(self.officer)

        r = self.client.post("/registry/stock-takes/", {"title": "Q3 count"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        st = StockTake.objects.get(pk=r.data["id"])
        self.assertEqual(
            sorted(i.file.file_no for i in st.items.all()),
            ["S-1", "S-2", "S-ONLOAN"],
        )

    def test_snapshot_records_the_officer_holding_the_file(self):
        """§3.7 step 3 needs to know who a file was marked to."""
        borrower = User.objects.create_user("holder", password="x")
        shelf = self._file("M-SHELF")
        issued = self._file("M-ISSUED")
        MovementCard.objects.create(
            file=issued, borrower=borrower, borrower_ack=True,
            due_at=timezone.now() + timedelta(days=28),
        )
        issued.status = FileRecord.STATUS_ON_LOAN
        issued.save()

        self.client.force_authenticate(self.officer)
        r = self.client.post("/registry/stock-takes/", {"title": "count"}, format="json")
        st = StockTake.objects.get(pk=r.data["id"])
        self.assertEqual(st.items.get(file=issued).marked_to, borrower)
        self.assertIsNone(st.items.get(file=shelf).marked_to)

    def test_location_scoped_stock_take(self):
        self._file("L-A", pocket="A1")
        self._file("L-B", pocket="B2")
        self.client.force_authenticate(self.officer)
        r = self.client.post(
            "/registry/stock-takes/", {"title": "Aisle A", "location": "A1"}, format="json"
        )
        st = StockTake.objects.get(pk=r.data["id"])
        self.assertEqual([i.file.file_no for i in st.items.all()], ["L-A"])

    # sight + close raises incidents ---------------------------------------
    def test_close_flags_unsighted_as_missing(self):
        found = self._file("C-FOUND")
        lost = self._file("C-LOST")
        self.client.force_authenticate(self.officer)

        r = self.client.post("/registry/stock-takes/", {"title": "count"}, format="json")
        stid = r.data["id"]
        st = StockTake.objects.get(pk=stid)
        found_item = st.items.get(file=found)

        # sight one of the two
        s = self.client.post(
            f"/registry/stock-takes/{stid}/sight/",
            {"item": found_item.pk, "sighted": True}, format="json",
        )
        self.assertEqual(s.status_code, 200, s.content)

        c = self.client.post(f"/registry/stock-takes/{stid}/close/")
        self.assertEqual(c.status_code, 200, c.content)

        found.refresh_from_db()
        lost.refresh_from_db()
        self.assertEqual(found.status, FileRecord.STATUS_ACTIVE)
        self.assertEqual(lost.status, FileRecord.STATUS_MISSING)
        # incident raised for the lost file only
        self.assertEqual(MissingFileIncident.objects.filter(file=lost).count(), 1)
        self.assertEqual(MissingFileIncident.objects.filter(file=found).count(), 0)

        st.refresh_from_db()
        self.assertEqual(st.status, StockTake.STATUS_CLOSED)

    def test_close_splits_untraced_by_marked_to_officer(self):
        """§3.7 step 3/4: a file marked to an officer has a trace — chase the
        officer per the overdue procedure; don't flag it untraced/missing."""
        borrower = User.objects.create_user("holder2", password="x")
        unmarked = self._file("K-SHELF")
        issued = self._file("K-ISSUED")
        MovementCard.objects.create(
            file=issued, borrower=borrower, borrower_ack=True,
            due_at=timezone.now() + timedelta(days=28),
        )
        issued.status = FileRecord.STATUS_ON_LOAN
        issued.save()

        self.client.force_authenticate(self.officer)
        r = self.client.post("/registry/stock-takes/", {"title": "count"}, format="json")
        stid = r.data["id"]
        # Neither is sighted.
        c = self.client.post(f"/registry/stock-takes/{stid}/close/")
        self.assertEqual(c.status_code, 200, c.content)

        # Marked to an officer: incident records the holder, file stays on loan.
        issued.refresh_from_db()
        self.assertEqual(issued.status, FileRecord.STATUS_ON_LOAN)
        marked_inc = MissingFileIncident.objects.get(file=issued)
        self.assertEqual(marked_inc.marked_to, borrower)

        # Marked to nobody: genuinely untraced.
        unmarked.refresh_from_db()
        self.assertEqual(unmarked.status, FileRecord.STATUS_MISSING)
        self.assertIsNone(MissingFileIncident.objects.get(file=unmarked).marked_to)

        # The status report splits the two (§3.7 step 3).
        self.assertEqual(c.data["missing_marked"], 1)
        self.assertEqual(c.data["missing_unmarked"], 1)

    def test_file_issued_mid_count_is_traceable_not_missing(self):
        """Issued after the snapshot: the open card is still a trace to follow."""
        borrower = User.objects.create_user("holder3", password="x")
        f = self._file("MID-1")
        self.client.force_authenticate(self.officer)
        r = self.client.post("/registry/stock-takes/", {"title": "count"}, format="json")

        # Issued out after the count opened, so never sighted on the shelf.
        MovementCard.objects.create(
            file=f, borrower=borrower, borrower_ack=True,
            due_at=timezone.now() + timedelta(days=28),
        )
        f.status = FileRecord.STATUS_ON_LOAN
        f.save()

        self.client.post(f"/registry/stock-takes/{r.data['id']}/close/")
        f.refresh_from_db()
        self.assertEqual(f.status, FileRecord.STATUS_ON_LOAN)
        self.assertEqual(MissingFileIncident.objects.get(file=f).marked_to, borrower)

    def test_cannot_sight_closed_stock_take(self):
        self._file("Z-1")
        self.client.force_authenticate(self.officer)
        r = self.client.post("/registry/stock-takes/", {"title": "x"}, format="json")
        stid = r.data["id"]
        item = StockTake.objects.get(pk=stid).items.first()
        self.client.post(f"/registry/stock-takes/{stid}/close/")
        s = self.client.post(
            f"/registry/stock-takes/{stid}/sight/",
            {"item": item.pk, "sighted": True}, format="json",
        )
        self.assertEqual(s.status_code, 400)

    # incident resolution ---------------------------------------------------
    def test_incident_found_returns_file_to_active(self):
        f = self._file("I-1")
        self.client.force_authenticate(self.officer)
        r = self.client.post("/registry/incidents/", {"file": f.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        f.refresh_from_db()
        self.assertEqual(f.status, FileRecord.STATUS_MISSING)

        res = self.client.post(
            f"/registry/incidents/{r.data['id']}/resolve/",
            {"outcome": "found", "resolution_note": "in RM's drawer"}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["status"], "found")
        f.refresh_from_db()
        self.assertEqual(f.status, FileRecord.STATUS_ACTIVE)

    def test_incident_skeleton_creates_replacement(self):
        f = self._file("I-2", pocket="P9")
        self.client.force_authenticate(self.officer)
        r = self.client.post("/registry/incidents/", {"file": f.pk}, format="json")
        res = self.client.post(
            f"/registry/incidents/{r.data['id']}/resolve/",
            {"outcome": "skeleton"}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["status"], "skeleton")

        skeleton = FileRecord.objects.get(file_no="I-2-SKEL")
        self.assertTrue(skeleton.is_skeleton)
        self.assertEqual(skeleton.pocket, "P9")
        f.refresh_from_db()
        self.assertEqual(f.status, FileRecord.STATUS_MISSING)  # original stays lost

    def test_cannot_resolve_twice(self):
        f = self._file("I-3")
        self.client.force_authenticate(self.officer)
        r = self.client.post("/registry/incidents/", {"file": f.pk}, format="json")
        iid = r.data["id"]
        self.client.post(f"/registry/incidents/{iid}/resolve/", {"outcome": "found"}, format="json")
        again = self.client.post(
            f"/registry/incidents/{iid}/resolve/", {"outcome": "found"}, format="json"
        )
        self.assertEqual(again.status_code, 400)

    def test_phase3_endpoints_require_registry_staff(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get("/registry/stock-takes/").status_code, 403)
        self.assertEqual(self.client.get("/registry/incidents/").status_code, 403)
