from django.apps import AppConfig


class LargeCashConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.large_cash"
    verbose_name = "Large Cash Transactions"
