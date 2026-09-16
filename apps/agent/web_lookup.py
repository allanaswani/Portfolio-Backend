"""Outward-facing lookups for the assistant: web search, and fetching a page.

Every other tool the assistant has reads this bank's own warehouse. That makes
it useless for the questions Strategy are actually asked most often — the CBK
base rate this week, what a competitor announced, what is in the new Finance
Act. This closes that gap, and nothing else.

**It is dormant unless ``TINYFISH_API_KEY`` is set.** No key, no tool: the two
definitions are not even offered to the model, so it cannot try and fail. That
is deliberate — the code ships ready and nothing leaves the bank until somebody
deliberately turns it on.

## Why there is a guard on the query

The model composes the search string. Nothing in a prompt stops it writing
"deposit balance for customer 1110801" into a query that then leaves the bank to
a third party — and a prompt instruction is guidance, not a control. For a
CBK-regulated bank that is a compliance event rather than a bug, so the check
lives here, server-side, and refuses rather than redacts: a silently trimmed
query returns results for a question nobody asked.

What it blocks is anything that looks like it identifies a person or an account.
It cannot be complete — no such check is — so it is deliberately blunt, and the
tool description tells the model plainly that external lookups are for public
information only.

## What is deliberately NOT here

TinyFish also offers Browser and Agent APIs that drive real websites. A bank's
backend automating live third-party sites is a risk with no business case here,
so those are not wired up and should not be without a separate decision.
"""

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"

#: Kept short. This sits inside the assistant's reply loop, and a slow third
#: party must not hold a user's question open.
TIMEOUT_SECONDS = 12
MAX_RESULTS = 8
#: Page text is trimmed before it reaches the model — a whole article would
#: crowd out the bank's own data in the same context window.
MAX_PAGE_CHARS = 6000


def enabled() -> bool:
    return bool(str(getattr(settings, "TINYFISH_API_KEY", "") or "").strip())


# ── The guard ────────────────────────────────────────────────────────────────

#: Anything that looks like it names a person or an account. Blunt on purpose:
#: a false refusal costs one retry with a better query, a false pass sends a
#: customer identifier to a third party.
_IDENTIFIER_PATTERNS = [
    (re.compile(r"\b\d{6,}\b"),
     "a long number that could be a customer, account or ID number"),
    (re.compile(r"\b(?:cust(?:omer)?[_\s-]?(?:id|no|number)|account[_\s-]?(?:no|number)"
                r"|acc[_\s-]?no|id[_\s-]?no|pf[_\s-]?(?:no|number)|kra[_\s-]?pin"
                r"|sales[_\s-]?code|cif)\b", re.I),
     "a field name that identifies a customer or member of staff"),
    (re.compile(r"\b[A-Z]{1,3}\d{6,}[A-Z]?\b"),
     "something shaped like an ID or PIN"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an email address"),
    (re.compile(r"\b(?:\+?254|0)7\d{8}\b"), "a phone number"),
    (re.compile(r"\bHFC?B?/(?:GTE|ELC)/", re.I),
     "a trade finance reference, which names a customer's instrument"),
]


def check_query(text):
    """``None`` if this may leave the bank, else the reason it may not."""
    probe = str(text or "")
    for pattern, reason in _IDENTIFIER_PATTERNS:
        if pattern.search(probe):
            return reason
    return None


def _refusal(reason):
    return {
        "error": "refused",
        "reason": (
            f"That query contains {reason}. External lookups leave the bank and "
            f"go to a third party, so they are for PUBLIC information only — "
            f"market rates, regulation, competitors, general knowledge. Ask the "
            f"internal tools for anything about a customer, an account or a "
            f"member of staff."
        ),
    }


# ── The calls ────────────────────────────────────────────────────────────────

def _request(url, *, method="GET", payload=None):
    """One HTTP call. Returns parsed JSON, or a dict with ``error``.

    Never raises. The assistant answers from the bank's own data most of the
    time, and a third party being down must degrade one tool rather than fail
    the whole reply.
    """
    key = str(getattr(settings, "TINYFISH_API_KEY", "") or "").strip()
    if not key:
        return {"error": "External lookup is not configured on this server."}

    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("X-API-Key", key)
    request.add_header("X-TF-Request-Origin", "api")
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        # The status is the useful part; the body may be an HTML error page.
        log.warning("tinyfish %s -> HTTP %s", url, exc.code)
        return {"error": f"The external lookup service returned HTTP {exc.code}."}
    except Exception as exc:  # noqa: BLE001 — timeout, DNS, TLS, bad JSON
        log.warning("tinyfish %s failed: %s", url, exc)
        return {"error": "The external lookup service could not be reached."}


def search(query, limit=MAX_RESULTS):
    """Public web search. Returns ranked results, or an ``error`` dict."""
    refused = check_query(query)
    if refused:
        return _refusal(refused)

    params = urllib.parse.urlencode(
        {"query": str(query or "").strip(), "location": "KE", "language": "en"})
    data = _request(f"{SEARCH_URL}?{params}")
    if "error" in data:
        return data

    try:
        limit = max(1, min(MAX_RESULTS, int(limit)))
    except (TypeError, ValueError):
        limit = MAX_RESULTS

    rows = data.get("results") or []
    return {
        "query": data.get("query", query),
        "source": "web search (external)",
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "site": r.get("site_name", ""),
                "snippet": r.get("snippet", ""),
            }
            for r in rows[:limit]
        ],
    }


def fetch_page(url):
    """Fetch one public page as clean text."""
    address = str(url or "").strip()
    if not address.lower().startswith(("http://", "https://")):
        return {"error": "Give a full http(s) URL."}
    refused = check_query(address)
    if refused:
        return _refusal(refused)

    data = _request(FETCH_URL, method="POST", payload={"url": address})
    if "error" in data:
        return data

    text = ""
    for field in ("content", "text", "markdown", "body"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            text = value
            break
    truncated = len(text) > MAX_PAGE_CHARS
    return {
        "url": address,
        "title": data.get("title", ""),
        "source": "web page (external)",
        "content": text[:MAX_PAGE_CHARS],
        "truncated": truncated,
    }


# ── Tool definitions, offered only when the key is set ───────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_the_web",
        "description": (
            "Search the public web for information that is NOT in the bank's own "
            "systems: market rates, CBK or regulatory announcements, competitor "
            "news, general knowledge, current events.\n\n"
            "PUBLIC INFORMATION ONLY. The query leaves the bank and goes to a "
            "third-party service, so it must never contain a customer name, "
            "account number, ID number, PF number, phone number, email address "
            "or trade finance reference. For anything about a customer, an "
            "account or a member of staff, use the internal tools instead — they "
            "read the bank's own data and nothing leaves.\n\n"
            "Returns ranked results with a title, URL and snippet. Use "
            "fetch_web_page to read one in full. Always tell the user when an "
            "answer came from the web rather than from the bank's data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Public-information search terms.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"How many results, up to {MAX_RESULTS}.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_web_page",
        "description": (
            "Read one public web page as text, usually a URL returned by "
            "search_the_web. External and public pages only — never an internal "
            "system. Long pages are truncated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full http(s) URL."},
            },
            "required": ["url"],
        },
    },
]

DISPATCH = {
    "search_the_web": lambda **kw: search(
        kw.get("query"), kw.get("limit", MAX_RESULTS)),
    "fetch_web_page": lambda **kw: fetch_page(kw.get("url")),
}
