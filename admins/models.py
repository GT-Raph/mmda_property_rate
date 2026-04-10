from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Assembly(TimeStampedModel):
    ASSEMBLY_TYPES = [
        ("metro", "Metropolitan"),
        ("municipal", "Municipal"),
        ("district", "District"),
    ]

    name = models.CharField(max_length=255, unique=True)
    short_code = models.CharField(max_length=20, unique=True)
    assembly_type = models.CharField(max_length=20, choices=ASSEMBLY_TYPES)
    region = models.CharField(max_length=100)
    district = models.CharField(max_length=150, blank=True)
    address = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    active_billing_year = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.short_code} - {self.name}"


class UserProfile(TimeStampedModel):
    ROLE_CHOICES = [
        ("sys_admin", "System Admin"),
        ("revenue_admin", "Revenue Admin"),
        ("billing_officer", "Billing Officer"),
        ("field_officer", "Field Officer"),
        ("citizen", "Citizen"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="user_profiles",
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    phone_number = models.CharField(max_length=20, blank=True)
    employee_id = models.CharField(max_length=50, blank=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.get_username()} ({self.role})"