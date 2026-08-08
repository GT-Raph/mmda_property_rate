from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


User = get_user_model()


@receiver(
    post_save,
    sender=User,
)
def create_or_update_user_profile(
    sender,
    instance,
    created,
    **kwargs,
):
    profile, profile_created = (
        UserProfile.objects.get_or_create(
            user=instance
        )
    )

    update_fields = []

    if not profile.role:
        profile.role = "citizen"
        update_fields.append("role")

    if (
        profile_created
        and not instance.is_superuser
    ):
        profile.must_change_password = True
        update_fields.append(
            "must_change_password"
        )

    if update_fields:
        profile.save(
            update_fields=update_fields
        )