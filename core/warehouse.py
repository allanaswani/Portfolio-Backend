"""Reading warehouse tables that have no ``id`` column.

Several warehouse aggregates are built by the ETL with only the columns they
aggregate — no surrogate key. Django adds an implicit ``id`` to any model that
declares no primary key, and from then on **every query for a model instance
selects a column that is not there**:

    django.db.utils.ProgrammingError: column ceo_deposit_movement_daily.id
    does not exist

``manage.py check_warehouse_columns`` lists them. There are eight.

The obvious fix — declare one of the real columns as the primary key — is
wrong here. These are aggregate rows keyed by things like *segment + month*;
no single column is unique, and telling Django otherwise is a lie the ORM
will eventually act on.

So they are read as dictionaries instead. ``.values()`` is the only way to
stop Django selecting the primary key, and it asserts nothing about the table
that is not true.

DRF serialises these rows unchanged: ``get_attribute`` handles a Mapping as
happily as a model instance, so a serializer with explicit ``fields`` (never
``"__all__"``, which would put the phantom id back in the payload) works
against them.
"""


def real_field_names(model):
    """Every field the table actually has, in declaration order.

    Excludes a primary key Django invented; keeps one the model really
    declares, since that column does exist.
    """
    pk = model._meta.pk
    invented = pk is not None and pk.auto_created
    return [
        f.name for f in model._meta.concrete_fields
        if not (invented and f is pk)
    ]


def rows(model, *only):
    """A queryset of dicts holding only columns the table really has.

    Pass field names to narrow it further; the default is everything real.
    """
    fields = list(only) or real_field_names(model)
    return model.objects.values(*fields)
