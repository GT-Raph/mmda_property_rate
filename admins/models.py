from django.conf import settings
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ReportRun(TimeStampedModel):
    REPORT_CHOICES = [
        ("monthly_revenue", "Monthly Revenue Report"),
        ("property_registration", "Property Registration Summary"),
        ("payment_trends", "Payment Collection Trends"),
        ("outstanding_bills", "Outstanding Bills Report"),
        ("dispute_resolution", "Dispute Resolution Summary"),
        ("field_operations", "Field Operations Report"),
    ]

    report_key = models.CharField(max_length=50, choices=REPORT_CHOICES)
    generated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_reports",
    )
    file_format = models.CharField(max_length=20, default="xlsx")
    rows_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_report_key_display()} - {self.created_at:%Y-%m-%d %H:%M}"


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
        ("property_officer", "Property Officer"),
        ("payment_officer", "Payment Officer"),
        ("billing_officer", "Billing Officer"),
        ("report_officer", "Report Officer"),
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
    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        default="citizen",
    )
    phone_number = models.CharField(max_length=20, blank=True)
    employee_id = models.CharField(max_length=50, blank=True)
    is_verified = models.BooleanField(default=False)

    EMPLOYEE_ID_PREFIXES = {
        "sys_admin": "SA",
        "revenue_admin": "RA",
        "property_officer": "PO",
        "payment_officer": "PAY",
        "billing_officer": "BO",
        "report_officer": "RO",
        "field_officer": "FO",
    }

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.get_username()} ({self.role})"

    def _build_employee_id(self):
        prefix = self.EMPLOYEE_ID_PREFIXES.get(self.role)
        if not prefix and self.user_id and self.user.is_staff:
            prefix = "EMP"

        if not prefix or not self.user_id:
            return ""

        return f"{prefix}-{self.user_id:05d}"

    def save(self, *args, **kwargs):
        if not self.employee_id and (self.role != "citizen" or (self.user_id and self.user.is_staff)):
            self.employee_id = self._build_employee_id()

            update_fields = kwargs.get("update_fields")
            if update_fields is not None and self.employee_id:
                update_fields = set(update_fields)
                update_fields.add("employee_id")
                kwargs["update_fields"] = update_fields

        super().save(*args, **kwargs)


class AdminPreference(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_preferences",
    )
    email_notifications = models.BooleanField(default=True)
    payment_alerts = models.BooleanField(default=True)
    dispute_alerts = models.BooleanField(default=True)
    system_updates = models.BooleanField(default=False)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"Preferences - {self.user.get_username()}"


class LoginAudit(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_audits",
    )
    session_key = models.CharField(max_length=64, unique=True)
    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_name = models.CharField(max_length=255, blank=True)
    location_label = models.CharField(max_length=255, blank=True, default="Unknown")
    last_seen = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-last_seen"]
        indexes = [
            models.Index(fields=["session_key"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user.get_username()} - {self.device_name or 'Session'}"