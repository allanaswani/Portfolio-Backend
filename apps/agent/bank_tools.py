"""One customer, one branch, and where we sit against the rest of the market.

Three gaps, all in the same request. The assistant could return the mortgage
book (``list_borrowers``) or the caller's own book (``get_my_customers``), but
nothing answered "tell me about *this* customer", "how is *that* branch doing",
or "where are we against the competition".

**Scope is enforced here, in the queryset.** An officer sees their own book, a
team leader their segment, a branch manager their branch, and management sees
anybody. That is a boundary, not a preference, so it cannot live in a prompt:
the model decides which tool to call, never how much it is allowed to see.

Everything internal reads :class:`CustomerAllocationBase` — the reallocation
base, one row per ``cust_id`` because that column is unique. That matters:
joining ``retail_allocated_portfolio`` instead fans out and inflates every
money figure, which has bitten this codebase twice.

The market table is different in kind. Nothing in this warehouse knows what
another bank is worth, so :class:`BankingSectorPosition` holds what CBK
publishes quarterly. Until somebody loads it, the tool says so in words rather
than returning an empty series that reads as "we have no competitors".
"""

from decimal import Decimal

from django.db.models import Count, Q, Sum

#: Groups that see the whole bank. Named explicitly rather than derived from a
#: tier, so widening this is a visible, reviewable edit to one line.
BANK_WIDE_GROUPS = {
    "ceo",
    "exco",
    "portfolio_mgt",
    "collection_mgt",
    "business_performance",
}
#: Sees their own branch only.
BRANCH_GROUPS = {"branch_portfolio"}
#: Sees their own segment only.
SEGMENT_GROUPS = {"tl_portfolio", "tl_collection"}

MAX_ROWS = 200


def _profile(user):
    try:
        return user.profile
    except Exception:  # noqa: BLE001 — no profile row is a normal state
        return None


