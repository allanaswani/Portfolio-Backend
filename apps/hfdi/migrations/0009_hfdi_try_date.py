"""A text column that holds dates will eventually hold "Sep".

``hfdi_performance_target_feedback`` stores ``month``, ``target_start_date``,
``target_sales_end_date`` and ``target_collections_end_date`` as ``varchar(50)``
(see ``apps/hfdi/models.py``: ``HfdiTargets``), and the YTD revenue queries cast
all four with ``::date``. One row typed as ``Sep`` - or left at the ``""``
default - makes the whole statement fail, so a single project's typo returns 500
for the entire bank's dashboard. It did, on 6 Oct 2026, on both
``/hfdi/hfdi-ytd_performance_hfdi_list/`` and ``.../list_per_project/``.

``hfdi_try_date`` casts when the text is a date and returns NULL when it is not,
which is what the surrounding SQL already copes with (``NULLIF`` on the
divisors, NULL targets rather than wrong ones). It accepts every format
PostgreSQL itself accepts, so it needs no guesses about how the data is written.

STABLE, not IMMUTABLE: text-to-date depends on the session's ``DateStyle``.
"""
from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION hfdi_try_date(txt text)
RETURNS date
LANGUAGE plpgsql
STABLE
RETURNS NULL ON NULL INPUT
AS $$
BEGIN
    IF btrim(txt) = '' THEN
        RETURN NULL;
    END IF;
    RETURN btrim(txt)::date;
EXCEPTION
    WHEN invalid_datetime_format OR datetime_field_overflow THEN
        RETURN NULL;
END;
$$;
"""

DROP = "DROP FUNCTION IF EXISTS hfdi_try_date(text);"


class Migration(migrations.Migration):

    dependencies = [
        ("hfdi", "0008_hfditargets_site_admin_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE, reverse_sql=DROP),
    ]
