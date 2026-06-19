from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authentication"
    label = "authentication"

    def ready(self):
        from django_rest_passwordreset.signals import reset_password_token_created
        from .views import password_reset_token_created
        reset_password_token_created.connect(password_reset_token_created)
