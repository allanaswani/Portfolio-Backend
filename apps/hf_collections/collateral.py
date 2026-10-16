"""What a loan is actually secured on.

The collections page typed collateral from ``product_mapping``, which types
the PRODUCT: every mortgage read "PROPERTY" whether or not a charge existed,
and a loan secured on a term deposit read whatever its product said. An
officer about to ring somebody about an arrears balance wants the charge,
not the product's category.

The real thing is in the lake, in two tables:

* ``account_collateral`` - 17,094 charges, keyed on ``prft_account``, with
  the estimated value, the mortgage amount and the expiry;
* ``collateral`` - what each charge IS, joined on the three columns core
  banking identifies it by: unit, company and serial. ``collateral_sn``
  repeats across units, so all three are needed; on the real data all 17,094
  rows join, over 15,265 loan accounts.

Typed PROPERTY (11,915 accounts), VEHICLE (1,895), TERM DEPOSIT COLLATERAL
(1,323), DYNAMIC COLLATERAL, PLOT, BOND, PENSION, INSURANCE and GUARANTEE.

Mirrored into Postgres rather than read live, for the reason the activity
feed is: the customer page is built on request, and a lake read on that path
is what hands the browser a dead connection.
"""

from __future__ import annotations

#: Joined in the lake, so what crosses the wire is one row per charge with
#: its type already resolved.
TRINO_QUERY = """
    SELECT TRIM(a.prft_account)                 AS loan_account_no,
           CAST(a.fk_customercust_id AS BIGINT) AS cust_id,
           a.full_name                          AS customer_name,
           CAST(a.fk_collateralfk_un AS INTEGER) AS unit_code,
           CAST(a.fk_collateralfk_co AS INTEGER) AS collateral_co,
           CAST(a.fk_collateralcolla AS INTEGER) AS collateral_sn,
           c.collateral_type,
           c.collateral_desc,
           c.collateral_status,
           a.est_value_amn                      AS estimated_value,
           c.total_estimated_value_amount       AS collateral_value,
           a.est_insurance_amn                  AS insurance_value,
           a.mortgage_amn                       AS mortgage_amount,
           a.mortgage_class,
           -- As TEXT. Core banking writes 0000-12-30 for "no expiry",
           -- which is not a date any driver will hand back - it fails the
           -- whole read rather than the one row. Parsed below, where the
           -- sentinel can be recognised for what it is.
           CAST(a.expiry_date_collateral AS VARCHAR) AS expires_on
    FROM delta.gold_db.account_collateral a
    JOIN delta.gold_db.collateral c
      ON c.unit_code         = a.fk_collateralfk_un
     AND c.fk_collateral_tfk = a.fk_collateralfk_co
     AND c.collateral_sn     = a.fk_collateralcolla
    WHERE a.prft_account IS NOT NULL
      AND TRIM(a.prft_account) <> ''
"""


def fetch_from_trino():
    """Run the join against the lake → list of dicts.

    Credentials come from the environment, never from this file:
    ``TRINO_HOST``, ``TRINO_PORT``, ``TRINO_USER``, ``TRINO_PASSWORD``.
    """
    import os

    import trino
    import urllib3
    from trino.auth import BasicAuthentication

    # The lake's certificate is not one this host trusts, so the connection
    # passes verify=False. urllib3 warns once per REQUEST and the client
    # polls, so one load would print the warning a dozen times.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    host = os.environ.get("TRINO_HOST")
    if not host:
        raise RuntimeError(
            "TRINO_HOST is not set, so the lake cannot be reached. The "
            "TRINO_* variables go in the environment file.")

    # docker --env-file takes quotes literally, so a password written with
    # them reaches Trino with them and comes back 401.
    user = (os.environ.get("TRINO_USER") or "").strip().strip("'\"")
    password = (os.environ.get("TRINO_PASSWORD") or "").strip().strip("'\"")
    if not user or not password:
        raise RuntimeError(
            "TRINO_USER or TRINO_PASSWORD is not set, so the lake cannot be "
            "reached. Both go in the environment file alongside TRINO_HOST.")

    connection = trino.dbapi.connect(
        host=host,
        port=int(os.environ.get("TRINO_PORT", "8443")),
        user=user,
        auth=BasicAuthentication(user, password),
        catalog=os.environ.get("TRINO_CATALOG", "delta"),
        http_scheme=os.environ.get("TRINO_HTTP_SCHEME", "https"),
        verify=False,
    )
    cursor = connection.cursor()
    cursor.execute(TRINO_QUERY)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _text(value, limit):
    return str(value if value is not None else "").strip()[:limit]


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value):
    """A collateral expiry → date, or None.

    Core banking writes ``0000-12-30`` to mean "no expiry". It is not a date
    any driver will hand back, and anything before 1900 is that sentinel
    rather than a charge that lapsed under Queen Victoria.
    """
    import datetime

    if value in (None, ""):
        return None
    if hasattr(value, "date"):
        value = value.date()
    if isinstance(value, datetime.date):
        return value if value.year >= 1900 else None

    text = str(value).strip()[:10]
    try:
        parsed = datetime.date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.year >= 1900 else None


