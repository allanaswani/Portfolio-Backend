"""Read every whole-table scorecard feed now, keep it, and say what failed.

    python manage.py warm_scorecard_feeds                 # this month and last
    python manage.py warm_scorecard_feeds --month 2026-10

Cards read these feeds from what is kept (see feed_cache), so a card never
waits and never shows "being read" once a feed has been read once. Run from
cron so the kept figures stay current; a failure prints the error and the
command exits 1.
"""
import calendar
import datetime
import time

from django.core.management.base import BaseCommand


def _month_end(year, month):
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


class Command(BaseCommand):
    help = "Read and keep the scorecard's whole-table feeds; print any failure."

    def add_arguments(self, parser):
        parser.add_argument("--month", action="append", default=[],
                            help="YYYY-MM; repeatable. Default: this month and last.")

    def handle(self, *args, **opts):
        from apps.staff_management import (feed_cache, loan_tat_seller,
                                           rm_definitions,
                                           weighted_sales_drawdowns as wsd,
                                           weighted_sales_new_customers as wnc)

        today = datetime.date.today()
        months = []
        for text in opts["month"]:
            y, m = (int(p) for p in text.split("-"))
            months.append((y, m))
        if not months:
            last = today.replace(day=1) - datetime.timedelta(days=1)
            months = [(last.year, last.month), (today.year, today.month)]

        failed = 0
        chosen = rm_definitions.chosen()
        for year, month in months:
            end = min(_month_end(year, month), today)
            feeds = [
                ("New Customers", lambda: wnc.new_customers_by_seller(end)),
                ("New Customers by branch", lambda: wnc.new_customers_by_branch(year, month)),
                ("Focus accounts (CASA)", lambda: wnc.focus_accounts_by_seller(end)),
                ("Drawdowns", lambda: wsd.net_drawdowns_by_seller(end)),
                ("TAT Loan", lambda: loan_tat_seller.seller_month_tat(year, month)),
            ]
            for sheet in chosen:
                if sheet in rm_definitions.CANDIDATES:
                    feeds.append((f"{sheet} (chosen definition)",
                                  lambda s=sheet: rm_definitions.value(s, "", end)))
            self.stdout.write(f"{year}-{month:02d}")
            for name, read in feeds:
                began = time.monotonic()
                try:
                    with feed_cache.fresh():
                        found = read()
                except Exception as exc:  # noqa: BLE001 - reported, the run goes on
                    failed += 1
                    self.stdout.write(f"  FAILED  {name}: {type(exc).__name__}: {exc}")
                    continue
                size = len(found) if hasattr(found, "__len__") else "-"
                self.stdout.write(f"  ok      {name}: {size} rows, "
                                  f"{time.monotonic() - began:.0f}s")
        if failed:
            self.stdout.write(f"{failed} feed(s) failed")
            raise SystemExit(1)
        self.stdout.write("all feeds read and kept")
