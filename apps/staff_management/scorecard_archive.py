"""Every month's scorecards, kept as files outside the database, and sent to
each person once their month is complete.

Why files
─────────
A scorecard is somebody's performance record. It can decide a bonus, a
promotion or a dismissal, and it can be asked for in a dispute or in court
years later. The database is not a safe single home for that: an outage, a
lost server or a careless edit would take the evidence with it. So each month
every card is written to a folder on disk - by default the host's shared
``/data/apps/datascience/scorecard_archive``, mounted into the container -
alongside the reports the ETLs write:

    <archive>/<YYYY-MM>/<workbook>/<CODE> - <Name>.xlsx   the card as sent
    <archive>/<YYYY-MM>/<workbook>/<CODE> - <Name>.json   its exact figures
    <archive>/<YYYY-MM>/manifest.csv                       one row per file

Files are never overwritten. A card that changes after it was archived (a late
figure, a correction) is written beside the first as ``(v2 <date>)``, so the
folder shows what a person was shown and when. Each file's SHA-256 is in the
manifest, so a copy produced later can be proved to be the one archived, and
the files are made read-only.

When a card goes out - the timeline
───────────────────────────────────
A month's card is COMPLETE when every line has its figure (no line is still
waiting for data). The daily run (``manage.py archive_scorecards``) for the
month just closed does this:

* before ``SEND_FROM_DAY`` (the 5th): nothing - the month's data is still
  being loaded;
* from the 5th: every COMPLETE card is archived and e-mailed to its person
  (and their manager) - once; it is not sent again;
* on ``FINAL_DAY`` (the 10th): every card is archived as it stands, complete
  or not, and Administration is e-mailed the list of cards still incomplete
  and why, so nothing is left unaccounted for.

People can always see their card in the portal; the e-mail and the archive are
the record.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
import re

#: Day of the following month from which complete cards are sent.
SEND_FROM_DAY = int(os.environ.get("SCORECARD_SEND_FROM_DAY", "5"))
#: Day on which everything is archived and the incomplete list goes out.
FINAL_DAY = int(os.environ.get("SCORECARD_FINAL_DAY", "10"))
#: Marks the automatic sends in sc_scorecard_dispatches.
AUTO = "automatic (scorecard archive)"


def archive_dir():
    from django.conf import settings

    return (os.environ.get("SCORECARD_ARCHIVE_DIR")
            or getattr(settings, "SCORECARD_ARCHIVE_DIR", "")
            or os.path.join(str(settings.BASE_DIR), "scorecard_archive"))


def month_end(period):
    year, month = (int(x) for x in period.split("-"))
    first_next = datetime.date(year + (month == 12), month % 12 + 1, 1)
    return first_next - datetime.timedelta(days=1)


def closed_period(today=None):
    today = today or datetime.date.today()
    last = today.replace(day=1) - datetime.timedelta(days=1)
    return f"{last.year:04d}-{last.month:02d}"


def people():
    """Everybody with a card → [{book, code, name}], one row per sales code."""
    from .management.commands.scorecard_reach import workbook_people

    found, _missing = workbook_people()
    out = {}
    for p in found:
        code = (p.get("code") or "").strip().upper()
        if code and code not in out:
            out[code] = {"book": p.get("book") or "", "code": code,
                         "name": p.get("name") or ""}
    return list(out.values())


def card_for(code, period):
    """The card for ``period`` → (card, signoff). A signed card is its frozen
    copy - what the person signed is what is kept."""
    from .live_scorecard import build_card
    from .scorecard_automation.models import ScorecardSignoff

    signoff = ScorecardSignoff.objects.filter(sales_code=code, period=period).first()
    if signoff is not None and signoff.signed_at and signoff.card:
        return signoff.card, signoff
    return build_card(code, as_at=month_end(period)), signoff


def waiting_lines(card):
    """The card's lines still waiting for a figure → [measure]."""
    out = []
    for perspective in card.get("perspectives") or []:
        for line in perspective.get("lines") or []:
            if line.get("pending"):
                out.append(line.get("kpi_name") or line.get("measure")
                           or line.get("label") or "a line")
    return out


def is_complete(card):
    return bool(card.get("has_card")) and not waiting_lines(card)


