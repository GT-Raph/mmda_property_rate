import uuid
from builtins import property as builtin_property

from django.conf import settings
from django.db import models
from properties.models import Property


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


class PropertyCertificate(models.Model):
    property = models.OneToOneField(
        Property,
        on_delete=models.CASCADE,
        related_name="certificate",
    )
    certificate_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return f"{self.property.property_reference} Certificate"

    @builtin_property
    def certificate_number(self):
        year_value = self.issued_at.year if self.issued_at else 2026
        return f"{self.property.property_reference}-CERT-{year_value}"

    @builtin_property
    def property_reference(self):
        return self.property.property_reference