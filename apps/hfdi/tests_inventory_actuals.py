"""This year's HFCB-Properties actuals from hfdi_projects_inventory_sales_data,
counted as the bank's weekly report counts them (11 Nov 2026: the YTD slide
showed 0 for every project because hfdi_crm_sales_data is empty)."""
import datetime
from decimal import Decimal

from django.db import connection
from django.test import TestCase

from . import services
from .models import CrmProject, HfdiTargets

TODAY = datetime.date.today()
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class InventoryActualsTests(TestCase):
    def setUp(self):
        cols = ", ".join(f"{m}_paid_amount numeric" for m in MONTHS)
        with connection.cursor() as cur:
            cur.execute(f"""CREATE TABLE IF NOT EXISTS hfdi_projects_inventory_sales_data (
                project_name varchar(200), unit_name varchar(200), sale_month date,
                perc_paid double precision, {cols})""")
            this_month = f"{MONTHS[TODAY.month - 1]}_paid_amount"
            rows = [
                # sold this year, paid this month
                ("Barista Gardens", "A1", TODAY.replace(day=1), 0.4, 100),
                # sold this year, perc_paid 0 still counts (the report's >= 0)
                ("barista gardens ", "A2", TODAY.replace(day=1), 0.0, 50),
                # sold last year: a collection, not a sale
                ("Barista Gardens", "A3", datetime.date(TODAY.year - 1, 6, 1), 0.9, 25),
                # never sold (perc_paid NULL): not a sale
                ("Barista Gardens", "A4", None, None, 0),
            ]
            for name, unit, sale, perc, paid in rows:
                cur.execute(f"""INSERT INTO hfdi_projects_inventory_sales_data
                    (project_name, unit_name, sale_month, perc_paid, {this_month})
                    VALUES (%s, %s, %s, %s, %s)""", [name, unit, sale, perc, paid])
        CrmProject.objects.create(project_id=6, project_name="Barista Gardens")
        HfdiTargets.objects.create(
            project_id=6, pm="PM", rm="RM", month=str(TODAY.replace(day=1)),
            target_start_date=str(TODAY.replace(month=1, day=1)),
            target_sales_end_date=str(datetime.date(TODAY.year, 12, 31)),
            target_collections_end_date=str(datetime.date(TODAY.year, 12, 31)),
            volume=10, value=Decimal("200"), income=Decimal("50"),
            collections_value=Decimal("150"))

    def test_the_weekly_reports_rules(self):
        self.assertEqual(services._inventory_ytd(TODAY)["BARISTA GARDENS"], (2, 175.0))

    def test_the_per_project_row_carries_them(self):
        row = next(r for r in services.revenue_point_ytd_by_project()
                   if r["project_name"] == "Barista Gardens")
        self.assertEqual((row["actual_ytd_volume"], row["actual_ytd_value"]), (2, 175.0))
        self.assertEqual(row["actuals_source"], "hfdi_projects_inventory_sales_data")
        self.assertEqual(row["volume_target"], 10)

    def test_the_summary_adds_the_target_projects(self):
        summary = services.revenue_point_ytd()[0]
        self.assertEqual((summary["actual_ytd_volume"], summary["actual_ytd_value"]), (2, 175.0))

    def test_the_months_of_this_year(self):
        months = services.inventory_monthly_current_year(TODAY)
        self.assertEqual(len(months), TODAY.month)
        this = months[-1]
        self.assertEqual((this["volume_actual"], this["value_actual"]), (2, 175.0))
        self.assertIsNone(this["income_actual"])


class InventoryMissingTests(TestCase):
    def test_no_table_reads_as_nothing_rather_than_failing(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS hfdi_projects_inventory_sales_data")
        self.assertIsNone(services._inventory_ytd())
        self.assertEqual(services.inventory_monthly_current_year(), [])
        self.assertIsInstance(services.revenue_point_ytd_by_project(), list)
