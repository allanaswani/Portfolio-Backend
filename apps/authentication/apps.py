from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _seed_roles(sender, **kwargs):
    """Ensure every canonical HF role (auth.Group) exists after each migrate.

    The admin Users screen lists Group.objects.all() for its role dropdown, so
    without these rows the dropdown is empty and roles can't be assigned. Running
    on post_migrate (idempotent get_or_create) means a fresh DB always has them
    and any newly-added role in core.roles.ALL_ROLES is picked up automatically —
    no manual `seed_roles` step required.
    """
    from django.contrib.auth.models import Group
    from core.roles import ALL_ROLES
    for name in ALL_ROLES:
        Group.objects.get_or_create(name=name)


class AuthenticationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authentication"
    label = "authentication"

    def ready(self):
        from django_rest_passwordreset.signals import reset_password_token_created
        from .views import password_reset_token_created
        reset_password_token_created.connect(password_reset_token_created)
        post_migrate.connect(_seed_roles, sender=self)
