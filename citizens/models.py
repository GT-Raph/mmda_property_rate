from django.conf import settings
from django.db import models


class CitizenPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="citizen_preference",
    )
    mailing_address = models.CharField(max_length=255, blank=True)

    bill_reminders = models.BooleanField(default=True)
    payment_confirmations = models.BooleanField(default=True)
    property_updates = models.BooleanField(default=True)
    promotions_offers = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"Citizen Preference - {self.user.get_username()}"