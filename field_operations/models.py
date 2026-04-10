from django.conf import settings
from django.db import models
from django.utils import timezone

from admins.models import Assembly, TimeStampedModel
from properties.models import Property


class EnumerationRecord(TimeStampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("converted", "Converted"),
    ]

    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="enumeration_records",
    )
    enumerator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="enumeration_records",
    )

    owner_name = models.CharField(max_length=255)
    owner_phone = models.CharField(max_length=20, blank=True)
    owner_email = models.EmailField(blank=True)

    address_line = models.CharField(max_length=255)
    area_town = models.CharField(max_length=100)
    suburb = models.CharField(max_length=100, blank=True)
    landmark = models.CharField(max_length=255, blank=True)
    digital_address = models.CharField(max_length=50, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    property_use = models.CharField(max_length=20, choices=Property.PROPERTY_USE_CHOICES)
    building_type = models.CharField(max_length=20, choices=Property.BUILDING_TYPE_CHOICES)
    number_of_floors = models.PositiveIntegerField(default=1)
    number_of_units = models.PositiveIntegerField(default=1)
    estimated_rateable_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    photo = models.ImageField(upload_to="enumeration_records/", null=True, blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_enumerations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    converted_property = models.OneToOneField(
        "properties.Property",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_enumeration",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Enumeration - {self.owner_name} - {self.area_town}"


class FieldVisit(TimeStampedModel):
    VISIT_TYPE_CHOICES = [
        ("verification", "Payment Verification"),
        ("enforcement", "Enforcement"),
        ("follow_up", "Follow Up"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("paid", "Paid"),
        ("part_paid", "Part Paid"),
        ("unpaid", "Unpaid"),
        ("disputed", "Disputed"),
        ("unknown", "Unknown"),
    ]

    OUTCOME_CHOICES = [
        ("compliant", "Compliant"),
        ("notice_served", "Notice Served"),
        ("follow_up_required", "Follow Up Required"),
        ("property_not_found", "Property Not Found"),
    ]

    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="field_visits",
    )
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.CASCADE,
        related_name="field_visits",
    )
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="field_visits",
    )

    visit_type = models.CharField(max_length=20, choices=VISIT_TYPE_CHOICES)
    payment_status_seen = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default="unknown",
    )
    outcome = models.CharField(max_length=30, choices=OUTCOME_CHOICES)
    amount_outstanding_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    visited_at = models.DateTimeField(default=timezone.now)
    next_action_date = models.DateField(null=True, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    notes = models.TextField(blank=True)
    photo = models.ImageField(upload_to="field_visits/", null=True, blank=True)

    class Meta:
        ordering = ["-visited_at"]

    def save(self, *args, **kwargs):
        if self.property_id and not self.assembly_id:
            self.assembly = self.property.assembly
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.property.property_reference} - {self.visit_type}"