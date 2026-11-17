"""Email for the design board.

Four rules, the same ones ``apps.service_desk.notifications`` settled on.

**Mail the person who is now waiting on something.** A designer hears when work
is allocated to them or comes back; a requester hears when there is something
to look at. That is the whole point — the board replaces nobody knowing.

**Never copy somebody on their own action.** An email telling you what you just
did teaches people to filter the sender, and then they miss the one that
mattered.

**Mail a person, not a department.** The raising *department* may approve a
brief (see ``rbac.can_judge``), but mailing everyone in Marketing on every
submission would be the fastest way to get this address blocked. The requester
is mailed; the marketing admins are the fallback when there is no requester to
reach.

**Never let mail break the work.** Every send is wrapped, and every send is
queued on ``transaction.on_commit``. Mail sent inside the transaction would
announce a submission a later error rolled back, and the designer would be told
their work was handed over when the database says it was not.
"""

import logging
from html import escape

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection

from .rbac import ADMIN_GROUP

log = logging.getLogger(__name__)

BOARD_NAME = "HFCB Marketing Briefs"
SUBJECT_PREFIX = "[HFCB Marketing]"

TEAL = "#1996A9"
INK = "#0B2D3D"
MUTED = "#6B8A96"
CORAL = "#C23530"


def send(to, subject, text_body, html_body=None):
    """Send one message. Returns how many addresses it went to; never raises."""
    addresses = sorted({str(a).strip() for a in (to or []) if a and "@" in str(a)})
    if not addresses:
        return 0
    try:
        message = EmailMultiAlternatives(
            subject=f"{SUBJECT_PREFIX} {subject}"[:250],
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=addresses,
            connection=get_connection(fail_silently=False),
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")
        message.send()
        return len(addresses)
    except Exception as exc:  # noqa: BLE001 — mail must never break the board
        log.warning("design board mail failed (%s): %s", subject, exc)
        return 0


# ── Who hears ────────────────────────────────────────────────────────────────

def _address(user, exclude=None):
    """One address, unless it is the person who just acted."""
    if user is None or not getattr(user, "email", ""):
        return []
    if exclude is not None and getattr(exclude, "id", None) == user.id:
        return []
    return [user.email]


def admin_addresses(exclude=None):
    """The marketing admins, by group membership.

    Superusers are deliberately absent: a superuser can *act* on any brief,
    which is what a superuser is, but mailing every superuser in the bank puts
    Marketing's queue in the inbox of people with nothing to do with it.
    """
    try:
        User = get_user_model()
        qs = User.objects.filter(
            is_active=True, groups__name=ADMIN_GROUP).exclude(email="")
        if exclude is not None and getattr(exclude, "id", None):
            qs = qs.exclude(pk=exclude.id)
        return list(qs.values_list("email", flat=True).distinct())
    except Exception:  # noqa: BLE001 — never break a transition over a lookup
        return []


def _requester_addresses(brief, exclude=None):
    """The person who asked - the named requester when the brief was captured
    for somebody, else whoever raised it - or the admins when there is nobody
    to reach."""
    named = (brief.requester_email or "").strip()
    if named and "@" in named:
        if exclude is None or (getattr(exclude, "email", "") or "").strip().lower() \
                != named.lower():
            return [named]
        return []
    direct = _address(brief.raised_by, exclude)
    return direct or admin_addresses(exclude)


def _ticket_addresses(brief):
    """Where a ticket update goes: the requester, ALWAYS - including when they
    raised it themselves. A receipt is the one mail that is about your own
    action on purpose: it is the proof the request landed and the reference
    to quote (Marketing asked for exactly this, 17 Nov 2026)."""
    named = (brief.requester_email or "").strip()
    if named and "@" in named:
        return [named]
    return _address(brief.raised_by)


def _link(brief):
    try:
        from core.email_links import primary_url

        base = primary_url()
    except Exception:  # noqa: BLE001
        base = ""
    return f"{base.rstrip('/')}/design-briefs/{brief.reference}" if base else ""


# ── The messages ─────────────────────────────────────────────────────────────

def _handler(brief):
    if brief.assigned_designer:
        return (brief.assigned_designer.get_full_name()
                or brief.assigned_designer.username)
    return "Marketing team - a designer is being assigned"


def _facts(brief):
    rows = [
        ("Reference", brief.reference),
        ("Item", f"{brief.design_item} ({brief.get_item_type_display()})"),
        ("Status", brief.get_status_display()),
        ("Handled by", _handler(brief)),
        ("Priority", brief.get_priority_display()),
        ("Needed by", brief.release_date.strftime("%d %b %Y")
                      if brief.release_date else "No date set"),
        ("Requested by", f"{brief.requester_display or '—'} ({brief.department})"),
        ("For", brief.addressed_to),
    ]
    if brief.rework_count:
        rows.append(("Sent back", f"{brief.rework_count} time(s) so far"))
    link = _link(brief)
    if link:
        rows.append(("Track it", link))
    return rows


def _text(brief, lead, note=None):
    lines = [lead, ""]
    lines += [f"{k}: {v}" for k, v in _facts(brief)]
    if note:
        lines += ["", note]
    lines += ["", f"Quote {brief.reference} in any reply.", f"— {BOARD_NAME}"]
    return "\n".join(lines)


def _html(brief, lead, note=None, accent=TEAL):
    def cell(k, v):
        if k == "Track it":
            return (f'<a href="{escape(str(v))}" style="color:{TEAL}">'
                    f"Open {escape(brief.reference)}</a>")
        return escape(str(v))

    rows = "".join(
        f'<tr><td style="padding:4px 14px 4px 0;color:{MUTED};font-size:13px;'
        f'white-space:nowrap">{escape(k)}</td>'
        f'<td style="padding:4px 0;color:{INK};font-size:13px;font-weight:600">'
        f"{cell(k, v)}</td></tr>"
        for k, v in _facts(brief)
    )
    extra = ""
    if note:
        extra = (
            f'<div style="margin-top:16px;padding:12px 14px;border-radius:10px;'
            f'background:#F6FAFB;border-left:3px solid {accent};color:{INK};'
            f'font-size:13.5px;white-space:pre-wrap">{escape(note)}</div>'
        )
    return (
        f'<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;'
        f'max-width:560px">'
        f'<div style="height:4px;background:linear-gradient(90deg,{INK},{TEAL});'
        f'border-radius:4px"></div>'
        f'<p style="color:{INK};font-size:15px;font-weight:600;margin:18px 0 14px">'
        f"{escape(lead)}</p>"
        f'<table cellpadding="0" cellspacing="0">{rows}</table>'
        f"{extra}"
        f'<p style="color:{MUTED};font-size:11.5px;margin-top:22px">'
        f"{escape(BOARD_NAME)}</p></div>"
    )


def _one(to, subject, brief, lead, note=None, accent=TEAL):
    return send(to, subject, _text(brief, lead, note),
                _html(brief, lead, note, accent))


def received(brief, actor=None):
    """The ticket receipt: the request is in, here is its reference, here is
    who is handling it. Sent on every new brief."""
    return _one(
        _ticket_addresses(brief),
        f"{brief.reference} received: {brief.design_item}",
        brief,
        "Your request has been received by Marketing. The details are below; "
        "you will be e-mailed as it moves - when a designer takes it on and "
        "when it is ready for you to review.")


def assigned(brief, actor=None):
    """The designer has new work - and the requester hears who has it."""
    who = brief.assigned_designer
    if who is None:
        return 0
    sent = _one(
        _address(who, actor),
        f"You have been given a brief: {brief.design_item}",
        brief,
        "A marketing brief has been allocated to you.")
    sent += _one(
        [a for a in _ticket_addresses(brief)
         if a.lower() != (getattr(who, "email", "") or "").lower()],
        f"{brief.reference}: now handled by {_handler(brief)}",
        brief,
        f"{_handler(brief)} is now handling your request.")
    return sent


def moved_up(brief, actor=None, reason=""):
    """Somebody else put this at the top of a designer's queue: the designer
    needs to know what to pick up next, and why."""
    who = brief.assigned_designer
    if who is None:
        return 0
    return _one(
        _address(who, actor),
        f"Do this next: {brief.design_item}",
        brief,
        "This brief has been moved to the top of your queue.",
        note=(reason or "").strip() or None,
        accent=CORAL)


def submitted(brief, actor=None):
    """There is something for the requester to look at."""
    return _one(
        _requester_addresses(brief, actor),
        f"Ready for your review: {brief.design_item}",
        brief,
        "The designer has submitted this for review. Approve it, or send it "
        "back with what needs changing.")


def reworked(brief, actor=None, reason=""):
    """It came back. The reason IS the message — without it the mail is useless."""
    who = brief.assigned_designer
    if who is None:
        return 0
    reason = (reason or brief.last_rework_reason or "").strip()
    return _one(
        _address(who, actor),
        f"Sent back for rework: {brief.design_item}",
        brief,
        "This has been sent back. What needs changing:\n\n" + reason,
        accent=CORAL)


def approved(brief, actor=None):
    """Somebody's work was accepted, and they should hear so."""
    who = brief.assigned_designer
    if who is None:
        return 0
    return _one(
        _address(who, actor),
        f"Approved: {brief.design_item}",
        brief,
        "This has been approved and the brief is now closed.",
        # Only if somebody wrote one; the lead above always stands on its own.
        note=brief.closing_note or None,
        accent=TEAL)


def cancelled(brief, actor=None, reason=""):
    """Stop work. The designer is the one who needs to know immediately."""
    who = brief.assigned_designer
    if who is None:
        return 0
    return _one(
        _address(who, actor),
        f"Cancelled: {brief.design_item}",
        brief,
        f"This brief has been cancelled. Stop work on it.\n\n{reason}".strip(),
        accent=MUTED)
