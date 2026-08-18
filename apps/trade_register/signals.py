"""Keep a register entry in step when its Trade Finance row is edited elsewhere.

Administration → Trade Finance edits the ``trade_finance_data`` row directly.
This ``post_save`` reflects such edits back into the linked register entry so the
two stores stay consistent in both directions.

No-loop guarantee: the back-sync writes via queryset ``.update()`` (no signals),
and the register → TF direction also uses ``.update()``/``.create()``. A freshly
created TF row has no ``register_entry`` yet, so creating one from the register
side is a no-op here.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.staff_management.models import TradeFinanceData


@receiver(post_save, sender=TradeFinanceData, dispatch_uid="trade_register_tf_backsync")
def sync_trade_finance_to_register(sender, instance, created, **kwargs):
    if created:
        return
    entry = getattr(instance, "register_entry", None)
    if entry is not None:
        entry.apply_from_trade_finance(instance)