def scope_of(user):
    """How much of the bank this person may see.

    Returns a dict with ``level`` and the key to filter on. ``level`` is one of
    ``all``, ``branch``, ``segment``, ``rm`` or ``none``. ``none`` means the
    account has nothing to scope by, and the tools refuse rather than widening
    to everything — an unscoped answer that looks scoped is worse than none.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return {"level": "none", "reason": "not signed in"}
    if getattr(user, "is_superuser", False):
        return {"level": "all", "as": "superuser"}

    groups = set(user.groups.values_list("name", flat=True))
    if groups & BANK_WIDE_GROUPS:
        return {"level": "all", "as": sorted(groups & BANK_WIDE_GROUPS)[0]}

    prof = _profile(user)
    if groups & BRANCH_GROUPS:
        branch = (getattr(prof, "branch", "") or "").strip()
        if not branch:
            return {"level": "none", "reason": "no branch on this profile"}
        return {"level": "branch", "branch": branch}

    if groups & SEGMENT_GROUPS:
        segment = (getattr(prof, "segment", "") or "").strip()
        if not segment:
            return {"level": "none", "reason": "no segment on this profile"}
        return {"level": "segment", "segment": segment}

    code = (getattr(prof, "sales_code", "") or "").strip()
    if not code:
        return {"level": "none", "reason": "no sales code on this profile"}
    return {"level": "rm", "sales_code": code}


def _scoped_queryset(user):
    """The customer base this person is allowed to read, or ``(None, reason)``."""
    from apps.portfolio_management_enrichment.models import CustomerAllocationBase

    scope = scope_of(user)
    qs = CustomerAllocationBase.objects.all()
    level = scope["level"]

    if level == "all":
        return qs, scope
    if level == "branch":
        # Branch names are held two ways on this table; match either.
        return qs.filter(Q(customer_branch_name__iexact=scope["branch"])
                         | Q(rm_branch_name__iexact=scope["branch"])), scope
    if level == "segment":
        # Never compare a segment with '=': BUSINESS BANKING, SME and SMALL/
        # MEDIUM ENTERPRISES are the same thing spelled three ways.
        from core.segments import segment_synonyms

        names = segment_synonyms(scope["segment"])
        if not names:
            return None, scope
        return qs.filter(Q(segment__in=names) | Q(main_segment__in=names)), scope
    if level == "rm":
        return qs.filter(rm_code__iexact=scope["sales_code"]), scope
    return None, scope


def _refused(scope):
    return {
        "error": "out_of_scope",
        "detail": (
            f"This account cannot be scoped to a book ({scope.get('reason')}), "
            "so there is nothing it may be shown. That is an Administration "
            "setting on the user's profile, not something they can fix. Say so "
            "plainly and do not substitute a bank-wide figure."
        ),
    }


def _money(value):
    return float(value) if isinstance(value, Decimal) else (value or 0)


# ── One customer ─────────────────────────────────────────────────────────────

def get_customer(user=None, query="", **_):
    """Everything known about one customer, within what the caller may see."""
    query = (query or "").strip()
    if not query:
        return {"error": "A customer id, account number or name is required."}

    qs, scope = _scoped_queryset(user)
    if qs is None:
        return _refused(scope)

    # An exact cust_id wins; otherwise treat it as a name fragment.
    match = qs.filter(cust_id__iexact=query)
    if not match.exists():
        match = qs.filter(customer_name__icontains=query)

    total = match.count()
    if total == 0:
        return {
            "found": 0,
            "query": query,
            "scope": scope["level"],
            "detail": (
                "No customer matching that, within what this user may see. "
                "They may exist but belong to another book."
            ),
        }

    rows = [{
        "cust_id": c.cust_id,
        "customer_name": c.customer_name,
        "segment": c.main_segment or c.segment,
        "branch": c.customer_branch_name,
        "aum": _money(c.aum_cust_id),
        "group_aum": _money(c.aum_group),
        "rm_name": c.rm_name,
        "rm_code": c.rm_code,
        "rm_branch": c.rm_branch_name,
        "interest_income": _money(c.interest_income),
        "non_funded_income": _money(c.nfi),
        "interest_expense": _money(c.interest_expense),
        "net_after_expense": _money(c.net_after_expense),
    } for c in match.order_by("-aum_cust_id")[:25]]

    return {
        "found": total,
        "query": query,
        "scope": scope["level"],
        "showing": len(rows),
        "customers": rows,
    }


# ── One branch, or all of them ───────────────────────────────────────────────

def get_branch_performance(user=None, branch=None, limit=40, **_):
    """Customers, AUM and income per branch, ranked."""
    qs, scope = _scoped_queryset(user)
    if qs is None:
        return _refused(scope)

    if branch:
        qs = qs.filter(customer_branch_name__icontains=str(branch).strip())

    try:
        limit = max(1, min(int(limit), MAX_ROWS))
    except (TypeError, ValueError):
        limit = 40

    rows = (qs.values("customer_branch_name")
              .annotate(customers=Count("cust_id", distinct=True),
                        aum=Sum("aum_cust_id"),
                        interest_income=Sum("interest_income"),
                        non_funded_income=Sum("nfi"),
                        net_after_expense=Sum("net_after_expense"))
              .order_by("-aum")[:limit])

    out = [{
        "branch": r["customer_branch_name"] or "Unassigned",
        "customers": r["customers"],
        "aum": _money(r["aum"]),
        "interest_income": _money(r["interest_income"]),
        "non_funded_income": _money(r["non_funded_income"]),
        "net_after_expense": _money(r["net_after_expense"]),
    } for r in rows]

    return {
        "scope": scope["level"],
        "branches": len(out),
        "total_aum": sum(r["aum"] for r in out),
        "results": out,
    }


# ── Where we sit in the market ───────────────────────────────────────────────

METRICS = {
    "assets": "total_assets",
    "deposits": "total_deposits",
    "loans": "total_loans",
    "profit": "profit_before_tax",
    "market_share": "market_share_pct",
}


def get_market_position(period=None, metric="deposits", limit=20, **_):
    """HF Group against the rest of the Kenyan banking sector, per CBK."""
    from apps.business_performance.models import BankingSectorPosition

    column = METRICS.get((metric or "deposits").lower())
    if column is None:
        return {"error": f"metric must be one of {sorted(METRICS)}."}

    qs = BankingSectorPosition.objects.all()
    if not qs.exists():
        return {
            "error": "no_sector_data",
            "detail": (
                "No banking sector figures have been loaded yet, so there is "
                "nothing to compare against. CBK publishes these quarterly and "
                "they load into bp_banking_sector_position. Say plainly that "
                "the comparison is unavailable and do not estimate it."
            ),
        }

    if period:
        qs = qs.filter(period=str(period).strip())
    else:
        period = qs.order_by("-period").values_list("period", flat=True).first()
        qs = qs.filter(period=period)

    qs = qs.exclude(**{f"{column}__isnull": True}).order_by(f"-{column}")
    try:
        limit = max(1, min(int(limit), MAX_ROWS))
    except (TypeError, ValueError):
        limit = 20

    rows = []
    for rank, bank in enumerate(qs[:limit], start=1):
        rows.append({
            "rank": rank,
            "bank_name": bank.bank_name,
            "is_us": bank.is_us,
            "tier": bank.tier,
            "value": _money(getattr(bank, column)),
            "market_share_pct": _money(bank.market_share_pct),
            "npl_ratio_pct": _money(bank.npl_ratio_pct),
        })

    ours = next((r for r in rows if r["is_us"]), None)
    return {
        "period": period,
        "metric": metric,
        "measured": column,
        "banks": len(rows),
        "our_rank": ours["rank"] if ours else None,
        "our_value": ours["value"] if ours else None,
        "results": rows,
    }


TOOL_DEFINITIONS = [
    {
        "name": "get_customer",
        "description": (
            "Everything the bank knows about ONE customer — AUM, segment, "
            "branch, their relationship manager, and the income they generate. "
            "Accepts a customer id, or part of a name. Automatically limited to "
            "what the signed-in person is allowed to see, so an empty result "
            "can mean the customer belongs to somebody else's book."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Customer id, or part of the name."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_branch_performance",
        "description": (
            "Customers, assets under management and income for each branch, "
            "ranked by AUM. Omit 'branch' for the league table across every "
            "branch the signed-in person may see; give it to focus on one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string",
                           "description": "Branch name, or part of it. Omit for all."},
                "limit": {"type": "integer",
                          "description": "How many branches to return. Default 40."},
            },
        },
    },
    {
        "name": "get_market_position",
        "description": (
            "Where HF Group sits against every other Kenyan bank, from the "
            "figures CBK publishes each quarter: assets, deposits, loans, "
            "profit before tax or market share, ranked, with our own row "
            "flagged. This is the ONLY source of competitor figures — no other "
            "tool knows anything about another bank."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string",
                           "description": "CBK period such as '2026-Q2'. Omit for the latest."},
                "metric": {"type": "string",
                           "enum": sorted(METRICS),
                           "description": "Which measure to rank on. Default deposits."},
                "limit": {"type": "integer", "description": "How many banks. Default 20."},
            },
        },
    },
]

#: get_customer and get_branch_performance are scoped to the caller, so they
#: receive the user. get_market_position is public information and does not.
DISPATCH = {
    "get_customer": get_customer,
    "get_branch_performance": get_branch_performance,
    "get_market_position": lambda user=None, **kw: get_market_position(**kw),
}
