import uuid
from builtins import property as builtin_property
from django.conf import settings
from django.db import models
from properties.models import Property
import os
from django.utils import timezone
from admins.models import Assembly
from billing.models import Bill



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
    

def citizen_dispute_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    ext = ext if ext else ".dat"
    return f"citizens/disputes/{instance.dispute.id}/{uuid.uuid4().hex}{ext}"


class CitizenDispute(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_RESOLVED = "resolved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    TYPE_RATE_ASSESSMENT = "rate_assessment"
    TYPE_WRONG_OWNER = "wrong_owner"
    TYPE_WRONG_PROPERTY_TYPE = "wrong_property_type"
    TYPE_DUPLICATE_BILL = "duplicate_bill"
    TYPE_PAYMENT_ISSUE = "payment_issue"
    TYPE_OTHER = "other"

    DISPUTE_TYPE_CHOICES = [
        (TYPE_RATE_ASSESSMENT, "Rate Assessment"),
        (TYPE_WRONG_OWNER, "Wrong Owner Details"),
        (TYPE_WRONG_PROPERTY_TYPE, "Wrong Property Type"),
        (TYPE_DUPLICATE_BILL, "Duplicate Bill"),
        (TYPE_PAYMENT_ISSUE, "Payment Issue"),
        (TYPE_OTHER, "Other"),
    ]

    dispute_number = models.CharField(max_length=40, unique=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="citizen_disputes",
    )
    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citizen_disputes",
    )
    property_record = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="citizen_disputes",
    )
    bill = models.ForeignKey(
        Bill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citizen_disputes",
    )
    dispute_type = models.CharField(max_length=50, choices=DISPUTE_TYPE_CHOICES)
    description = models.TextField()
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_SUBMITTED,
    )
    response_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return self.dispute_number or f"Dispute #{self.pk}"

    def save(self, *args, **kwargs):
        if not self.dispute_number:
            year = timezone.localdate().year
            prefix = f"DSP-{year}-"

            last_item = (
                CitizenDispute.objects.filter(dispute_number__startswith=prefix)
                .order_by("-dispute_number")
                .values_list("dispute_number", flat=True)
                .first()
            )

            next_number = 1
            if last_item:
                try:
                    next_number = int(last_item.split("-")[-1]) + 1
                except Exception:
                    next_number = 1

            self.dispute_number = f"{prefix}{next_number:05d}"

        if self.status == self.STATUS_RESOLVED and not self.resolved_at:
            self.resolved_at = timezone.now()

        super().save(*args, **kwargs)


class CitizenDisputeAttachment(models.Model):
    dispute = models.ForeignKey(
        CitizenDispute,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to=citizen_dispute_upload_path)
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return self.original_name or os.path.basename(self.file.name)