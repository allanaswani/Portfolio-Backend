"""Everything a collections officer needs about one customer, in one read.

The customer page carried four tiles and an empty Account Details box: the
front end was reading ``loan_product``, ``loan_type``, ``branch_code`` and
``bucket``, and the API returned none of them, so all four printed a dash. It
also showed "# Contacts 0" where that count was the number of DIARY entries,
not the customer's phone numbers - a customer you have never called is not a
customer with no number.

What this returns and where each part comes from
────────────────────────────────────────────────
``bio``        ``customers`` - the customer master. Name, date of birth,
               gender, national ID, when they joined, segment, branch.
``contacts``   the same table: phone, other phones, e-mail. These are the
               numbers an officer actually dials, and they were nowhere on
               the page.
``loans``      ``loans``, a row per account: product, status, branch,
               outstanding, arrears, days past due, the instalment and when
               it is next due, and both officers the core system records.
``collateral`` ``product_mapping`` on the product code. Collateral is a
               property of the PRODUCT in this estate - there is no per-loan
               security table in the warehouse - so a mortgage reads
               "PROPERTY" because that is what that product is secured on.
``totals``     summed over the loans, so the tiles and the table agree.

Every read is wrapped: a warehouse table that is absent or slow costs its own
section and not the whole page. An officer who can see the phone number but
not the collateral can still make the call.
"""

from __future__ import annotations

#: The buckets the page shows, in order. ``None`` is an open upper bound.
#: One definition, used for the figure AND the label, so the tile and the
#: classification cannot disagree - they were computed separately before.
BUCKETS = (
    ("current", "Current (0)", 0, 0),
    ("1_30", "1-30 Days", 1, 30),
    ("31_60", "31-60 Days", 31, 60),
    ("61_90", "61-90 Days", 61, 90),
    ("npl", "90+ Days (NPL)", 91, None),
)


def bucket_for(days):
    """Days past due → ``(key, label)``. Never guesses: no days, no bucket."""
    if days is None:
        return "", ""
    days = int(days)
    for key, label, low, high in BUCKETS:
        if days >= low and (high is None or days <= high):
            return key, label
    return "", ""


