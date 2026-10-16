"""Sending a scorecard out by e-mail.

One button. The card goes to the person it is about and to the manager who
has to counter-sign it, with the read-only workbook attached - the same file
the download gives, laid out as the bank's own scorecard.

Where the addresses come from
─────────────────────────────
This was the open question, and the answer is that the two addresses live in
two different places:

* **the person's own** is on the HR roster, ``staff_employee_data.staff_email``,
  keyed on their sales code. The scorecard workbook's ``List`` sheet does NOT
  have it - the ``e-mail1`` column there is the LINE MANAGER's, which is why
  reading it as the person's would have sent every card to their boss and to
  nobody else;
* **the manager's** is the same column on the manager's OWN roster row, found
  by the name the card already carries in ``team_leader``.

Either can be missing, and a missing address is reported rather than worked
around: a card sent to a guessed address is worse than a card not sent.

Nothing is sent silently
────────────────────────
Every send is written to ``sc_scorecard_dispatches`` with who pressed the
button, when, and the exact addresses it went to. A scorecard is somebody's
performance record; where a copy of it went is part of that record.
"""

from __future__ import annotations

import datetime

#: Rendered into the covering note. Kept here rather than in a template so the
#: wording travels with the code that explains it.
BODY = """Dear {name},

Your performance scorecard for {period} is attached.

{state}

The attached copy is read-only. It is laid out as the scorecard you know, and
the figures on it are the ones the platform held when this was sent{frozen}.

Each line shows its year-to-date target beside the actual, the score, and the
weighted score. Where a line has no figure, it says why in the ACTUAL column
rather than showing a nought - a line nobody has a figure for is a different
thing from a line achieved at zero.

{closing}

HFCB Performance Analytics
"""


def _roster_email(name="", sales_code=""):
    """The HR roster's address for somebody → ``(address, how)``.

    By sales code where there is one, because that is exact. By name
    otherwise, through the same word-set comparison the rest of the platform
    uses, and only when exactly ONE roster row agrees - a scorecard sent to
    the wrong Joseph is not a near miss.
    """
    from .live_scorecard import name_tokens, names_agree
    from .models import StaffEmployeeData

    rows = StaffEmployeeData.objects.exclude(staff_email="").exclude(
        staff_email__isnull=True)

    code = (sales_code or "").strip()
    if code:
        row = rows.filter(sales_code__iexact=code).first()
        if row is not None:
            return (row.staff_email or "").strip(), "their sales code"

    tokens = name_tokens(name or "")
    if len(tokens) < 2:
        return "", ""
    longest = max(tokens, key=len)
    found = {
        (row.staff_email or "").strip()
        for row in rows.filter(staff_name__icontains=longest)
                       .only("staff_name", "staff_email")[:400]
        if names_agree(name, row.staff_name)
    }
    found.discard("")
    if len(found) == 1:
        return found.pop(), "their name on the HR roster"
    if len(found) > 1:
        return "", "more than one person on the roster has that name"
    return "", ""


def recipients_for(card):
    """Who this card should go to → ``(to, cc, problems)``.

    ``to`` is the person. ``cc`` is the manager who counter-signs. Both are
    lists so a caller can add to them, and ``problems`` names every address
    that could not be found, in words the person pressing the button can act
    on.
    """
    staff = (card.get("staff") or {})
    name = staff.get("name") or ""
    problems = []

    own = _roster_email(name=name, sales_code=staff.get("sales_code"))[0]
    if not own:
        problems.append(
            f"No e-mail address for {name or 'this person'} on the HR roster "
            f"(staff_employee_data). Their own address is the only one that "
            f"column holds for them - the scorecard workbook's e-mail column "
            f"is their manager's.")

    manager_name = staff.get("team_leader") or ""
    manager = ""
    if manager_name:
        manager, why = _roster_email(name=manager_name)
        if not manager:
            problems.append(
                f"{manager_name} is the manager named on this card, and "
                + (f"{why}, so there is no address to copy."
                   if why else
                   "the HR roster holds no e-mail address for them."))
    else:
        problems.append(
            "This card names no line manager, so there is nobody to copy. "
            "The manager comes off the roster row; see the note in "
            "scorecard_signoff on the two columns that hold it.")

    to = [own] if own else []
    cc = [manager] if manager and manager != own else []
    return to, cc, problems