def _safe(text):
    return re.sub(r'[\\/:*?"<>|]+', "-", str(text or "")).strip() or "unnamed"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def archive_card(period, person, card, signoff=None, now=None):
    """Write one card's files for ``period`` unless the same card is already
    there → {"file", "sha256", "written"} (written False when unchanged)."""
    from .scorecard_signoff import build_card_workbook

    now = now or datetime.datetime.now()
    folder = os.path.join(archive_dir(), period, _safe(person["book"] or "cards"))
    os.makedirs(folder, exist_ok=True)
    base = f"{_safe(person['code'])} - {_safe(person['name'])}"
    payload = json.dumps(card, sort_keys=True, default=str, indent=1).encode("utf-8")
    digest = _sha256(payload)

    # The same figures already archived (any version): nothing to write.
    for name in sorted(os.listdir(folder)):
        if name.startswith(base) and name.endswith(".json"):
            with open(os.path.join(folder, name), "rb") as f:
                if _sha256(f.read()) == digest:
                    return {"file": os.path.join(folder, name[:-5] + ".xlsx"),
                            "sha256": digest, "written": False}

    stem, version = base, 1
    while os.path.exists(os.path.join(folder, stem + ".json")):
        version += 1
        stem = f"{base} (v{version} {now:%Y-%m-%d})"
    xlsx = build_card_workbook(card, signoff).getvalue()
    paths = {".json": payload, ".xlsx": xlsx}
    for ext, data in paths.items():
        path = os.path.join(folder, stem + ext)
        with open(path, "xb") as f:      # x: never overwrite
            f.write(data)
        try:
            os.chmod(path, 0o444)
        except OSError:
            pass

    manifest = os.path.join(archive_dir(), period, "manifest.csv")
    new = not os.path.exists(manifest)
    with open(manifest, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["archived_at", "period", "workbook", "sales_code", "name",
                        "file", "xlsx_sha256", "json_sha256", "version", "signed_at",
                        "manager_signed_at", "score", "complete", "waiting_lines"])
        w.writerow([now.isoformat(timespec="seconds"), period, person["book"],
                    person["code"], person["name"], stem + ".xlsx", _sha256(xlsx),
                    digest, version,
                    getattr(signoff, "signed_at", "") or "",
                    getattr(signoff, "manager_signed_at", "") or "",
                    card.get("performance_score", ""), is_complete(card),
                    "; ".join(waiting_lines(card))])
    return {"file": os.path.join(folder, stem + ".xlsx"), "sha256": digest,
            "written": True}


def already_sent(code, period):
    from .scorecard_automation.models import ScScorecardDispatch

    return ScScorecardDispatch.objects.filter(
        sales_code__iexact=code, period=period, sent_by_name=AUTO).exists()


def run(period=None, today=None, send=True, final=None, out=print):
    """The daily job for ``period`` (default: the month just closed) →
    a summary dict. See the module note for the timeline."""
    from . import scorecard_email

    today = today or datetime.date.today()
    period = period or closed_period(today)
    after_month = today > month_end(period)
    if final is None:
        final = after_month and (today.day >= FINAL_DAY or
                                 today >= month_end(period) + datetime.timedelta(days=31))
    sending_open = after_month and (today.day >= SEND_FROM_DAY or final
                                    or today > month_end(period) + datetime.timedelta(days=31))
    summary = {"period": period, "archived": 0, "unchanged": 0, "sent": 0,
               "complete": 0, "incomplete": [], "failed": [], "final": final}
    if not sending_open:
        out(f"{period}: before day {SEND_FROM_DAY} of the next month - the month's "
            f"data is still being loaded; nothing archived or sent.")
        return summary

    for person in people():
        code = person["code"]
        try:
            card, signoff = card_for(code, period)
        except Exception as exc:  # noqa: BLE001 - one card must not stop the rest
            summary["failed"].append((code, person["name"], f"card could not be built: {exc}"))
            continue
        if not card.get("has_card"):
            continue
        complete = is_complete(card)
        if complete:
            summary["complete"] += 1
        else:
            summary["incomplete"].append((code, person["name"], "; ".join(waiting_lines(card))))
        if not (complete or final):
            continue
        try:
            done = archive_card(period, person, card, signoff)
        except Exception as exc:  # noqa: BLE001
            summary["failed"].append((code, person["name"], f"not archived: {exc}"))
            continue
        summary["archived" if done["written"] else "unchanged"] += 1
        if send and complete and not already_sent(code, period):
            try:
                scorecard_email.send_card(card, signoff, who=AUTO, period=period)
                summary["sent"] += 1
            except Exception as exc:  # noqa: BLE001 - e.g. no address on file
                summary["failed"].append((code, person["name"], f"not sent: {exc}"))

    out(f"{period}: {summary['archived']} card(s) archived, {summary['unchanged']} "
        f"already archived unchanged, {summary['sent']} sent; "
        f"{summary['complete']} complete, {len(summary['incomplete'])} incomplete, "
        f"{len(summary['failed'])} problem(s). Archive: {archive_dir()}")
    if final and send:
        notify_administration(summary, out)
    return summary


def notify_administration(summary, out=print):
    """On the final day: the cards still incomplete, and every problem."""
    from django.conf import settings
    from django.core.mail import EmailMessage

    to = [a.strip() for a in os.environ.get("SCORECARD_ADMIN_EMAILS", "").split(",") if a.strip()]
    if not to:
        out("SCORECARD_ADMIN_EMAILS is not set - the incomplete list was not e-mailed.")
        return
    lines = [f"Scorecards for {summary['period']} - final day.", "",
             f"Archived: {summary['archived']} new, {summary['unchanged']} unchanged. "
             f"Sent: {summary['sent']}. Complete: {summary['complete']}.", ""]
    if summary["incomplete"]:
        lines += [f"Still incomplete ({len(summary['incomplete'])}) - archived as they "
                  f"stand, NOT sent:"]
        lines += [f"  {c}  {n}: waiting for {w}" for c, n, w in summary["incomplete"]]
        lines.append("")
    if summary["failed"]:
        lines += [f"Problems ({len(summary['failed'])}):"]
        lines += [f"  {c}  {n}: {why}" for c, n, why in summary["failed"]]
        lines.append("")
    lines.append(f"Archive folder: {archive_dir()}/{summary['period']}")
    EmailMessage(subject=f"Scorecards {summary['period']}: final-day report",
                 body="\n".join(lines), from_email=settings.DEFAULT_FROM_EMAIL,
                 to=to).send(fail_silently=False)
    out(f"Final-day report e-mailed to {', '.join(to)}.")
