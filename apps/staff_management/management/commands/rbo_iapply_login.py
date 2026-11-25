"""Confirm a Retail Back Office analyst's iApply sign-in.

    python manage.py rbo_iapply_login                    # list who has which
    python manage.py rbo_iapply_login JGC2024 JCHEGE     # set
    python manage.py rbo_iapply_login JGC2024 --clear    # back to the guess

iApply records the SIGN-IN (ALIDEDE, ECHEGE), not the name. The card guesses
it from the name (an initial and a name) only where exactly one sign-in fits;
this sets it where the guess cannot.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Show or set the retail back office analysts' iApply sign-ins."

    def add_arguments(self, parser):
        parser.add_argument("code", nargs="?")
        parser.add_argument("login", nargs="?")
        parser.add_argument("--clear", action="store_true")

    def handle(self, *args, **opts):
        from apps.staff_management import rbo_live_feeds as rlf
        from apps.staff_management import workbook_cards as wc

        fixed = dict(rlf.confirmed_logins())
        code = (opts.get("code") or "").strip().upper()
        if code and (opts.get("login") or opts.get("clear")):
            if opts.get("clear"):
                fixed.pop(code, None)
            else:
                fixed[code] = opts["login"].strip().upper()
            wc.save_file(rlf.LOGINS_KIND, fixed, loaded_by="rbo_iapply_login")
            self.stdout.write(f"{code}: {fixed.get(code, 'cleared - the guess applies')}")
            return
        if code:
            raise CommandError("Give a sign-in to set, or --clear.")

        spec = wc.SPECS[wc.RETAIL_BO]
        year = datetime.date.today().year
        book = wc.saved(spec.files[0], year)
        if book is None:
            raise CommandError("Load the retail back office scorecards workbook first.")
        every = {}
        for m in range(1, datetime.date.today().month + 1):
            every.update(rlf.iapply_users(year, m, wait=True) or {})
        for holder in wc.holders(book, keep_off=True):
            login, how = rlf.login_for(holder.sales_code, holder.name, every)
            surname = holder.name.split()[-1].upper()[:5]
            like = sorted(u for u in every if surname in u)[:6]
            self.stdout.write(f"{holder.sales_code:<9} {holder.name:<22} "
                              f"{login or '-':<12} {how}"
                              + (f"   [iApply sign-ins like the surname: {', '.join(like)}]"
                                 if not login and like else ""))
