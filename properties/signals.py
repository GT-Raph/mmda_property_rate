from django.db import transaction
from django.db.models.signals import (
    post_save,
    pre_save,
)
from django.dispatch import receiver
from django.urls import reverse

from admins.models import (
    UserNotification,
)

from .models import Property


@receiver(
    pre_save,
    sender=Property,
)
def remember_previous_verification_status(
    sender,
    instance,
    **kwargs,
):
    if not instance.pk:
        instance._previous_verification_status = (
            None
        )
        return

    previous_status = (
        Property.objects
        .filter(
            pk=instance.pk,
        )
        .values_list(
            "verification_status",
            flat=True,
        )
        .first()
    )

    instance._previous_verification_status = (
        previous_status
    )


@receiver(
    post_save,
    sender=Property,
)
def notify_owner_when_verified(
    sender,
    instance,
    created,
    **kwargs,
):
    if created:
        return

    old_status = getattr(
        instance,
        "_previous_verification_status",
        None,
    )

    new_status = (
        instance.verification_status
        or ""
    ).strip().lower()

    if new_status != "verified":
        return

    if old_status == "verified":
        return

    owner = getattr(
        instance,
        "owner",
        None,
    )

    if not owner:
        return

    citizen_user = getattr(
        owner,
        "linked_user",
        None,
    )

    if not citizen_user:
        return

    user_id = citizen_user.pk
    property_reference = (
        instance.property_reference
    )

    action_url = reverse(
        "citizens:bills"
    )

    def create_notification():
        UserNotification.objects.create(
            user_id=user_id,
            notification_type=(
                "property_verified"
            ),
            level="success",
            title="Property Verified",
            message=(
                f"Your property "
                f"{property_reference} "
                "has been verified by the MMDA. "
                "You can now make property-rate "
                "payments for this property."
            ),
            action_url=action_url,
        )

    transaction.on_commit(
        create_notification
    )