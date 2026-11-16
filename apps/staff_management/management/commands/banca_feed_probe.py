"""Prove the Banca DSR live readers against a month the desk filled.

    docker exec hf-backend python manage.py banca_feed_probe --month 2026-10
    docker exec hf-backend python manage.py banca_feed_probe --month 2026-10 --who DSR476

For each insurance-template sheet the insurance report fills, the reader's
figure for every Banca DSR beside the desk's (the stored card of that month).
A sheet reads live on the cards once 70% of the DSRs agree; the result is
stored, and re-running replaces it. See apps/staff_management/banca_live_feeds.py.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Prove the Banca DSR live readers against the desk's figures."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="YYYY-MM the desk filled")
        parser.add_argument("--who", help="one DSR's code or name: show every sheet")
        parser.add_argument("--card", help="one DSR's code: show today's live card, "
                                           "line by line, instead of probing")

    def handle(self, *args, **o):
        from apps.staff_management import banca_live_feeds

        if o["card"]:
            from apps.staff_management.live_scorecard import build_card

            card = build_card(o["card"].strip().upper())
            w = self.stdout.write
            w(f"{card.get('staff', {}).get('name', '')} {card.get('period', {}).get('label', '')}"
              f" - live: {card.get('live')} - score {card.get('performance_score')}")
            w(card.get("how_scored", "") or card.get("detail", ""))
            for p in card.get("perspectives", []):
                for ln in p["lines"]:
                    w(f"  {ln['kpi_name'][:55]:55} actual {ln['ytd_actual']!s:>14}  "
                      f"target {ln['ytd_target']!s:>14}  {ln['as_at']}")
            return
        if not o["month"]:
            raise CommandError("Give --month YYYY-MM (or --card CODE).")
        try:
            when = datetime.datetime.strptime(o["month"], "%Y-%m")
        except ValueError:
            raise CommandError(f"{o['month']!r} is not YYYY-MM")
        banca_live_feeds.probe(when.year, when.month, out=self.stdout.write, who=o["who"])
