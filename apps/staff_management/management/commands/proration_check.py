"""Did an administrator's proration reach one person's card for a month?

    python manage.py proration_check EK1234 --month 2026-10
    python manage.py proration_check "Elijah Kilonzi" --month 2026-10

Prints, so the answer is a fact and not a guess:
  * the proration entries saved for the person;
  * each workbook card they hold, the proration columns its List has and the
    ones the card's own formulas READ (an entry in a column the card does not
    read changes nothing - the desk's formula decides, not us);
  * the month's card score and every line's YTD target WITH the entries and
    WITHOUT them, so any difference is on the screen;
  * whether the month is signed (a signed card is the frozen copy: proration
    entered later cannot change it);
  * the month's archived files and the e-mails sent for it.
It writes nothing.
"""
import calendar
import datetime
import os
from unittest import mock

from django.core.management.base import BaseCommand, CommandError


def _lines(card):
    return [(ln.get("kpi_name") or ln.get("measure") or "?", ln.get("ytd_target"))
            for p in card.get("perspectives") or [] for ln in p.get("lines") or []]


def _pct(v):
    return "-" if v is None else f"{float(v) * 100:.2f}%"


class Command(BaseCommand):
    help = "Show whether a person's proration changes their card for a month."

    def add_arguments(self, parser):
        parser.add_argument("who", help="sales code, or the person's name")
        parser.add_argument("--month", required=True, help="YYYY-MM")

    def handle(self, *args, **opts):
        from django.core.cache import cache

        from apps.staff_management import workbook_cards as wc
        from apps.staff_management import scorecard_archive as sa
        from apps.staff_management.live_scorecard import build_card
        from apps.staff_management.management.commands.accounts_opened_compare import (
            Command as Compare)
        from apps.staff_management.scorecard_automation.models import (
            ScorecardSignoff, ScScorecardDispatch)
        from apps.staff_management.workbook_views import _proration_effect

        code, name = Compare()._code(opts["who"])
        try:
            y, m = (int(x) for x in opts["month"].split("-"))
            as_at = datetime.date(y, m, calendar.monthrange(y, m)[1])
        except (ValueError, TypeError) as exc:
            raise CommandError("--month is YYYY-MM") from exc
        period = f"{y:04d}-{m:02d}"
        w = self.stdout.write
        w(f"{name}  ({code})   card for {period}")

        cache.delete(wc.PRORATION)
        entries = wc.proration().get(code) or []
        w(f"\nPRORATION ENTRIES: {len(entries)}")
        for e in entries:
            w(f"  {e.get('reason')}  from {e.get('from')}  to {e.get('to') or '-'}  "
              f"(months out by {period}: {wc.excluded_months(e, y, m)})  "
              f"by {e.get('by')} at {e.get('at')}")

        w("\nCARDS HELD AND WHAT THEIR FORMULAS READ")
        effect = _proration_effect(code)
        if not effect:
            w("  on no loaded workbook's List")
        for c in effect:
            w(f"  {c['book']}: {c['card']} (role {c['role']})")
            w(f"    List has: {', '.join(c['columns_on_list']) or 'none'}")
            w(f"    card reads: {', '.join(c['columns_the_card_reads']) or 'none'}")
            for e in entries:
                col = wc.PRORATION_REASONS.get(e.get("reason"), (None,))[0]
                if col and col not in c["columns_the_card_reads"]:
                    w(self.style.WARNING(
                        f"    ! the {e.get('reason')} entry fills {col}, which this card "
                        f"does not read: it changes nothing on this card"))

        signoff = ScorecardSignoff.objects.filter(sales_code__iexact=code, period=period).first()
        signed = bool(signoff and signoff.signed_at and signoff.card)
        w(f"\nSIGNED FOR {period}: "
          + (f"YES at {signoff.signed_at} - the frozen copy is the card; later "
             f"proration cannot change it" if signed else "no"))

        with_p = build_card(code, as_at=as_at)
        cache.delete(wc.PRORATION)
        with mock.patch.object(wc, "proration", lambda: {}):
            without = build_card(code, as_at=as_at)
        cache.delete(wc.PRORATION)
        if not with_p.get("has_card"):
            w(f"\nNO CARD: {with_p.get('reason')}: {with_p.get('detail')}")
            return
        w(f"\nLIVE CARD {period}: score with entries {_pct(with_p.get('performance_score'))}"
          f" | without {_pct(without.get('performance_score'))}")
        changed = 0
        for (label, t1), (_, t0) in zip(_lines(with_p), _lines(without)):
            mark = "" if t1 == t0 else "   <- prorated"
            changed += bool(mark)
            w(f"  {label[:44]:<46} ytd target {t1!s:>18} | without {t0!s:>18}{mark}")
        w(f"  {changed} line(s) changed by the proration")
        if signed:
            w(f"  signed copy score: {_pct(signoff.card.get('performance_score'))}")

        folder = os.path.join(sa.archive_dir(), period)
        files = []
        if os.path.isdir(folder):
            for root, _dirs, names in os.walk(folder):
                files += [os.path.join(os.path.relpath(root, folder), n) for n in names
                          if n.upper().startswith(code + " ") and n.endswith(".xlsx")]
        w(f"\nARCHIVED FILES FOR {period}: {len(files)}")
        for f in sorted(files):
            w(f"  {f}")
        sent = ScScorecardDispatch.objects.filter(sales_code__iexact=code, period=period)
        w(f"E-MAILS SENT FOR {period}: {sent.count()}")
        for d in sent.order_by("sent_at"):
            w(f"  {d.sent_at:%Y-%m-%d %H:%M}  by {d.sent_by_name}")
