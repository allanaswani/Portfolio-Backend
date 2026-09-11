"""Register Customer 360 as a watched service.

It is a separate resource server on the same host — it trusts the JWT this
backend mints but has no Django app here, so this backend cannot read its
internals. Registering it here is what lets this one probe it from outside, and
what gives it somewhere to push its own audit events and table health once
somebody can edit that repo.

Seeded WITHOUT a health URL and WITHOUT a token, deliberately:

* the URL is environment-specific and nobody has given it to me, and an invented
  one would probe nothing and then report Customer 360 as down;
* the token is generated on demand from Administration and shown once, so no
  shared secret is ever written into version control.

Both are filled in from the Administration screen. Until the URL is set the
service is listed as "not probed", which is honest, rather than green.
"""

from django.db import migrations


def seed(apps, schema_editor):
    Service = apps.get_model("observability", "MonitoredService")
    Service.objects.update_or_create(
        slug="customer-360",
        defaults={
            "name": "Customer 360",
            # Left blank on purpose — see the module docstring.
            "health_url": "",
            "expected_status": 200,
            "timeout_seconds": 10,
            "slow_ms": 3000,
            "is_active": True,
        },
    )


def unseed(apps, schema_editor):
    Service = apps.get_model("observability", "MonitoredService")
    Service.objects.filter(slug="customer-360").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("observability", "0002_alertrecipient_alertstate_externalauditevent_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
