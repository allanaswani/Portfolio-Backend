"""The signed-in person's OWN book — the questions the assistant was failing.

An RM asked "tell me about my portfolio across my customers" and was told they
had one borrower called Julia Walimbwa and no loans. That answer came from
``get_portfolio_dashboard``, which reads the **mortgage** module: a different
product, a bank-wide view, and in that environment a single test record. The
name and description invited the model to pick it for any question containing
the word "portfolio", and it did.

Two things were wrong, and only one of them was the prompt:

* nothing read the relationship manager's actual book — deposits, loans,
  revenue and customers from the warehouse, keyed on their sales code; and
* **no tool was scoped to the person asking.** Every executor returned
  bank-wide figures, and ``_role_context`` merely *asked* the model to tailor
  its emphasis. A request is not a boundary: an RM could be handed the whole
  bank's numbers because the model judged them relevant.

So these tools take the user, resolve their ``Profile.sales_code`` — the same
key every screen in ``apps.portfolio`` scopes on — and refuse rather than fall
back to everything when there is no code to scope by. An unscoped answer that
looks scoped is worse than no answer.
"""

from services import portfolio_service as svc


def sales_code_of(user):
    """The signed-in person's book, or ``None``."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        code = (user.profile.sales_code or "").strip()
    except Exception:  # noqa: BLE001 — no profile row is a normal state here
        return None
    return code or None


def _no_code():
    return {
        "error": "no_sales_code",
        "detail": (
            "This account has no sales code on its profile, so there is no "
            "book to report on. That is an Administration setting, not "
            "something the user can fix. Say so plainly and do not substitute "
            "bank-wide figures — they would look like this person's own."
        ),
    }


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def my_portfolio(user=None, **_):
    """Headline figures for the signed-in relationship manager's own book."""
    code = sales_code_of(user)
    if not code:
        return _no_code()

    out = {"sales_code": code, "scope": "this user's own book only"}

    # Each block is guarded separately: a warehouse table that is empty or
    # unavailable should cost its own line, not the whole answer.
    try:
        totals = svc.rM_total_customers(code) or {}
        out["customers"] = totals
    except Exception as exc:  # noqa: BLE001
        out["customers"] = {"error": str(exc)[:200]}

    try:
        out["revenue"] = svc.rm_revenue(code) or {}
    except Exception as exc:  # noqa: BLE001
        out["revenue"] = {"error": str(exc)[:200]}

    try:
        rows = svc.loans_arrears_by_sales_code(code) or []
        out["loans_in_arrears"] = {
            "accounts": len(rows),
            "total_arrears": sum(_num(r.get("arrears") or r.get("arrears_amount"))
                                 for r in rows),
        }
    except Exception as exc:  # noqa: BLE001
        out["loans_in_arrears"] = {"error": str(exc)[:200]}

    try:
        out["new_customers_ytd"] = svc.rm_new_customers_ytd(code)
    except Exception as exc:  # noqa: BLE001
        out["new_customers_ytd"] = {"error": str(exc)[:200]}

    return out


def my_customers(user=None, limit=25, **_):
    """The customers allocated to the signed-in relationship manager."""
    code = sales_code_of(user)
    if not code:
        return _no_code()
    try:
        limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        limit = 25

    rows = list(svc.customers(code))
    trimmed = []
    for row in rows[:limit]:
        trimmed.append({
            "cust_id": row.get("cust_id"),
            "name": row.get("customer_name") or row.get("latin_surname"),
            "segment": row.get("segment"),
            "deposits": row.get("total_depost_balance"),
            "loans": row.get("total_loans"),
            "revenue": row.get("total_revenue"),
        })
    return {
        "sales_code": code,
        "scope": "this user's own book only",
        "total_customers": len(rows),
        "showing": len(trimmed),
        "customers": trimmed,
    }


def my_loans(user=None, **_):
    """Loan position for the signed-in relationship manager's book."""
    code = sales_code_of(user)
    if not code:
        return _no_code()

    out = {"sales_code": code, "scope": "this user's own book only"}
    try:
        rows = list(svc.loan_trends_data(code) or [])
        # The current month has no month-end column yet. Reporting a partial
        # total next to complete ones is what made the RM trend chart look
        # like the loan book had collapsed, so it is not done here either.
        out["loan_rows"] = len(rows)
        out["note"] = ("Month-end balances only. The current month is not "
                       "closed and is deliberately not reported as a total.")
    except Exception as exc:  # noqa: BLE001
        out["loan_rows"] = {"error": str(exc)[:200]}

    try:
        arrears = list(svc.loans_arrears_by_sales_code(code) or [])
        out["arrears"] = {
            "accounts": len(arrears),
            "total": sum(_num(r.get("arrears") or r.get("arrears_amount"))
                         for r in arrears),
            "worst": sorted(
                ({"customer": r.get("customer_name") or r.get("latin_surname"),
                  "arrears": _num(r.get("arrears") or r.get("arrears_amount"))}
                 for r in arrears),
                key=lambda r: -r["arrears"])[:10],
        }
    except Exception as exc:  # noqa: BLE001
        out["arrears"] = {"error": str(exc)[:200]}
    return out


TOOL_DEFINITIONS = [
    {
        "name": "get_my_portfolio",
        "description": (
            "The SIGNED-IN USER'S OWN portfolio: their customers, deposits, "
            "loans, revenue and arrears, scoped to their sales code.\n\n"
            "Use this for any question phrased as 'my portfolio', 'my book', "
            "'my customers', 'my performance' or 'how am I doing'. It is NOT "
            "the mortgage module and NOT bank-wide — it is this person's own "
            "allocated book from the warehouse, which is what a relationship "
            "manager means by 'my portfolio'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_my_customers",
        "description": (
            "The customers allocated to the signed-in user, with each one's "
            "deposits, loans and revenue. Use for 'my customers', 'who is in "
            "my book', 'my top clients'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer",
                          "description": "How many customers to return, up to 100."},
            },
        },
    },
    {
        "name": "get_my_loans",
        "description": (
            "The signed-in user's loan book and arrears, including the worst "
            "arrears positions. Use for 'my loans', 'my arrears', 'which of my "
            "customers are behind'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

#: These receive the signed-in user. ``run_tool`` passes it; nothing else does.
DISPATCH = {
    "get_my_portfolio": my_portfolio,
    "get_my_customers": my_customers,
    "get_my_loans": my_loans,
}