def _rows(sql, params):
    """Run one read → list of dicts, or [] if the feed is not there.

    Each section gets its own cursor and its own savepoint. Postgres aborts
    the whole transaction on a failed statement, so without one an absent
    warehouse column would take down every later section too and the page
    would come back empty rather than partly filled.
    """
    from django.db import connection, transaction

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, params)
            columns = [c[0] for c in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001 - a missing feed costs its own section
        return []


def bio_and_contacts(cust_id):
    """The customer master row → ``(bio, contacts)``.

    ``other_phone_numbers`` is free text in the source - officers type in
    whatever they were given - so it is split on the separators that actually
    appear rather than assumed to be one number.
    """
    rows = _rows(
        """
        SELECT firstname, middlename, lastname, dob, gender, national_id,
               phone_number, other_phone_numbers, email, open_date, branch,
               type, status, segment
        FROM customers
        WHERE cust_id = %s
        LIMIT 1
        """, [cust_id])
    if not rows:
        return {}, {}

    row = rows[0]
    name = " ".join(part for part in (row.get("firstname"),
                                      row.get("middlename"),
                                      row.get("lastname")) if part)

    others = []
    for chunk in str(row.get("other_phone_numbers") or "").replace(
            ";", ",").replace("/", ",").split(","):
        chunk = chunk.strip()
        if chunk and chunk.lower() not in ("none", "null", "-"):
            others.append(chunk)

    numbers = [n for n in [str(row.get("phone_number") or "").strip()]
               if n] + others

    bio = {
        "name": name, "date_of_birth": row.get("dob"),
        "gender": row.get("gender"), "national_id": row.get("national_id"),
        "customer_since": row.get("open_date"), "branch": row.get("branch"),
        "customer_type": row.get("type"), "status": row.get("status"),
        "segment": row.get("segment"),
    }
    contacts = {
        "phone": row.get("phone_number"),
        "other_phones": others,
        "email": row.get("email"),
        # The count the page should show: numbers on file, not calls made.
        "count": len([n for n in numbers if n]) + (1 if row.get("email") else 0),
        "reachable": bool(numbers or row.get("email")),
    }
    return bio, contacts


def loans_for(cust_id):
    """Every loan this customer holds, with its collateral → list of dicts.

    ``product_mapping`` carries the collateral for a product code, which is
    where collateral lives in this estate - there is no per-loan security
    table. LEFT JOINed, so a product the mapping has not caught up with
    still returns its loan rather than dropping it.
    """
    rows = _rows(
        """
        SELECT l.loan_account_no, l.account_no, l.loan_product,
               l.status, l.sector, l.branch,
               l.euro_book_balance        AS outstanding,
               l.total_arrears, l.days_in_arrears, l.overdue_days,
               l.capital_balance, l.interest_arrears,
               l.installment_amount, l.next_installment_date,
               l.last_transaction_date, l.penalty_interest_rate,
               l.insurance, l.open_date, l.expiry_date,
               l.delay_officer, l.account_officer,
               pm.product_description, pm.loan_collateral
        FROM loans l
        LEFT JOIN product_mapping pm
               ON TRIM(pm.code::text) = TRIM(l.loan_product::text)
        WHERE l.cust_id = %s
        ORDER BY l.days_in_arrears DESC NULLS LAST, l.euro_book_balance DESC
        """, [cust_id])

    for row in rows:
        days = row.get("days_in_arrears") or row.get("overdue_days")
        key, label = bucket_for(days)
        row["bucket"] = key
        row["bucket_label"] = label
        row["days_past_due"] = days
        # The product's own words where the mapping has them, the code
        # otherwise - a loan that prints "40046" tells an officer nothing.
        row["product"] = (row.get("product_description")
                          or row.get("loan_product") or "")
        row["collateral"] = row.get("loan_collateral") or ""
    return rows


def key_dates(cust_id, loans):
    """The dates an officer works an account to → a list of rows.

    A collections call turns on dates: when the next instalment falls, when
    they last actually paid, what they promised and whether that day has
    passed. Those were spread across three feeds and none of them was on the
    page, so an officer had to hold them in their head or go and look.

    Each row is ``{label, date, note}`` and a date the feed does not have is
    left out rather than shown as a dash - a list of dashes is not a list of
    dates.
    """
    import datetime

    from .models import Collection, PromiseToPay

    today = datetime.date.today()
    rows = []

    def day(value):
        return value.date() if hasattr(value, "date") else value

    def add(label, value, note=""):
        value = day(value)
        if value:
            rows.append({"label": label, "date": value, "note": note})

    if loans:
        worst = loans[0]
        add("Next instalment due", worst.get("next_installment_date"))
        add("Last payment received", worst.get("last_transaction_date"))
        add("Loan opened", worst.get("open_date"))
        add("Loan matures", worst.get("expiry_date"))

    promise = (PromiseToPay.objects
               .filter(cust_id=cust_id)
               .order_by("-promised_date").first())
    if promise is not None and promise.promised_date:
        overdue = promise.promised_date < today
        add("Promised to pay", promise.promised_date,
            note=(f"{promise.promised_amount:,.0f} - "
                  + ("still open" if promise.status == PromiseToPay.STATUS_OPEN
                     else promise.get_status_display().lower())
                  + (", that day has passed" if overdue
                     and promise.status == PromiseToPay.STATUS_OPEN else "")))

    entry = (Collection.objects
             .filter(cust_id=cust_id)
             .order_by("-recording_date").first())
    if entry is not None:
        add("Last contacted", entry.recording_date,
            note=(entry.contactibility or "").strip())
        add("Next action due", entry.next_action_date,
            note=(entry.next_action or "").strip())

    # Soonest first among the dates still ahead, then the past, most recent
    # first - which is the order an officer reads them in.
    ahead = sorted((r for r in rows if r["date"] >= today),
                   key=lambda r: r["date"])
    behind = sorted((r for r in rows if r["date"] < today),
                    key=lambda r: r["date"], reverse=True)
    for row in ahead:
        row["when"] = "ahead"
        row["days"] = (row["date"] - today).days
    for row in behind:
        row["when"] = "past"
        row["days"] = (today - row["date"]).days
    return ahead + behind


def profile(cust_id):
    """The whole page in one call.

    ``has_customer`` is False only when the customer master has no row for
    this id. A customer with no LOANS is still a customer - they may have
    just cleared - and the page should say that rather than 404.
    """
    bio, contacts = bio_and_contacts(cust_id)
    loans = loans_for(cust_id)

    def total(field):
        return sum(float(row.get(field) or 0) for row in loans)

    worst = max((row.get("days_past_due") or 0) for row in loans) if loans else 0
    key, label = bucket_for(worst if loans else None)

    outstanding = total("outstanding")
    arrears = total("total_arrears")

    # The officers the core system records against the loans. A customer with
    # two loans can sit with two officers, so both are reported rather than
    # one being picked arbitrarily.
    officers = sorted({(row.get("delay_officer") or "").strip()
                       for row in loans} - {""})
    collaterals = sorted({(row.get("collateral") or "").strip()
                          for row in loans} - {""})
    products = sorted({(row.get("product") or "").strip()
                       for row in loans} - {""})

    return {
        "cust_id": cust_id,
        "has_customer": bool(bio),
        "bio": bio,
        "contacts": contacts,
        "loans": loans,
        # The dates an officer works the account to, gathered from the loan,
        # the promise and the diary - see ``key_dates``.
        "dates": key_dates(cust_id, loans),
        "products": products,
        "collateral": collaterals,
        "delay_officers": officers,
        "totals": {
            "outstanding": outstanding,
            "total_arrears": arrears,
            "days_past_due": worst,
            "bucket": key,
            "bucket_label": label,
            "loans": len(loans),
            # The ratio the page prints in red. Guarded, because a cleared
            # loan leaves a zero balance and a division by it.
            "arrears_ratio": (round(arrears / outstanding, 4)
                              if outstanding else None),
        },
        "buckets": [{"key": k, "label": lab} for k, lab, _lo, _hi in BUCKETS],
    }
