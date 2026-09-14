"""Email for the service desk.

Three rules shape all of it.

**Mail the person who is waiting.** A requester hears when their query is
received, answered, resolved and closed — that is the whole point, since the
complaint was never knowing. Nobody is copied on their own action: an email
telling you what you just did teaches people to filter the sender.

**Mail the team, not everybody who could.** The desk team is group membership,
explicitly. Superusers can *act* on any ticket — that is what a superuser is —
but they are not on the desk, and mailing every superuser in the bank puts the
queue in the inbox of people who have nothing to do with it.

**Never let mail break the work.** Every send is wrapped. A ticket saved but
whose confirmation bounced is a ticket that exists; an exception thrown out of
``resolve()`` because Office365 was slow would roll the resolution back, and the
handler would do it twice.

The messages are HTML with a plain-text alternative. The first version was
plain text with column-aligned labels, which arrives as ragged monospace in
Outlook and reads like a machine fault report rather than a bank's desk writing
to a colleague.
"""

import logging
from html import escape

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import Q
from django.utils import timezone

from .models import DeskRecipient, DeskSettings
from .rbac import AGENT_GROUP, MANAGER_GROUP
from .worktime import describe

log = logging.getLogger(__name__)

BRAND = "HFCB"
DESK_NAME = "HFCB Service Desk"
SUBJECT_PREFIX = "[HFCB Service Desk]"

TEAL = "#1996A9"
INK = "#0B2D3D"
MUTED = "#6B8A96"

#: The desk team. Membership is explicit — see the module docstring on why
#: superusers are deliberately NOT included here.
TEAM_GROUPS = [MANAGER_GROUP, AGENT_GROUP]
MANAGER_GROUPS = [MANAGER_GROUP]


def send(to, subject, text_body, html_body=None, reply_to=None):
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
            reply_to=[reply_to] if reply_to else None,
            connection=get_connection(fail_silently=False),
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")
        message.send()
        return len(addresses)
    except Exception as exc:  # noqa: BLE001 — mail must never break the desk
        log.warning("service desk mail failed (%s): %s", subject, exc)
        return 0


# ── Who hears ────────────────────────────────────────────────────────────────

def _emails(predicate, exclude=None):
    try:
        people = (get_user_model().objects
                  .filter(is_active=True).filter(predicate)
                  .exclude(email="").distinct())
        out = {p.email.strip() for p in people if p.email}
    except Exception:  # noqa: BLE001 — never break a transition over a lookup
        return []
    if exclude is not None and getattr(exclude, "email", None):
        out.discard(exclude.email.strip())
    return sorted(out)


def _plus_recipients(addresses, kind, exclude=None):
    """Team accounts, plus the people who have no account at all.

    Added to the accounts, never instead of them: several of the people who run
    this desk have no login, and requiring one before they can be emailed would
    mean creating logins purely so that mail has somewhere to go.
    """
    out = set(addresses) | set(DeskRecipient.addresses(kind))
    if exclude is not None and getattr(exclude, "email", None):
        out.discard(exclude.email.strip())
    return sorted(a for a in out if a)


def handler_addresses(exclude=None):
    """The desk: team accounts plus the account-free addresses.

    Group membership rather than every superuser — a superuser may work any
    ticket, but being able to administer the system is not the same as being on
    this desk, and the queue should not arrive in the inbox of everybody who
    happens to hold the keys.
    """
    return _plus_recipients(
        _emails(Q(groups__name__in=TEAM_GROUPS), exclude), "queue", exclude)


def manager_addresses(exclude=None):
    return _plus_recipients(
        _emails(Q(groups__name__in=MANAGER_GROUPS), exclude), "escalations", exclude)


def requester_addresses(ticket, exclude=None):
    out = set()
    if ticket.requester_email:
        out.add(ticket.requester_email.strip())
    if ticket.raised_by_id and getattr(ticket.raised_by, "email", ""):
        out.add(ticket.raised_by.email.strip())
    if exclude is not None and getattr(exclude, "email", None):
        out.discard(exclude.email.strip())
    return sorted(a for a in out if a)


