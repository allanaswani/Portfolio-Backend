"""Where one person's card targets come from, line by line. Read-only.

    docker exec hf-backend python manage.py scorecard_targets JN3696

Prints the person's DMC roster row (every target_* column, as stored), then
each line of the live engine card: its annual, growth and YTD target, the
prior-year base, the source the target came from - or the reason there is
none. The workbook card fills a target the desk's Summary Allocation lacks
from exactly these engine lines, so a line with no target here is a line the
workbook card cannot score either.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show where one person's scorecard targets come from."

    def add_arguments(self, parser):
        parser.add_argument("sales_code")

    def handle(self, *args, **opts):
        from apps.staff_management import live_scorecard as ls

        code = opts["sales_code"].strip().upper()
        try:
            targets, table, columns = ls.roster_target_row(code)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            targets, table, columns = {}, f"(could not read: {exc})", set()
        self.stdout.write(f"DMC row: {table or '(none found)'}")
        for key in sorted(targets):
            if key.startswith("target"):
                self.stdout.write(f"  {key:<34} {targets[key]!r}")

        import datetime

        from django.db import connection, transaction

        from services import portfolio_service as svc

        last_year = datetime.date.today().year - 1
        self.stdout.write(f"\nBases on the customers allocated to {code} ({last_year}):")
        try:
            with transaction.atomic():
                book = svc.allocated_book_bases(code, last_year)
            self.stdout.write(f"  customers allocated            {book.get('customers')}")
            self.stdout.write(f"  December {last_year} loan book       {book.get('december_loan_book')}")
            for k, v in (book.get("problems") or {}).items():
                self.stdout.write(f"  problem ({k}): {v}")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"  could not read: {exc}")
        try:
            with transaction.atomic():
                value, problem = ls.last_year_income(code, last_year)
            self.stdout.write(f"  {last_year} income contribution     {value}  {problem or ''}")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"  {last_year} income: could not read: {exc}")
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("SELECT min(trx_date), max(trx_date), count(*) FROM revenue")
                self.stdout.write(f"  revenue table covers {cur.fetchone()}")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"  revenue table: {exc}")

        card = ls._engine_card(code)
        if not card.get("has_card"):
            self.stdout.write(f"No engine card: {card.get('detail') or card.get('reason')}")
            return
        self.stdout.write(f"\nEngine card: {card.get('staff', {}).get('title')} - "
                          f"{card.get('period', {}).get('label')}")
        for p in card.get("perspectives", []):
            for ln in p.get("lines", []):
                def num(v):
                    return "-" if v is None else (f"{v:,.2f}" if isinstance(v, (int, float)) else str(v))
                self.stdout.write(
                    f"  {str(ln.get('kpi_name'))[:34]:<34} annual {num(ln.get('annual_target')):>16}"
                    f"  growth {num(ln.get('growth_target')):>16}  prior {num(ln.get('prior_year')):>16}"
                    f"  ytd {num(ln.get('ytd_target')):>14}")
                why = ln.get("target_source") or ""
                if ln.get("pending"):
                    why += f" | pending: {ln.get('pending')}"
                if ln.get("diagnostic"):
                    why += f" | {ln.get('diagnostic')}"
                if why:
                    self.stdout.write(f"      {why[:300]}")
