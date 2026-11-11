"""Whether a customer is active: from their last transaction, not a flag.

``hf_customer.active`` is set upstream and does not follow transactions. On
11 Nov 2026 a customer who had transacted on 5 Nov showed Inactive on the
customer lists. ``customer_last_transaction`` (filled daily by
``load_activity_from_transactions --only-last-transaction``) holds each
customer's last transaction, so a customer is active when that falls inside
ACTIVE_DAYS - the window the branch page's activity section opens on.
"""

#: A customer who transacted in this many days is active.
ACTIVE_DAYS = 30


def active_sql(alias="hf_customer"):
    """A WHERE condition true for a customer of ``alias`` who is active."""
    return (f"EXISTS (SELECT 1 FROM customer_last_transaction clt "
            f"WHERE clt.cust_id = {alias}.cust_id "
            f"AND clt.last_txn::date >= CURRENT_DATE - {ACTIVE_DAYS})")


def active_count(queryset):
    """How many customers in an HfCustomer queryset are active."""
    return queryset.extra(where=[active_sql("hf_customer")]).count()
