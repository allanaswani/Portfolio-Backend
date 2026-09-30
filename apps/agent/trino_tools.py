"""Curated reads from the Trino lake (``delta.gold_db``).

Every other data tool reads the Postgres warehouse, which is a *derived* copy:
the ETLs pull from Trino nightly and land summaries. That means anything the
ETLs do not land — an individual account, yesterday's opening date, a customer
who arrived today — is invisible to the assistant no matter how it is asked.
These tools reach the lake directly for exactly those questions.

**Curated, not free SQL.** Each tool owns one fixed statement with bound
parameters and a hard ``LIMIT``. The model chooses the tool and the arguments;
it never composes SQL. A lake holding every account in the bank is not somewhere
to let a language model improvise, and a fixed statement is also the only way
``surfaces`` can honestly re-run a panel later and get the same shape back.

**Dormant unless configured.** No ``TRINO_HOST``, no tools: the definitions are
never offered, so the model cannot try and fail. Same pattern as
``web_lookup``, for the same reason — configuration is the control.

The tables and columns below are not guesses. They are the ones the production
ETLs already read (``crm_it_data.py`` and
``trino_python_scripts/trino_sql_queries/``): ``dim_customer``,
``eom_deposits``, ``other_id``, ``unit`` and ``bank_parameters``. Nothing here
references a column those queries do not.
"""

import logging

from django.conf import settings

log = logging.getLogger(__name__)

#: A lake query holds the user's question open. Keep both of these small.
TIMEOUT_SECONDS = 30
MAX_ROWS = 200

#: ``bank_parameters`` carries the bank's own idea of "the last closed day".
#: Every balance table is keyed on it, so using it beats CURRENT_DATE, which
#: silently returns nothing on a day the batch has not run.
PREV_DATE = "(SELECT prev_trx_date FROM delta.gold_db.bank_parameters)"


def _cfg(name, default=""):
    return str(getattr(settings, name, default) or "").strip()


def enabled() -> bool:
    """True only when a host is configured. Absence is the off switch."""
    return bool(_cfg("TRINO_HOST"))


def _connect():
    """A Trino connection, or a readable reason why not.

    ``trino`` is an optional dependency: the package is only needed where the
    lake is reachable, so an ImportError is a configuration answer rather than
    a crash.
    """
    try:
        import trino
        from trino.auth import BasicAuthentication
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "The 'trino' package is not installed on this server, so the lake "
            "cannot be reached. Install it or leave TRINO_HOST unset."
        ) from exc

    host = _cfg("TRINO_HOST")
    port = int(_cfg("TRINO_PORT", "8443") or 8443)
    user = _cfg("TRINO_USER")
    password = _cfg("TRINO_PASSWORD")
    catalog = _cfg("TRINO_CATALOG", "delta") or "delta"
    schema = _cfg("TRINO_SCHEMA", "gold_db") or "gold_db"

    kwargs = {
        "host": host,
        "port": port,
        "user": user or "portfolio-tool",
        "catalog": catalog,
        "schema": schema,
        "request_timeout": TIMEOUT_SECONDS,
    }
    if password:
        kwargs["auth"] = BasicAuthentication(user, password)
        kwargs["http_scheme"] = "https"
    return trino.dbapi.connect(**kwargs)


