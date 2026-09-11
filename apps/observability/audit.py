"""Reads the audit trail that ``simple_history`` has been writing all along.

Every model carrying ``HistoricalRecords()`` gets a shadow table with one row
per create / update / delete, the acting user (via
``simple_history.middleware.HistoryRequestMiddleware``, which is already in the
middleware stack) and a timestamp. Thirty-five models across nine apps record
this. Nothing had ever read it — the Administration "audit" screen only showed
frontend page-view pings.

This module turns those tables into one feed: enumerate the historical models,
pull each one's recent rows, merge-sort them by time, and — for an update —
diff the row against its predecessor so the feed says *which fields changed and
what from*, not merely that "something was edited".
"""

from django.apps import apps as django_apps
from django.db import DatabaseError

ACTION_LABELS = {"+": "created", "~": "updated", "-": "deleted"}

# Never diff or display these — they are the audit bookkeeping itself.
_HISTORY_META = {
    "history_id", "history_date", "history_change_reason",
    "history_type", "history_user", "history_user_id", "history_relation",
}


def auditable_models():
    """Every model in the project that keeps history, sorted for display.

    Returns dicts of ``{app_label, model, verbose, history_model, model_class}``.
    """
    out = []
    for model in django_apps.get_models():
        manager = getattr(model, "history", None)
        history_model = getattr(manager, "model", None)
        if history_model is None or not hasattr(history_model, "history_type"):
            continue
        out.append({
            "app_label": model._meta.app_label,
            "model": model._meta.model_name,
            "verbose": str(model._meta.verbose_name).title(),
            "history_model": history_model,
            "model_class": model,
        })
    out.sort(key=lambda r: (r["app_label"], r["model"]))
    return out


def _tracked_field_names(history_model):
    return [
        f.name for f in history_model._meta.fields
        if f.name not in _HISTORY_META
    ]


def describe(record):
    """A human label for the record this history row belongs to.

    ``__str__`` on the historical row is simple_history's own
    "<obj> as of <date>", so the underlying model's ``__str__`` is used where it
    can be reconstructed, and the primary key otherwise.
    """
    try:
        instance = record.instance
    except Exception:  # noqa: BLE001 — a stale FK must not break the feed
        return str(getattr(record, "id", "") or "")
    try:
        text = str(instance)
    except Exception:  # noqa: BLE001
        return str(getattr(record, "id", "") or "")
    return text[:200]


def changed_fields(record):
    """``[{field, old, new}]`` for an update; ``[]`` for a create or delete.

    A create has nothing to compare against and a delete's "change" is the
    deletion itself, so only ``~`` rows are diffed.
    """
    if record.history_type != "~":
        return []
    try:
        previous = record.prev_record
    except (DatabaseError, AttributeError):
        return []
    if previous is None:
        return []
    try:
        delta = record.diff_against(previous, excluded_fields=tuple(_HISTORY_META))
    except Exception:  # noqa: BLE001 — a schema change can break an old diff
        return []
    return [
        {
            "field": change.field,
            "old": _render(change.old),
            "new": _render(change.new),
        }
        for change in delta.changes
    ]


ACTION_CODES = {"created": "+", "updated": "~", "deleted": "-"}


def external_feed(since=None, until=None, source=None, username=None,
                  action=None, model=None, limit=100):
    """Events pushed by another system, in the same shape as the local ones.

    ``source`` doubles as the app filter: the feed's app column shows the
    service name for an external row, so filtering by it has to reach these.
    """
    from .models import ExternalAuditEvent

    qs = ExternalAuditEvent.objects.all()
    if since is not None:
        qs = qs.filter(occurred_at__gte=since)
    if until is not None:
        qs = qs.filter(occurred_at__lte=until)
    if source:
        qs = qs.filter(source__iexact=source)
    if username:
        qs = qs.filter(username__iexact=username)
    if action:
        wanted = {v: k for k, v in ACTION_CODES.items()}.get(action)
        if wanted:
            qs = qs.filter(action__iexact=wanted)
    rows = [
        {
            "app_label": row.source,
            "model": (row.model_label or "").lower().replace(" ", ""),
            "model_label": row.model_label or "—",
            "object_id": row.object_id,
            "object_label": row.object_label,
            "action": row.action or "changed",
            "action_code": ACTION_CODES.get(row.action, "~"),
            "user": row.username or None,
            "username": row.username or None,
            "reason": row.reason or "",
            "when": row.occurred_at,
            "changes": row.changes if isinstance(row.changes, list) else [],
            # So the page can show where a row came from — a change made in
            # Customer 360 must not read as one made here.
            "external": True,
            "source": row.source,
        }
        for row in qs.order_by("-occurred_at")[:limit]
    ]
    if model:
        # Narrowing the feed to one record type has to narrow these too, or
        # filtering to "Trade Entry" would still list everything Customer 360
        # has ever pushed. Compared on the normalised key, because that is what
        # the page sends back.
        rows = [row for row in rows if row["model"] == model.lower().replace(" ", "")]
    return rows


def _render(value):
    if value is None:
        return None
    text = str(value)
    return text[:300]


def serialise(record, entry, with_changes=True):
    """One feed row from one historical record."""
    user = record.history_user
    return {
        "app_label": entry["app_label"],
        "model": entry["model"],
        "model_label": entry["verbose"],
        "object_id": getattr(record, entry["model_class"]._meta.pk.attname, None),
        "object_label": describe(record),
        "action": ACTION_LABELS.get(record.history_type, record.history_type),
        "action_code": record.history_type,
        "user": (user.get_full_name() or user.username) if user else None,
        "username": user.username if user else None,
        "reason": record.history_change_reason or "",
        "when": record.history_date,
        "changes": changed_fields(record) if with_changes else [],
        "external": False,
        "source": "portfolio",
    }


def feed(since=None, until=None, app_label=None, model=None, username=None,
         action=None, search=None, limit=100, with_changes=True):
    """Merged, newest-first audit feed across every history table.

    Each table contributes at most ``limit`` rows before the merge, which is
    what keeps this to one small query per model instead of a union over
    thirty-five tables.
    """
    rows = []
    for entry in auditable_models():
        if app_label and entry["app_label"] != app_label:
            continue
        if model and entry["model"] != model:
            continue
        qs = entry["history_model"].objects.all()
        if since is not None:
            qs = qs.filter(history_date__gte=since)
        if until is not None:
            qs = qs.filter(history_date__lte=until)
        if username:
            qs = qs.filter(history_user__username__iexact=username)
        if action:
            qs = qs.filter(history_type=action)
        try:
            recent = list(
                qs.select_related("history_user").order_by("-history_date")[:limit]
            )
        except DatabaseError:
            # A history table that was never migrated on this database must not
            # take the whole feed down with it.
            continue
        for record in recent:
            rows.append((record, entry))

    rows.sort(key=lambda pair: pair[0].history_date, reverse=True)
    out = [serialise(r, e, with_changes=with_changes) for r, e in rows[:limit]]

    # Changes made in OTHER systems — Customer 360 pushes its own events here.
    # They merge into this one feed rather than living on a second screen: the
    # point of an audit trail is that one place answers "who changed what".
    out += external_feed(
        since=since, until=until, source=app_label, username=username,
        action=action, model=model, limit=limit,
    )
    out.sort(key=lambda row: row["when"], reverse=True)
    out = out[:limit]
    if search:
        needle = search.lower()
        out = [
            row for row in out
            if needle in (row["object_label"] or "").lower()
            or needle in (row["model_label"] or "").lower()
            or needle in (row["username"] or "").lower()
        ]
    return out