def compose(card, signoff=None):
    """Subject and body for one card → ``(subject, body)``."""
    staff = card.get("staff") or {}
    period = (card.get("period") or {}).get("label") or ""
    name = (staff.get("name") or "").split()[0] if staff.get("name") else "all"
    signed = getattr(signoff, "signed_at", None)
    counter = getattr(signoff, "manager_signed_at", None)

    score = float(card.get("performance_score") or 0)
    state = (f"It scores {score * 100:.1f}% overall.")
    if signed and counter:
        countersigner = (getattr(signoff, "manager_signed_by_name", "")
                         or "your line manager")
        state += (f" You signed it on {signed:%d %b %Y} and "
                  f"{countersigner} counter-signed on {counter:%d %b %Y}, "
                  f"so this card is complete.")
        closing = "No action is needed; this copy is for your records."
    elif signed:
        state += (f" You signed it on {signed:%d %b %Y}. It is now with "
                  f"{staff.get('team_leader') or 'your line manager'} to "
                  f"counter-sign.")
        closing = ("Your line manager can counter-sign it in the portal under "
                   "My scorecard.")
    else:
        state += " It has not been signed yet."
        closing = ("You can review and sign it in the portal under My "
                   "scorecard. Signing fixes the figures as they stand, so "
                   "the card you sign is the card that is kept.")

    frozen = (f", frozen when you signed on {signed:%d %b %Y}" if signed
              else f" on {datetime.date.today():%d %b %Y}")

    subject = (f"HFCB scorecard - {staff.get('name') or ''} - {period}"
               f"{'' if signed else ' (unsigned)'}").strip()
    return subject, BODY.format(name=name, period=period, state=state,
                                frozen=frozen, closing=closing)


def send_card(card, signoff=None, extra_to=(), who="", request_user=None):
    """E-mail one card → the dispatch record.

    Raises ``ValueError`` with the reason when there is nobody to send it to.
    An address that cannot be found is never substituted for another.
    """
    from django.conf import settings
    from django.core.mail import EmailMessage

    from .scorecard_automation.models import ScScorecardDispatch
    from .scorecard_signoff import build_card_workbook, period_for

    staff = card.get("staff") or {}
    to, cc, problems = recipients_for(card)
    to = list(to) + [a.strip() for a in extra_to if a and a.strip()]
    # Somebody typing an address by hand answers the problem it was reported
    # for, so an address supplied here clears the person's own missing one.
    to = list(dict.fromkeys(to))

    if not to:
        raise ValueError(
            " ".join(problems) or "There is no address to send this card to.")

    subject, body = compose(card, signoff)
    message = EmailMessage(
        subject=subject, body=body,
        from_email=settings.DEFAULT_FROM_EMAIL, to=to, cc=cc)

    name = (staff.get("name") or staff.get("sales_code") or "scorecard")
    period = (card.get("period") or {}).get("label") or period_for(card)
    filename = (f"HFCB scorecard - {name} - {period}.xlsx"
                .replace("/", "-").replace("\\", "-"))
    message.attach(
        filename, build_card_workbook(card, signoff).getvalue(),
        "application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet")

    # fail_silently is OFF on purpose. A send that did not happen must not be
    # recorded as one, and the person pressing the button is the only one who
    # can do anything about a mail server that is refusing.
    message.send(fail_silently=False)

    return ScScorecardDispatch.objects.create(
        sales_code=staff.get("sales_code") or "",
        period=period_for(card),
        sent_to=", ".join(to), sent_cc=", ".join(cc),
        sent_by=request_user if getattr(request_user, "pk", None) else None,
        sent_by_name=who or "",
        was_signed=bool(getattr(signoff, "signed_at", None)),
        note="; ".join(problems),
    )