def _owner_or_queue(ticket, exclude=None):
    """Whoever owns it, or the whole team while nobody does."""
    if ticket.assigned_to_id and getattr(ticket.assigned_to, "email", ""):
        return [ticket.assigned_to.email]
    return handler_addresses(exclude=exclude)


# ── Composition ──────────────────────────────────────────────────────────────

def _when(moment):
    return timezone.localtime(moment).strftime("%a %d %b, %H:%M") if moment else "—"


def _url(ticket):
    base = str(getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
    return f"{base}/service-desk/{ticket.reference}" if base else ""


def _facts(ticket):
    rows = [
        ("Reference", ticket.reference),
        ("Subject", ticket.subject),
        ("Type", ticket.category.name if ticket.category else "Uncategorised"),
        ("Priority", ticket.get_priority_display()),
        ("Status", ticket.get_status_display()),
    ]
    if ticket.assigned_to_id:
        rows.append(("Handled by",
                     ticket.assigned_to.get_full_name() or ticket.assigned_to.username))
    return rows


def _actor_name(actor):
    if actor is None or not getattr(actor, "is_authenticated", False):
        return "The desk"
    return actor.get_full_name() or actor.username


def _text(ticket, lead, extra=None, cta=None, note=None):
    """The plain-text alternative. Some people read mail as text by choice."""
    lines = [lead, ""]
    lines += [f"{label}: {value}" for label, value in _facts(ticket)]
    if note:
        lines += ["", note]
    if extra:
        lines += ["", extra]
    # The call to action is a button label. On its own it is an orphaned
    # imperative, so in text it only appears attached to the link it labels —
    # and not at all when there is no link to give.
    url = _url(ticket)
    if url:
        lines += ["", f"{cta or 'Open the query'}: {url}"]
    lines += ["", "--", DESK_NAME,
              "Please reply on the ticket rather than to this address, so the "
              "answer stays with the query."]
    return "\n".join(lines)


def _html(ticket, lead, extra=None, cta=None, accent=TEAL, note=None):
    """One layout for every message, so the desk reads as one sender."""
    url = _url(ticket)

    facts = "".join(
        f'<tr>'
        f'<td style="padding:5px 14px 5px 0;color:{MUTED};font-size:12px;'
        f'white-space:nowrap;vertical-align:top;">{escape(label)}</td>'
        f'<td style="padding:5px 0;color:{INK};font-size:13px;'
        f'font-weight:500;vertical-align:top;">{escape(str(value))}</td>'
        f'</tr>'
        for label, value in _facts(ticket)
    )

    note_block = ""
    if note:
        note_block = (
            f'<tr><td style="padding:0 28px 20px;">'
            f'<div style="background:#F7FAFB;border-left:3px solid {accent};'
            f'border-radius:4px;padding:12px 14px;color:{INK};font-size:13px;'
            f'line-height:1.6;white-space:pre-wrap;">{escape(note)}</div>'
            f'</td></tr>'
        )

    extra_block = ""
    if extra:
        extra_block = (
            f'<tr><td style="padding:0 28px 18px;color:{INK};font-size:13px;'
            f'line-height:1.65;">{escape(extra)}</td></tr>'
        )

    button = ""
    if url:
        label = cta or "Open the query"
        button = (
            f'<tr><td style="padding:4px 28px 28px;">'
            f'<a href="{escape(url)}" style="display:inline-block;background:{accent};'
            f'color:#ffffff;text-decoration:none;font-size:13px;font-weight:600;'
            f'padding:11px 22px;border-radius:8px;">{escape(label)}</a>'
            f'</td></tr>'
        )

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#EEF3F5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#EEF3F5;padding:24px 12px;">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:560px;background:#ffffff;border-radius:14px;
                overflow:hidden;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">

    <tr><td style="background:{INK};padding:18px 28px;">
      <span style="color:#ffffff;font-size:15px;font-weight:600;
                   letter-spacing:.3px;">{BRAND}</span>
      <span style="color:{TEAL};font-size:15px;font-weight:600;"> Service Desk</span>
    </td></tr>

    <tr><td style="padding:26px 28px 16px;color:{INK};font-size:15px;
                   line-height:1.6;">{escape(lead)}</td></tr>

    {extra_block}
    {note_block}

    <tr><td style="padding:0 28px 20px;">
      <table role="presentation" cellpadding="0" cellspacing="0"
             style="width:100%;border-top:1px solid #E8EEF0;
                    border-bottom:1px solid #E8EEF0;padding:6px 0;">
        {facts}
      </table>
    </td></tr>

    {button}

    <tr><td style="background:#F7FAFB;padding:16px 28px;color:{MUTED};
                   font-size:11px;line-height:1.6;">
      {escape(DESK_NAME)}<br>
      Please reply on the query itself rather than to this address, so the
      answer stays with it.
    </td></tr>

  </table>
</td></tr></table>
</body></html>"""


def _deliver(to, subject, ticket, lead, extra=None, cta=None, accent=TEAL, note=None):
    return send(
        to, subject,
        _text(ticket, lead, extra=extra, cta=cta, note=note),
        _html(ticket, lead, extra=extra, cta=cta, accent=accent, note=note),
    )


# ── The messages ─────────────────────────────────────────────────────────────

def ticket_raised(ticket, actor=None):
    """To the requester: we have it. To the team: it is here."""
    desk = DeskSettings.get()

    if desk.notify_requester:
        promise = (
            f"We aim to resolve this by {_when(ticket.resolution_due_at)}. "
            f"You will be emailed when it is answered and again when it is "
            f"resolved, so you do not have to chase it."
            if ticket.resolution_due_at else
            "You will be emailed when it is answered and again when it is resolved."
        )
        _deliver(
            requester_addresses(ticket),
            f"{ticket.reference} received — {ticket.subject}",
            ticket,
            "Your query has been logged with the Strategy & Business "
            "Performance desk.",
            extra=promise,
            cta="Follow your query",
        )

    respond_by = (f"Please respond by {_when(ticket.response_due_at)}."
                  if ticket.response_due_at else None)
    _deliver(
        handler_addresses(exclude=actor),
        f"New: {ticket.reference} — {ticket.subject}",
        ticket,
        "A query has been raised.",
        extra=respond_by,
        note=(ticket.body or "")[:1500] or None,
        cta="Open the query",
    )


def ticket_replied(ticket, comment, author=None):
    """A visible message goes to the other side, never back to its author."""
    if comment.is_internal:
        return
    from .rbac import is_handler

    if is_handler(author):
        _deliver(
            requester_addresses(ticket, exclude=author),
            f"{ticket.reference} — a reply from the desk", ticket,
            f"{_actor_name(author)} has replied to your query.",
            note=comment.body[:2000], cta="Read and reply",
        )
    else:
        _deliver(
            _owner_or_queue(ticket, exclude=author),
            f"{ticket.reference} — the requester replied", ticket,
            f"{_actor_name(author)} has added something to this query.",
            note=comment.body[:2000], cta="Open the query",
        )


def ticket_assigned(ticket, actor=None):
    if not DeskSettings.get().notify_assignee:
        return
    if not (ticket.assigned_to_id and getattr(ticket.assigned_to, "email", "")):
        return
    if actor is not None and ticket.assigned_to_id == getattr(actor, "id", None):
        return  # they picked it up themselves; they know
    _deliver(
        [ticket.assigned_to.email],
        f"{ticket.reference} is yours — {ticket.subject}", ticket,
        "This query has been assigned to you.",
        extra=f"Please resolve by {_when(ticket.resolution_due_at)}."
              if ticket.resolution_due_at else None,
        note=(ticket.body or "")[:1500] or None,
        cta="Open the query",
    )


def ticket_resolved(ticket, actor=None):
    """The email that closes the loop the original complaint is about."""
    days = DeskSettings.get().auto_close_after_days
    _deliver(
        requester_addresses(ticket, exclude=actor),
        f"{ticket.reference} resolved — {ticket.subject}", ticket,
        "The desk has marked your query resolved. This is what was done:",
        note=(ticket.resolution_note or "No note was left.")[:2000],
        extra=(
            f"If that answers it, please confirm and we are done. If it does "
            f"not, reopen it — it comes straight back to us with its full "
            f"history, so you do not start again. If we hear nothing it closes "
            f"on its own after {days} working day(s), recorded as unconfirmed."
        ),
        cta="Confirm or reopen",
        accent="#16A34A",
    )


def ticket_closed(ticket, actor=None):
    if ticket.confirmed_by_requester:
        return  # they closed it themselves; telling them is noise
    _deliver(
        requester_addresses(ticket, exclude=actor),
        f"{ticket.reference} closed — {ticket.subject}", ticket,
        "This query has been closed.",
        extra=f"It can still be reopened for "
              f"{DeskSettings.get().reopen_window_days} days if it was not "
              f"actually answered.",
        cta="View the query",
        accent=MUTED,
    )


def ticket_reopened(ticket, actor=None):
    _deliver(
        _owner_or_queue(ticket, exclude=actor),
        f"{ticket.reference} reopened — {ticket.subject}", ticket,
        "The requester says this was not resolved.",
        extra=f"Reopened {ticket.reopened_count} time(s).",
        cta="Open the query",
        accent="#E9A23B",
    )


def breach_warning(ticket, kind="resolution"):
    """Before it breaches, not after. After is a report; before is a chance."""
    due = ticket.response_due_at if kind == "response" else ticket.resolution_due_at
    _deliver(
        _owner_or_queue(ticket),
        f"Due soon: {ticket.reference} — {ticket.subject}", ticket,
        f"This query is close to its {kind} target.",
        extra=f"Target: {_when(due)}. Open for "
              f"{describe(ticket.working_seconds_open())} of working time.",
        cta="Open the query",
        accent="#E9A23B",
    )


def breached(ticket, kind="resolution"):
    """Managers only.

    A breach is a management fact, not a nag for the handler — who is usually
    already aware, and is the person who could not get to it.
    """
    due = ticket.response_due_at if kind == "response" else ticket.resolution_due_at
    _deliver(
        manager_addresses(),
        f"SLA breached: {ticket.reference} — {ticket.subject}", ticket,
        f"This query has passed its {kind} target.",
        extra=f"Target was {_when(due)}. Raised {_when(ticket.created_at)}. "
              f"Open for {describe(ticket.working_seconds_open())} of working time.",
        cta="Open the query",
        accent="#F04E45",
    )


def report(to, subject, body_text):
    """The periodic report. Monospace on purpose — it is a column layout."""
    html = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#EEF3F5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#EEF3F5;padding:24px 12px;">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:640px;background:#ffffff;border-radius:14px;overflow:hidden;
                font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <tr><td style="background:{INK};padding:18px 28px;">
      <span style="color:#ffffff;font-size:15px;font-weight:600;">{BRAND}</span>
      <span style="color:{TEAL};font-size:15px;font-weight:600;"> Service Desk</span>
    </td></tr>
    <tr><td style="padding:22px 28px;">
      <pre style="margin:0;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
                  font-size:12px;line-height:1.65;color:{INK};white-space:pre-wrap;"
      >{escape(body_text)}</pre>
    </td></tr>
    <tr><td style="background:#F7FAFB;padding:14px 28px;color:{MUTED};font-size:11px;">
      {escape(DESK_NAME)}
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""
    return send(to, subject, body_text, html)
