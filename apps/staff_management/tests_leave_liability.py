"""Aruti's Leave Liability Report (.xlsb) loads into the leave table."""
from unittest import mock

from django.test import SimpleTestCase


class _Cell:
    def __init__(self, v):
        self.v = v


class _Sheet:
    def __init__(self, grid):
        self.grid = grid

    def rows(self):
        return [[_Cell(v) for v in row] for row in self.grid]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Book:
    sheets = ["Leave_Liability_Report", "Liability"]

    def __init__(self, grid):
        self.grid = grid

    def get_sheet(self, name):
        return _Sheet(self.grid)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


GRID = [
    ["Printed By :", "x", "HFCB"],
    ["Date :", "12-Oct-2026 11:00:03 AM", "Leave Liability Report"],
    [""], ["Yearly Leave Liability Days: 3"], [" Order By :  Employee ID"],
    ["", "", "", "", None, None, None, "Annual Leave Accrued",
     "Annual Leave Consumed", "Annual Leave Balance", "Sick Leave Accrued",
     "Sick Leave Consumed", "Sick Leave Balance"],
    ["Employee ID", "Staff Name", "Sub Department", "Hire Date", "Division",
     "Grade", "Salary", "Annual Leave Days", "Annual Leave Days",
     "Annual Leave Days", "Sick Leave Days", "Sick Leave Days", "Sick Leave Days"],
    ["3789", "Felix Saigon", "Komarock Branch", "04/12/2023", None, None, None,
     28.0, 16.0, 12.0, 30.0, 0.0, 30.0],
]


class LeaveLiabilityTests(SimpleTestCase):
    def test_it_reads_annual_leave_by_pf(self):
        import datetime

        from . import hr_reports as hr

        with mock.patch("pyxlsb.open_workbook", return_value=_Book(GRID)):
            as_of, rows, report = hr._read_liability("x.xlsb")
        self.assertEqual(as_of, datetime.date(2026, 10, 12))
        annual = next(r for r in rows if r["leave_code"] == "AL")
        self.assertEqual((annual["pf_number"], annual["accrued"], annual["issued"],
                          annual["balance"]), (3789, 28.0, 16.0, 12.0))
        self.assertEqual(report["balance_does_not_add_up"], 0)
        self.assertEqual(report["by_leave_type"], {"AL": 1, "SL": 1})
