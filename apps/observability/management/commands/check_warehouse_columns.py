"""Do the warehouse models match the tables the ETLs actually built?

    docker exec hf-backend python manage.py check_warehouse_columns

The unmanaged models are this application's *belief* about the warehouse. The
ETLs are what is true. When the two drift, nothing says so — the page 500s with
``column x.y does not exist``, and it is found one endpoint at a time by
whoever happened to open it.

That is how ``ceo_deposit_movement_daily`` was found: the model declares no
primary key, so Django adds an implicit ``id``, the table has no such column,
and every query for a model instance asked for it. The same shape is waiting in
any other table built without one.

This compares every unmanaged model against ``information_schema`` and reports:

* a table that is not there at all;
* a column the model expects and the table does not have — the 500 waiting to
  happen, with the **phantom primary key** called out separately because the fix
  is different (use ``.values()``, or declare a real primary key);
* a column the table has that no model mentions, which is only ever
  informational — an ETL may add columns this application has no use for.

Read-only. It changes nothing and is safe to run on production at any time.
"""

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand
from django.db import connections, router


class Command(BaseCommand):
    help = "Compare every unmanaged model against the real warehouse columns."

    def add_arguments(self, parser):
        parser.add_argument("--app", default="", help="Limit to one app label.")
        parser.add_argument("--extra", action="store_true",
                            help="Also list columns the tables have that no "
                                 "model mentions.")

    def handle(self, *args, **options):
        models = [m for m in django_apps.get_models() if not m._meta.managed]
        if options["app"]:
            models = [m for m in models if m._meta.app_label == options["app"]]
        models.sort(key=lambda m: (m._meta.app_label, m._meta.db_table))

        missing_tables, broken, phantom, extras = [], [], [], []

        for model in models:
            table = model._meta.db_table
            try:
                alias = router.db_for_read(model) or "default"
            except Exception:  # noqa: BLE001
                alias = "default"

            try:
                with connections[alias].cursor() as cursor:
                    cursor.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = %s", [table])
                    actual = {row[0].lower() for row in cursor.fetchall()}
            except Exception as exc:  # noqa: BLE001 — one bad table must not
                # end the audit; reporting the rest is the point.
                broken.append((model, table, [f"could not be read: {exc}"]))
                continue

            if not actual:
                missing_tables.append((model, table))
                continue

            expected = {f.column.lower(): f for f in model._meta.concrete_fields}
            absent = sorted(set(expected) - actual)
            if absent:
                pk = model._meta.pk
                # An auto-created primary key is Django's invention, not the
                # schema's — a different fault from a column the ETL dropped.
                if pk is not None and pk.auto_created and pk.column.lower() in absent:
                    phantom.append((model, table))
                    absent = [c for c in absent if c != pk.column.lower()]
                if absent:
                    broken.append((model, table, absent))

            if options["extra"]:
                spare = sorted(actual - set(expected))
                if spare:
                    extras.append((model, table, spare))

        self.report(models, missing_tables, phantom, broken, extras)

    def report(self, models, missing_tables, phantom, broken, extras):
        w = self.stdout.write
        w(f"Checked {len(models)} unmanaged model(s).")
        w("")

        if phantom:
            w(self.style.ERROR(
                f"{len(phantom)} model(s) expect an 'id' the table does not have."))
            w("  Django adds a primary key when a model declares none, and then")
            w("  every query for a model instance selects a column that is not")
            w("  there. Fix with .values(<real columns>), or declare the real")
            w("  primary key on the model.")
            for model, table in phantom:
                w(f"    {table:<48} {model._meta.label}")
            w("")

        if missing_tables:
            w(self.style.ERROR(f"{len(missing_tables)} table(s) do not exist."))
            for model, table in missing_tables:
                w(f"    {table:<48} {model._meta.label}")
            w("")

        if broken:
            w(self.style.ERROR(
                f"{len(broken)} model(s) expect columns the table does not have."))
            w("  Every one of these is a 500 waiting for somebody to open the page.")
            for model, table, columns in broken:
                w(f"    {table:<48} {model._meta.label}")
                w(f"      missing: {', '.join(columns)}")
            w("")

        if extras:
            w(f"{len(extras)} table(s) have columns no model mentions "
              f"(informational only).")
            for model, table, columns in extras:
                w(f"    {table:<48} {', '.join(columns[:8])}"
                  + (" …" if len(columns) > 8 else ""))
            w("")

        if not (phantom or missing_tables or broken):
            w(self.style.SUCCESS(
                "Every unmanaged model matches its table. Nothing to fix."))