def _query(sql, params=None, limit=MAX_ROWS):
    """Run one statement and return rows as dicts.

    The caller supplies the SQL; the model never does. Parameters are bound by
    the driver rather than formatted in, so a customer name containing a quote
    is data and not syntax.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        columns = [d[0].lower() for d in (cur.description or [])]
        rows = cur.fetchmany(limit)
        return [dict(zip(columns, row)) for row in rows]
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — a failed close must not mask the result
            pass


# ── The tools ────────────────────────────────────────────────────────────────

def trino_health(**_):
    """Can this server reach the lake at all, and as of which day?

    Worth its own tool: nobody currently knows whether the app tier has a route
    to the Trino host, and "the assistant said there was no data" is a much
    worse way to find out than asking.
    """
    if not enabled():
        return {"enabled": False,
                "detail": "TRINO_HOST is not set on this server."}
    try:
        rows = _query(
            f"SELECT prev_trx_date AS last_closed_day, "
            f"       previous_date AS previous_date "
            f"FROM delta.gold_db.bank_parameters", limit=1)
    except Exception as exc:  # noqa: BLE001 — the reason is the answer here
        return {"enabled": True, "reachable": False, "error": str(exc)}
    return {"enabled": True, "reachable": True,
            "catalog": _cfg("TRINO_CATALOG", "delta"),
            "schema": _cfg("TRINO_SCHEMA", "gold_db"),
            "bank_parameters": rows[0] if rows else None}


def trino_customer_accounts(cust_id=None, account_no=None, national_id=None,
                            limit=50, **_):
    """Every deposit account for one customer, straight from the lake.

    Identified by customer id, account number or national id — whichever the
    person has. At least one is required: this deliberately cannot list
    accounts in bulk.
    """
    if not enabled():
        return {"error": "The Trino lake is not configured on this server."}

    cust_id = (str(cust_id).strip() if cust_id else "")
    account_no = (str(account_no).strip() if account_no else "")
    national_id = (str(national_id).strip() if national_id else "")
    if not (cust_id or account_no or national_id):
        return {"error": "One of cust_id, account_no or national_id is required."}

    try:
        limit = max(1, min(int(limit), MAX_ROWS))
    except (TypeError, ValueError):
        limit = 50

    where, params = [], []
    if cust_id:
        where.append("CAST(d.cust_id AS VARCHAR) = ?")
        params.append(cust_id)
    if account_no:
        where.append("TRIM(d.account_number) = ?")
        params.append(account_no)
    if national_id:
        where.append("TRIM(UPPER(o.id_no)) = ?")
        params.append(national_id.upper())

    sql = f"""
        SELECT CAST(d.cust_id AS VARCHAR)              AS cust_id,
               TRIM(c.first_name) || ' ' || TRIM(c.surname) AS customer_name,
               TRIM(d.account_number)                  AS account_number,
               d.account_type                          AS account_type,
               d.currency                              AS currency,
               d.status_ind                            AS account_status,
               d.opening_date                          AS opened,
               d.monitoring_employee_name              AS relationship_manager,
               d.fk_bankemployeeid                     AS rm_sales_code,
               CAST(d.dep_open_unit AS INTEGER)        AS branch_code,
               TRIM(UPPER(o.id_no))                    AS national_id
        FROM   delta.gold_db.eom_deposits d
        LEFT JOIN delta.gold_db.dim_customer c ON c.customer_id = d.cust_id
        LEFT JOIN delta.gold_db.other_id    o ON o.fk_customercust_id = d.cust_id
        WHERE  d.eom_date = {PREV_DATE}
          AND  d.cust_id IS NOT NULL
          AND  ({' OR '.join(where)})
    """
    try:
        rows = _query(sql, params, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"The lake could not be read: {exc}"}
    return {"source": "trino:delta.gold_db", "found": len(rows), "accounts": rows}


TOOL_DEFINITIONS = [
    {
        "name": "trino_health",
        "description": (
            "Check whether this server can reach the Trino data lake, and "
            "which business day the lake is closed to. Call this first if a "
            "lake tool returns nothing, to tell a connectivity problem apart "
            "from a genuinely empty result."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "trino_customer_accounts",
        "description": (
            "Every deposit account held by ONE customer, read live from the "
            "Trino lake rather than the nightly warehouse copy — account "
            "number, type, currency, status, when it was opened and which RM "
            "monitors it. Requires a customer id, account number or national "
            "id; it cannot list accounts in bulk. Use this when the warehouse "
            "tools do not go down to individual accounts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cust_id": {"type": "string", "description": "Core banking customer id."},
                "account_no": {"type": "string", "description": "A single account number."},
                "national_id": {"type": "string", "description": "National ID number."},
                "limit": {"type": "integer", "description": "Max accounts. Default 50."},
            },
        },
    },
]

DISPATCH = {
    "trino_health": trino_health,
    "trino_customer_accounts": trino_customer_accounts,
}
