"""Which tables Django believes exist but the database does not have.

    manage.py schema_drift              # list what is missing
    manage.py schema_drift --sql        # print the CREATE statements for them
    manage.py schema_drift --app portfolio_management_enrichment

This repository's ``0001_initial`` migrations are shadowed by legacy
``django_migrations`` rows from the old project: Django records them as applied
and never runs them, so any table they would have created is simply absent.
Nothing complains until something writes to it, and then it fails in the middle
of a job rather than at deploy time.

That is how ``portfolio_management_enrichment_historicalrmtarget`` was found -
by ``load_rm_targets`` dying on the first RmTarget it tried to save, months
after the deploy that was supposed to have created it. Every other shadowed
table is still out there waiting for its first write.

``--sql`` prints CREATE statements for the missing tables and nothing else. It
does not execute them: this is production DDL and it should be read before it is
run. Nothing here writes to the database under any flag.
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connections, router


class Command(BaseCommand):
    help = "Report (and optionally emit DDL for) tables that are missing from the database."

    def add_arguments(self, parser):
        parser.add_argument("--sql", action="store_true",
                            help="Print CREATE statements for the missing tables.")
        parser.add_argument("--app", help="Limit to one app label.")

    def handle(self, *a, **o):
        w = self.stdout.write

        # Introspection is a round trip per alias, so do it once each.
        known = {}

        def tables(alias):
            if alias not in known:
                with connections[alias].cursor() as cur:
                    known[alias] = set(
                        connections[alias].introspection.table_names(cur)
                    )
            return known[alias]

        missing = []
        checked = 0
        for model in apps.get_models():
            meta = model._meta
            if not meta.managed:
                continue                      # warehouse tables; not ours to create
            if o["app"] and meta.app_label != o["app"]:
                continue
            alias = router.db_for_write(model) or "default"
            checked += 1
            if meta.db_table not in tables(alias):
                missing.append((alias, model))

        if not o["sql"]:
            w("")
            w(f"Checked {checked} managed models.")
            w("")
            if not missing:
                w("  Every table Django expects is present.")
                w("")
                return
            w(f"  {len(missing)} MISSING - Django thinks these exist:")
            w("")
            by_app = {}
            for alias, model in missing:
                by_app.setdefault(model._meta.app_label, []).append((alias, model))
            for app_label in sorted(by_app):
                w(f"  {app_label}")
                for alias, model in sorted(by_app[app_label],
                                           key=lambda x: x[1]._meta.db_table):
                    w(f"      {model._meta.db_table:<58}[{alias}]")
            w("")
            w("  Each of these will fail on its FIRST write and not before, so an")
            w("  empty list here is worth more than a successful deploy.")
            w("")
            w("  To see the DDL:  manage.py schema_drift --sql")
            w("  Read it, then apply it with psql. This command will not run it.")
            w("")
            return

        if not missing:
            w("-- nothing missing")
            return

        for alias, model in missing:
            with connections[alias].schema_editor(
                    collect_sql=True, atomic=False) as se:
                se.create_model(model)
            w("")
            w(f"-- {model._meta.app_label}.{model.__name__}  ->  "
              f"{model._meta.db_table}  [{alias}]")
            for statement in se.collected_sql:
                w(statement)
