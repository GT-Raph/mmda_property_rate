from django.db import models
from django.utils import timezone

from admins.models import Assembly, TimeStampedModel


class Payment(TimeStampedModel):
    METHOD_CHOICES = [
        ("momo", "Mobile Money"),
        ("card", "Card"),
        ("bank", "Bank Transfer"),
        ("cash", "Cash"),
        ("pos", "POS"),
    ]

    STATUS_CHOICES = [
        ("initiated", "Initiated"),
        ("pending", "Pending"),
        ("successful", "Successful"),
        ("failed", "Failed"),
        ("reversed", "Reversed"),
    ]

    RECONCILIATION_CHOICES = [
        ("unmatched", "Unmatched"),
        ("matched", "Matched"),
        ("manual_review", "Manual Review"),
    ]

    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="payments",
        null=True,
        blank=True,
    )
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    bill = models.ForeignKey(
        "billing.Bill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )

    payer_name = models.CharField(max_length=255, blank=True)
    payer_phone = models.CharField(max_length=20, blank=True)
    payer_email = models.EmailField(blank=True)
    property_reference_entered = models.CharField(max_length=40, blank=True)

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    provider = models.CharField(max_length=50, blank=True)
    transaction_reference = models.CharField(max_length=120, unique=True)
    external_reference = models.CharField(max_length=120, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reconciliation_status = models.CharField(
        max_length=20,
        choices=RECONCILIATION_CHOICES,
        default="unmatched",
    )

    paid_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    applied_to_bill = models.BooleanField(default=False)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["transaction_reference"]),
            models.Index(fields=["property_reference_entered"]),
            models.Index(fields=["status", "reconciliation_status"]),
            models.Index(fields=["status", "applied_to_bill"]),
        ]

    def save(self, *args, **kwargs):
        if self.bill_id and not self.property_id:
            self.property = self.bill.property_record

        if self.property_id and not self.assembly_id:
            self.assembly = self.property.assembly

        if self.status == "successful" and not self.paid_at:
            self.paid_at = timezone.now()

        super().save(*args, **kwargs)

    def apply_to_bill(self):
        from .services import apply_payment_to_bill
        return apply_payment_to_bill(self)

    def __str__(self):
        return self.transaction_reference