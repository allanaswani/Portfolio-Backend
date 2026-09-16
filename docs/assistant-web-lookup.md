# Assistant — external web lookup

`apps/agent/web_lookup.py`. Two extra tools for the AI assistant: a public web
search, and fetching one page as text. Provided by TinyFish.

**Off by default. It does nothing until `TINYFISH_API_KEY` is set, and setting
it is a deliberate act that needs Compliance and Security sign-off.**

## Why

Every other tool the assistant has — all nineteen — reads this bank's own
warehouse. That makes it useless for the questions Strategy are actually asked
most: the CBK rate this week, what a competitor announced, what is in the new
Finance Act. These two tools close that gap and nothing else.

## The control that matters

The model composes the search string. Nothing in a prompt stops it writing
`deposit balance for customer 1110801` into a query that then leaves the bank to
a third party — **a prompt instruction is guidance, not a control.**

So the check is server-side, in `check_query()`, and it **refuses rather than
redacts**: a silently trimmed query returns results for a question nobody asked.
Refused shapes:

| Blocked | Example |
|---|---|
| Any number of 6+ digits | `1110801`, `34399249` |
| Identifier field names | `cust_id`, `account_no`, `PF number`, `KRA PIN`, `sales_code`, `CIF` |
| ID/PIN shapes | `A012345678B` |
| Email addresses | `stacy.mwenda@hfgroup.co.ke` |
| Kenyan phone numbers | `0712345678`, `+254712345678` |
| Trade finance references | `HFCB/GTE/260630/01` |

It is deliberately blunt and cannot be complete — no such check is. A false
refusal costs the model one retry with a better query; a false pass sends a
customer identifier to a third party. The refusal text tells the model to use
the internal tools instead, so it can act on it rather than retry identically.

Both the URL and the query go through the guard — a URL can carry an identifier
in its path just as easily.

## What is deliberately not wired up

TinyFish also offers **Browser** and **Agent** APIs that drive real websites.
A bank's backend automating live third-party sites is a risk with no business
case here. Not built, and not to be without a separate decision.

## Behaviour

- **Dormant with no key.** The tool definitions are not offered to the model at
  all, so it cannot try and fail. `tool_definitions()` decides this at call
  time, not at import, because it is configuration rather than code.
- **Refuses if the key is removed later**, even for a model that was handed the
  definition earlier in a conversation.
- **Never raises.** A timeout, a 5xx or bad JSON degrades that one tool; the
  assistant still answers from the bank's own data.
- **12-second timeout.** It sits inside the reply loop and a slow third party
  must not hold a user's question open.
- **Pages truncated to 6,000 characters** — a whole article would crowd the
  bank's own figures out of the same context window.
- **Results are labelled `"source": "…(external)"`** and the tool description
  tells the model to say when an answer came from the web rather than from the
  bank's data.
- **The key travels in the `X-API-Key` header**, never the query string, so it
  does not land in proxy and access logs. There is a test for that.

## Turning it on

```bash
# /etc/hf/prod.env
TINYFISH_API_KEY=sk-tinyfish-...
```

Then restart the backend. Confirm:

```bash
docker exec hf-backend python manage.py shell -c \
"from apps.agent import agent_tools, web_lookup; \
print('enabled:', web_lookup.enabled(), '| tools:', len(agent_tools.tool_definitions()))"
```

Nineteen tools with it off, twenty-one with it on.

To turn it off again, remove the variable and restart. No code change, no
deployment.

## Before it is enabled

1. Does Compliance accept outbound queries to a third-party processor from the
   assistant?
2. Is there a data-processing agreement? The Search and Fetch APIs are free,
   which usually means no DPA and no SLA.
3. Does Security need to approve a new external egress from the backend
   container?

The code is ready and inert until those are answered.

## Endpoints used

| | |
|---|---|
| Search | `GET https://api.search.tinyfish.ai?query=&location=KE&language=en` |
| Fetch | `POST https://api.fetch.tinyfish.ai` with `{"url": "..."}` |

Docs: <https://docs.tinyfish.ai/>
