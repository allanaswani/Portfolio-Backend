"""Aruti's HR reports, stored as dated snapshots."""

import datetime

from django.test import TestCase

from . import hr_reports as hr


def leave_row(pf=1005, code="AL", balance=3.56):
    return {"pf_number": pf, "leave_code": code, "leave_name": "Annual Leave",
            "name": "X", "joined": None, "period_start": None,
            "period_end": None, "bf": 3.0, "adjustment": 0.0, "accrued": 21.56,
            "encashment": 0.0, "issued": 21.0, "balance": balance}


class DetectTests(TestCase):

    def test_the_two_exports_are_told_apart_by_their_content(self):
        """Both are named .xls; one is a real .xls, the other XML."""
        self.assertEqual(
            hr.detect(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 20),
            hr.LEAVE)
        self.assertEqual(hr.detect(
            '﻿<?xml version="1.0"?>\n<?mso-application progid='
            '"Excel.Sheet"?>\n<Workbook xmlns="urn:schemas-microsoft-com:'
            'office:spreadsheet">'.encode("utf-8")), hr.LISTING)
        self.assertIsNone(hr.detect(b"sales_code,name\nAB1,x\n"))

    def test_dates_are_read_as_aruti_writes_them(self):
        self.assertEqual(hr._date("08-Oct-2026"), datetime.date(2026, 10, 8))
        self.assertIsNone(hr._date(""))


class SnapshotTests(TestCase):

    def test_reports_from_different_dates_sit_side_by_side(self):
        aug, oct_ = datetime.date(2026, 8, 31), datetime.date(2026, 10, 8)
        hr.replace_snapshot(hr.LEAVE, aug, [leave_row()])
        hr.replace_snapshot(hr.LEAVE, oct_, [leave_row(), leave_row(1009)])
        self.assertEqual(hr.snapshots(hr.LEAVE), [aug, oct_])

    def test_loading_a_date_again_replaces_only_that_date(self):
        from .models import HrLeaveBalance

        aug, oct_ = datetime.date(2026, 8, 31), datetime.date(2026, 10, 8)
        hr.replace_snapshot(hr.LEAVE, aug, [leave_row()])
        hr.replace_snapshot(hr.LEAVE, oct_, [leave_row()])
        hr.replace_snapshot(hr.LEAVE, oct_, [leave_row(), leave_row(1009),
                                             leave_row(1010)])
        self.assertEqual(HrLeaveBalance.objects.filter(as_of=oct_).count(), 3)
        self.assertEqual(HrLeaveBalance.objects.filter(as_of=aug).count(), 1)

    def test_the_listing_keeps_no_personal_columns(self):
        """Birth date, age, gender, bank and membership are dropped."""
        from .models import HrEmployeeListing

        stored = {f.name for f in HrEmployeeListing._meta.get_fields()}
        for personal in ("birthdate", "age", "gender", "bank", "membership"):
            with self.subTest(personal):
                self.assertNotIn(personal, stored)
                self.assertNotIn(personal, hr.LISTING_KEEP.values())
