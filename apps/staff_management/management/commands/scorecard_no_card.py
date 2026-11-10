"""Take somebody off the scorecards from a month on, or put them back.

    python manage.py scorecard_no_card --add JMA1138 --from 2026-10 --reason "CX Manager, Head Office"
    python manage.py scorecard_no_card --remove JMA1138
    python manage.py scorecard_no_card                       # list

Months before --from keep the card the desk sent; stored months from --from on
are removed here, and a later template load does not bring them back.
"""
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Keep people who left a scored role off the scorecards."

    def add_arguments(self, parser):
        parser.add_argument("--add")
        parser.add_argument("--remove")
        parser.add_argument("--from", dest="start", default="",
                            help="YYYY-MM, first month with no card; default: all")
        parser.add_argument("--reason", default="")

    def handle(self, *args, **opts):
        from apps.staff_management import workbook_cards as wc
        from apps.staff_management.models import BoScorecard

        entries = dict(wc.saved(wc.NO_CARD) or {})
        if opts["add"]:
            code = opts["add"].replace(" ", "").upper()
            start = opts["start"]
            if start and not (len(start) == 7 and start[4] == "-"):
                raise CommandError("--from is YYYY-MM")
            entries[code] = {"from": start, "reason": opts["reason"]}
            # Stored months from --from on are no card any more.
            gone = BoScorecard.objects.filter(sales_code__iexact=code)
            if start:
                y, m = (int(p) for p in start.split("-"))
                gone = [r for r in gone if (r.month.year, r.month.month) >= (y, m)]
            removed = 0
            for row in list(gone):
                row.delete()
                removed += 1
            self.stdout.write(f"{code}: no card from {start or 'now'}; "
                              f"{removed} stored month(s) removed")
        if opts["remove"]:
            code = opts["remove"].replace(" ", "").upper()
            entries.pop(code, None)
            self.stdout.write(f"{code}: back on the scorecards - reload the "
                              f"template or rebuild for their stored months")
        if opts["add"] or opts["remove"]:
            wc.save_file(wc.NO_CARD, entries, "scorecard_no_card", "command")
            cache.delete(wc.NO_CARD)
            cache.delete("workbook_roster_roles")
        for code, entry in sorted(entries.items()):
            self.stdout.write(f"  {code}  from {entry.get('from') or 'all'}  "
                              f"{entry.get('reason') or ''}")
        if not entries:
            self.stdout.write("  nobody is on the no-card list")
