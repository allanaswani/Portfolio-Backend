"""Back-office Digital Onboarding, from the bank's Whizz onboarding report.

The CSO cards' Digital Onboarding line (the template's ``Digital_Customers``
sheet) is the number of customers a person onboarded on Whizz this year. The
report behind it is ``whizz_onnboarding_report.py`` (the ETLs): it reads

    delta.gold_db.customers_whizz  (customer_id, status, date_created,
                                    created_by, ...)

from 1 January LAST year, keeps one row per ``customer_id``, and its "Officer
Performance" sheet counts, per ``created_by``, every customer onboarded
("Onboarded" - all statuses, not only the active ones).

Read from the lake on a schedule (``manage.py load_whizz_onboarding``) into
the workbook-file store, never on the card's path: a lake read on every page
view is how the active-customers lines once timed out. The card reads the
running total of the person's months up to the card's month.

Whose row is whose: ``created_by`` is matched to the person by sales code, by
the AD login the desk keys their account-opening rows on, or by name
(:func:`live_scorecard.names_agree`). Somebody the report does not name has
no figure here - never a nought - and keeps the desk's.
"""
from __future__ import annotations

import datetime
import re

KIND = "whizz_onb:{}"

QUERY = """
    WITH c AS (
        SELECT customer_id, created_by, date_created,
               ROW_NUMBER() OVER (PARTITION BY customer_id
                                  ORDER BY date_created) AS rn
        FROM delta.gold_db.customers_whizz
        WHERE date_created >= DATE '{since}' AND customer_id IS NOT NULL)
    SELECT created_by, year(date_created) AS y, month(date_created) AS m,
           count(*) AS n
    FROM c WHERE rn = 1
    GROUP BY 1, 2, 3
"""


def officer_key(value):
    """The report's own tidy (spaces collapsed), upper case."""
    return " ".join(str(value or "").split()).upper()


def fetch(year):
    """The lake's counts for ``year`` -> {officer: {month: n}}.

    Customers are de-duplicated from 1 January of the year before, as the
    report does, so one first onboarded last year is not counted again."""
    import os

    import trino
    import urllib3
    from trino.auth import BasicAuthentication

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    host = os.environ.get("TRINO_HOST")
    user = (os.environ.get("TRINO_USER") or "").strip().strip("'\"")
    password = (os.environ.get("TRINO_PASSWORD") or "").strip().strip("'\"")
    if not host or not user or not password:
        raise RuntimeError("TRINO_HOST, TRINO_USER and TRINO_PASSWORD must be "
                           "set in the environment file.")
    connection = trino.dbapi.connect(
        host=host, port=int(os.environ.get("TRINO_PORT", "8443")), user=user,
        auth=BasicAuthentication(user, password),
        catalog=os.environ.get("TRINO_CATALOG", "delta"),
        http_scheme=os.environ.get("TRINO_HTTP_SCHEME", "https"), verify=False)
    cursor = connection.cursor()
    cursor.execute(QUERY.format(since=f"{year - 1}-01-01"))
    return counts(cursor.fetchall(), year)


def counts(rows, year):
    """(created_by, year, month, n) rows -> {officer: {"m": n}} for ``year``."""
    out = {}
    for created_by, y, m, n in rows:
        if int(y) != year:
            continue
        key = officer_key(created_by) or "UNKNOWN"
        months = out.setdefault(key, {})
        months[str(int(m))] = months.get(str(int(m)), 0) + int(n)
    return out


def save(year, officers):
    from django.core.cache import cache

    from .workbook_cards import save_file

    save_file(KIND.format(year), {"year": year, "officers": officers,
                                  "loaded": datetime.date.today().isoformat()},
              "delta.gold_db.customers_whizz", "load_whizz_onboarding")
    cache.delete(KIND.format(year))


def _loaded(year):
    from django.core.cache import cache

    from .workbook_cards import saved

    data = cache.get(KIND.format(year))
    if data is None:
        data = saved(KIND.format(year)) or {}
        cache.set(KIND.format(year), data, 3600)
    return data


def _alnum(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def mine(officers, codes=(), names=()):
    """The ``created_by`` spellings that are this person -> [officer]."""
    from .live_scorecard import names_agree

    ids = {_alnum(c) for c in codes if c and len(_alnum(c)) >= 4}
    out = []
    for officer in officers:
        if _alnum(officer) in ids or any(n and names_agree(officer, n) for n in names):
            out.append(officer)
    return out


def running_total(year, month, codes=(), names=()):
    """Customers this person onboarded in ``year`` to ``month`` -> (n, loaded)
    or (None, None) when nothing is loaded or the report does not name them."""
    data = _loaded(year)
    officers = data.get("officers") or {}
    if not officers:
        return None, None
    found = mine(officers, codes, names)
    if not found:
        return None, None
    total = sum(n for officer in found
                for m, n in officers[officer].items() if int(m) <= month)
    return total, data.get("loaded")
