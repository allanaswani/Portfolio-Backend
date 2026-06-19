class HFGroupRouter:
    """
    Two-database routing strategy:

    - default (hf_group_app)    — all Django-managed models: auth, sessions,
                                   admin, token blacklist, history tables, and
                                   every app model where managed = True.
    - datawarehouse             — legacy HF Group tables (managed = False).
                                   Read-only from the app's perspective; no
                                   migrations are ever applied here.
    """

    LEGACY = "datawarehouse"
    APP = "default"

    def db_for_read(self, model, **hints):
        if not model._meta.managed:
            return self.LEGACY
        return self.APP

    def db_for_write(self, model, **hints):
        if not model._meta.managed:
            # Unmanaged tables are owned by the old backend — block writes.
            return None
        return self.APP

    def allow_relation(self, obj1, obj2, **hints):
        # Cross-DB relations are handled at the service/view layer, not via
        # ORM JOINs, so allow everything and let the code handle consistency.
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Migrations only ever run against the new application database.
        # The legacy datawarehouse is never touched by Django migrations.
        return db == self.APP
    