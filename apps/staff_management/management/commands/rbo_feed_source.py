"""Which reader each Retail Back Office template sheet uses - a setting.

    python manage.py rbo_feed_source                        # list
    python manage.py rbo_feed_source New_Sheet engine:training_hours
    python manage.py rbo_feed_source New_Sheet "iapply:category:trade"
    python manage.py rbo_feed_source New_Sheet --clear      # back to the default
    python manage.py rbo_feed_source Old_Sheet --off        # the desk's figure only

A card line names its template sheet in column K. When the desk adds or
renames one, map it here; no code changes. Run prove_rbo_feeds after.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Show or set which reader a retail back office template sheet uses."

    def add_arguments(self, parser):
        parser.add_argument("sheet", nargs="?")
        parser.add_argument("reader", nargs="?")
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--off", action="store_true")

    def handle(self, *args, **opts):
        import datetime

        from apps.staff_management import rbo_live_feeds as rlf
        from apps.staff_management import workbook_cards as wc

        mine = dict(wc.saved(rlf.SOURCES_KIND) or {})
        sheet = (opts.get("sheet") or "").strip()
        if sheet:
            if opts.get("clear"):
                mine.pop(sheet, None)
            elif opts.get("off"):
                mine[sheet] = ""
            elif opts.get("reader"):
                if not rlf.valid_reader(opts["reader"]):
                    raise CommandError(f"{opts['reader']!r} is not a reader. Readers: "
                                       + ", ".join(rlf.READERS))
                mine[sheet] = opts["reader"]
            else:
                raise CommandError("Give a reader, --clear or --off.")
            wc.save_file(rlf.SOURCES_KIND, mine, loaded_by="rbo_feed_source")
            self.stdout.write(f"{sheet}: {rlf.reader_of(sheet) or 'the desk figure only'}")
            return

        w = self.stdout.write
        w("Readers:")
        for key, words in rlf.READERS.items():
            w(f"  {key:<32} {words}")
        # The sheets the loaded workbook's cards name, mapped or not.
        spec = wc.SPECS[wc.RETAIL_BO]
        book = wc.saved(spec.files[0], datetime.date.today().year)
        named = set()
        for card in (book or {}).get("cards", {}).values():
            for key, tokens in card["f"].items():
                r, c = (int(x) for x in key.split(","))
                if c == spec.cols["actual"] and any(t[0] == "f" and t[1] == "INDIRECT"
                                                    for t in tokens):
                    feed = wc._txt(wc._at(card["grid"], r, spec.cols["feed"]))
                    if feed:
                        named.add(feed)
        w("\nTemplate sheets:")
        for feed in sorted(named | set(rlf.sources())):
            reader = rlf.reader_of(feed)
            where = "set here" if feed in mine else "default"
            used = "" if feed in named else "   (no card names it)"
            w(f"  {feed:<28} {reader or 'NOT MAPPED - the desk figure only':<40} {where}{used}")
        m = rlf.tat_mapping()
        w(f"\nTAT mapping: {len(m['categories'])} product codes; "
          f"{m['split']['category']} split at {m['split']['at']:,.0f}")
