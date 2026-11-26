"""Why a month's archive holds several versions of one person's card.

    python manage.py archive_versions --period 2026-10
    python manage.py archive_versions --period 2026-10 --code BCK3783

A card is archived again (never overwritten) whenever its figures differ
from every copy already there. This compares each version with the one
before it and counts WHAT changed: the score, which lines' actuals or
targets, or only fields that are not figures. Codes only, no names.
Writes nothing.
"""
import collections
import json
import os

from django.core.management.base import BaseCommand


def _lines(card):
    out = {}
    for p in card.get("perspectives") or []:
        for ln in p.get("lines") or []:
            key = ln.get("kpi_code") or ln.get("kpi_name") or ln.get("measure") or "?"
            out[key] = ln
    return out


def _diff(a, b):
    """Changes from a to b → list of labels."""
    found = []
    if a.get("performance_score") != b.get("performance_score"):
        found.append("score")
    la, lb = _lines(a), _lines(b)
    for key in sorted(set(la) | set(lb)):
        x, y = la.get(key) or {}, lb.get(key) or {}
        for field in ("ytd_actual", "ytd_target", "annual_target", "score", "pending"):
            if x.get(field) != y.get(field):
                found.append(f"line {key}: {field}")
    top = {k for k in set(a) | set(b) if k != "perspectives" and a.get(k) != b.get(k)}
    found += [f"field {k}" for k in sorted(top - {"performance_score"})]
    return found


class Command(BaseCommand):
    help = "Explain the versions in one month's scorecard archive."

    def add_arguments(self, parser):
        parser.add_argument("--period", required=True, help="YYYY-MM")
        parser.add_argument("--code", default="", help="one sales code, printed in full")

    def handle(self, *args, **opts):
        from apps.staff_management import scorecard_archive as sa

        root = os.path.join(sa.archive_dir(), opts["period"])
        if not os.path.isdir(root):
            self.stdout.write(f"nothing archived for {opts['period']}")
            return
        only = opts["code"].strip().upper()
        people = per_book = 0
        hist = collections.Counter()
        what = collections.Counter()
        score_moves = no_score_moves = 0
        for book in sorted(os.listdir(root)):
            sub = os.path.join(root, book)
            if not os.path.isdir(sub):
                continue
            versions = collections.defaultdict(list)
            for name in os.listdir(sub):
                if name.endswith(".json"):
                    stem, n = sa.card_stem(name)
                    versions[stem].append((n, name))
            per_book = 0
            for stem, files in sorted(versions.items()):
                code = stem.split(" - ")[0].strip().upper()
                if only and code != only:
                    continue
                people += 1
                per_book += 1
                hist[len(files)] += 1
                files.sort()
                cards = []
                for n, name in files:
                    with open(os.path.join(sub, name), encoding="utf-8") as f:
                        cards.append((n, os.path.getmtime(os.path.join(sub, name)), json.load(f)))
                for (n0, _t0, c0), (n1, t1, c1) in zip(cards, cards[1:]):
                    changes = _diff(c0, c1)
                    if "score" in changes:
                        score_moves += 1
                    else:
                        no_score_moves += 1
                    for c in changes:
                        what[c if c.startswith(("score", "field")) else
                             "line " + c.split(": ", 1)[1]] += 1
                    if only:
                        import datetime
                        self.stdout.write(
                            f"\n{code} v{n0} -> v{n1} "
                            f"({datetime.datetime.fromtimestamp(t1):%Y-%m-%d %H:%M}): "
                            f"score {c0.get('performance_score')} -> {c1.get('performance_score')}")
                        for c in changes:
                            self.stdout.write(f"    {c}")
            if not only:
                self.stdout.write(f"{book}: {per_book} people")
        self.stdout.write(f"\n{people} people; versions per person: "
                          + ", ".join(f"{k} version(s): {v}" for k, v in sorted(hist.items())))
        self.stdout.write(f"re-archives that moved the score: {score_moves}; "
                          f"that did not: {no_score_moves}")
        self.stdout.write("what changed, most often first:")
        for label, count in what.most_common(20):
            self.stdout.write(f"  {count:6}  {label}")