def plan(rows):
    """Lake rows → ``(entries, report)``. Writes nothing."""
    entries, report = [], {
        "read": len(rows), "accounts": set(), "by_type": {},
        "no_account": 0, "duplicates": 0,
    }
    # The same charge is listed more than once in places - the join can
    # match a charge that core banking has recorded twice against an
    # account. One charge is one charge: the later row is dropped and
    # counted, rather than being written twice and doubling what the bank
    # looks like it is holding.
    seen = set()

    for row in rows:
        account = _text(row.get("loan_account_no"), 40)
        if not account:
            report["no_account"] += 1
            continue
        key = (account,
               int(row.get("unit_code") or 0),
               int(row.get("collateral_co") or 0),
               int(row.get("collateral_sn") or 0))
        if key in seen:
            report["duplicates"] += 1
            continue
        seen.add(key)

        kind = _text(row.get("collateral_type"), 80)
        report["by_type"][kind] = report["by_type"].get(kind, 0) + 1
        report["accounts"].add(account)
        entries.append({
            "loan_account_no": account,
            "cust_id": row.get("cust_id"),
            "customer_name": _text(row.get("customer_name"), 255),
            "unit_code": int(row.get("unit_code") or 0),
            "collateral_co": int(row.get("collateral_co") or 0),
            "collateral_sn": int(row.get("collateral_sn") or 0),
            "collateral_type": kind,
            "collateral_desc": _text(row.get("collateral_desc"), 255),
            "collateral_status": _text(row.get("collateral_status"), 40),
            "estimated_value": _number(row.get("estimated_value")),
            "collateral_value": _number(row.get("collateral_value")),
            "insurance_value": _number(row.get("insurance_value")),
            "mortgage_amount": _number(row.get("mortgage_amount")),
            "mortgage_class": _text(row.get("mortgage_class"), 40),
            "expires_on": _date(row.get("expires_on")),
        })

    report["accounts"] = len(report["accounts"])
    report["to_write"] = len(entries)
    return entries, report


def save(entries, batch=2000):
    """Write the mirror → how many rows were written.

    Upserted on the charge's own identity, so a reload corrects rather than
    stacking a second copy of the same charge.
    """
    from django.db import transaction

    from .models import LoanCollateral

    written = 0
    with transaction.atomic():
        for start in range(0, len(entries), batch):
            chunk = entries[start:start + batch]
            LoanCollateral.objects.bulk_create(
                [LoanCollateral(**item) for item in chunk],
                update_conflicts=True,
                update_fields=[
                    "cust_id", "customer_name", "collateral_type",
                    "collateral_desc", "collateral_status",
                    "estimated_value", "collateral_value", "insurance_value",
                    "mortgage_amount", "mortgage_class", "expires_on",
                    "loaded_at"],
                unique_fields=["loan_account_no", "unit_code",
                               "collateral_co", "collateral_sn"])
            written += len(chunk)
    return written


def for_accounts(accounts):
    """The charges against these loan accounts → ``{account: [charge, ...]}``.

    Keyed on the account as the LOANS feed spells it, trimmed, because the
    lake pads ``prft_account`` to a fixed width.
    """
    from .models import LoanCollateral

    wanted = {str(a).strip() for a in accounts if str(a or "").strip()}
    if not wanted:
        return {}

    out = {}
    for row in LoanCollateral.objects.filter(loan_account_no__in=wanted):
        out.setdefault(row.loan_account_no, []).append({
            "type": row.collateral_type,
            "description": row.collateral_desc,
            "status": row.collateral_status,
            "estimated_value": (float(row.estimated_value)
                                if row.estimated_value is not None else None),
            "collateral_value": (float(row.collateral_value)
                                 if row.collateral_value is not None
                                 else None),
            "insurance_value": (float(row.insurance_value)
                                if row.insurance_value is not None else None),
            "mortgage_amount": (float(row.mortgage_amount)
                                if row.mortgage_amount is not None else None),
            "expires_on": row.expires_on,
        })
    return out


def coverage():
    """What the mirror holds → a dict, for telling a gap from a stale load."""
    from django.db.models import Count

    from .models import LoanCollateral

    rows = LoanCollateral.objects.all()
    return {
        "charges": rows.count(),
        "accounts": rows.values("loan_account_no").distinct().count(),
        "by_type": {
            item["collateral_type"]: item["n"]
            for item in rows.values("collateral_type")
            .annotate(n=Count("id")).order_by("-n")
        },
    }
