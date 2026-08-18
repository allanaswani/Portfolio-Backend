from django.apps import AppConfig


class TradeRegisterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.trade_register"
    verbose_name = "Trade Register"

    def ready(self):
        # Wire the Administration Trade Finance → register back-sync signal.
        from . import signals  # noqa: F401
