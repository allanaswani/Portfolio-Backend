"""Resolve the names a Feedback Log shows, in one place.

``Feedback`` stores ``cust_id`` and ``sales_code``. Every Feedback Log in the
application — RM, TL, branch, EXCO — renders a **Customer** and an **RM Name**
column, so every one of them has to turn those two ids into names.

Only the branch log ever did. The others rendered dashes, because the fix was
written into one view instead of somewhere all four could reach. This is that
somewhere: a mixin a list view drops in, so the next feedback list gets it
without anybody remembering to.

Both lookups are batched over the page being returned, not resolved per row —
a Feedback Log is a few hundred rows and an N+1 here is a few hundred queries.
"""

from rest_framework.response import Response


def resolve_names(rows):
    """``(cust_names, rm_names)`` for a batch of feedback rows.

    Customer names come from ``hf_customer``; RM names from
    ``retail_allocated_portfolio``, which is the table that maps a sales code to
    the person holding it.
    """
    from django.db import router as db_router

    from apps.portfolio.models import HfCustomer, RetailAllocatedPortfolio

    # The router reads unmanaged models from ``datawarehouse`` and returns None
    # for their writes, which falls through to ``default``. On production the
    # two aliases are the same database, so the split is invisible — and the
    # write alias is the one a test can reach. Same pinning as
    # ``employee_master_views.employee_db``.
    alias = db_router.db_for_write(HfCustomer) or "default"

    cust_ids = {int(r.cust_id) for r in rows if r.cust_id is not None}
    sales_codes = {r.sales_code for r in rows if r.sales_code}

    cust_names = {}
    if cust_ids:
        cust_names = {
            int(cid): name
            for cid, name in HfCustomer.objects.using(alias)
            .filter(cust_id__in=cust_ids)
            .values_list("cust_id", "latin_surname")
        }

    rm_names = {}
    if sales_codes:
        # retail_allocated_portfolio has no unique cust_id and repeats a sales
        # code once per customer, so this is deliberately a dict comprehension
        # over the pairs — the last write wins and the map holds one name per
        # code rather than a row per allocation.
        rm_names = {
            code: name
            for code, name in RetailAllocatedPortfolio.objects.using(alias)
            .filter(sales_code__in=sales_codes)
            .values_list("sales_code", "rm_name")
            if name
        }
    return cust_names, rm_names


class FeedbackNamesMixin:
    """Give a feedback ``ListAPIView`` its customer and RM names.

    Use with :class:`~apps.portfolio.serializers.NamedFeedbackSerializer`.
    Works paginated or not.
    """

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)

        cust_names, rm_names = resolve_names(rows)
        ctx = self.get_serializer_context()
        ctx.update({"cust_names": cust_names, "rm_names": rm_names})

        serializer = self.get_serializer(rows, many=True, context=ctx)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
