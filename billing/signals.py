from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from properties.models import Property

from .services import generate_bill_for_property


@receiver(
    post_save,
    sender=Property,
)
def auto_generate_current_year_bill(
    sender,
    instance,
    created,
    raw=False,
    **kwargs,
):
    if raw:
        return

    if not instance.is_active:
        return

    generate_bill_for_property(
        instance,
        billing_year=(
            timezone.localdate().year
        ),
    )