from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Payment
from .services import apply_payment_to_bill


@receiver(post_save, sender=Payment)
def apply_successful_payment_on_save(sender, instance, **kwargs):
    if instance.status == "successful" and instance.bill_id and not instance.applied_to_bill:
        apply_payment_to_bill(instance)