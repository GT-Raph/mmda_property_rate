from uuid import uuid4

from django.conf import settings
from django.db import models

from admins.models import Assembly, TimeStampedModel

from decimal import Decimal

class Owner(TimeStampedModel):
    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="owners",
    )
    linked_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owner_profile",
    )
    full_name = models.CharField(max_length=255)
    primary_phone = models.CharField(max_length=20)
    alternate_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    ghana_card_number = models.CharField(max_length=30, blank=True)
    postal_address = models.CharField(max_length=255, blank=True)
    residential_address = models.TextField(blank=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["primary_phone"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        return self.full_name


class Property(TimeStampedModel):
    PROPERTY_USE_CHOICES = [
        ("residential", "Residential"),
        ("commercial", "Commercial"),
        ("industrial", "Industrial"),
        ("mixed_use", "Mixed Use"),
        ("institutional", "Institutional"),
    ]

    BUILDING_TYPE_CHOICES = [
        ("compound", "Compound House"),
        ("self_contained", "Self Contained"),
        ("detached", "Detached"),
        ("semi_detached", "Semi Detached"),
        ("apartment", "Apartment"),
        ("shop", "Shop"),
        ("office", "Office"),
        ("warehouse", "Warehouse"),
        ("other", "Other"),
    ]

    OCCUPANCY_STATUS_CHOICES = [
        ("occupied", "Occupied"),
        ("vacant", "Vacant"),
        ("under_construction", "Under Construction"),
    ]

    REGISTRATION_SOURCE_CHOICES = [
        ("admin", "Admin"),
        ("field", "Field"),
    ]

    VERIFICATION_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("verified", "Verified"),
        ("flagged", "Flagged"),
        ("possible_duplicate", "Possible Duplicate"),
    ]

    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="properties",
    )
    owner = models.ForeignKey(
        Owner,
        on_delete=models.PROTECT,
        related_name="properties",
    )
    property_reference = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
        db_index=True,
    )

    digital_address = models.CharField(max_length=50, blank=True)
    address_line = models.CharField(max_length=255)
    area_town = models.CharField(max_length=100)
    suburb = models.CharField(max_length=100, blank=True)
    landmark = models.CharField(max_length=255, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    property_use = models.CharField(max_length=20, choices=PROPERTY_USE_CHOICES)
    building_type = models.CharField(max_length=20, choices=BUILDING_TYPE_CHOICES)
    number_of_floors = models.PositiveIntegerField(default=1)
    number_of_units = models.PositiveIntegerField(default=1)
    year_built = models.PositiveIntegerField(null=True, blank=True)
    occupancy_status = models.CharField(
        max_length=20,
        choices=OCCUPANCY_STATUS_CHOICES,
        default="occupied",
    )

    rateable_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_exempt = models.BooleanField(default=False)
    exemption_reason = models.TextField(blank=True)

    registration_source = models.CharField(
        max_length=10,
        choices=REGISTRATION_SOURCE_CHOICES,
        default="admin",
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default="pending",
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_properties",
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["property_reference"]
        indexes = [
            models.Index(fields=["property_reference"]),
            models.Index(fields=["area_town"]),
            models.Index(fields=["property_use"]),
            models.Index(fields=["building_type"]),
            models.Index(fields=["verification_status"]),
        ]

    def save(self, *args, **kwargs):
        if not self.property_reference:
            prefix = self.assembly.short_code if self.assembly_id and getattr(self.assembly, "short_code", "") else "MMDA"
            self.property_reference = f"{prefix}-{uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.property_reference} - {self.owner.full_name}"


class PropertyPhoto(TimeStampedModel):
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(upload_to="property_photos/")
    caption = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_property_photos",
    )

    class Meta:
        ordering = ["-is_primary", "-created_at"]

    def __str__(self):
        return f"Photo for {self.property.property_reference}"
