from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from admins.models import Assembly, TimeStampedModel
from properties.models import Property


class RatePolicy(TimeStampedModel):
    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="rate_policies",
    )
    year = models.PositiveIntegerField(db_index=True)
    property_use = models.CharField(
        max_length=20,
        choices=Property.PROPERTY_USE_CHOICES,
    )
    building_type = models.CharField(max_length=20, blank=True, default="")
    rate_impost = models.DecimalField(max_digits=10, decimal_places=4)
    minimum_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-year", "property_use", "building_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["assembly", "year", "property_use", "building_type"],
                name="unique_rate_policy_per_year_use_type",
            )
        ]

    def __str__(self):
        building_type = self.building_type or "all"
        return f"{self.assembly.short_code} {self.year} {self.property_use} {building_type}"


class Bill(TimeStampedModel):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("part_paid", "Part Paid"),
        ("paid", "Paid"),
        ("overdue", "Overdue"),
        ("cancelled", "Cancelled"),
    ]

    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="bills",
    )
    property_record = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="bills",
    )
    rate_policy = models.ForeignKey(
        RatePolicy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills",
    )

    billing_year = models.PositiveIntegerField(db_index=True)
    bill_number = models.CharField(max_length=60, unique=True, editable=False)

    rateable_value_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    rate_impost_snapshot = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    principal_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    arrears_brought_forward = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    penalty_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    amount_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    issued_at = models.DateTimeField(default=timezone.now)
    due_date = models.DateField()
    last_payment_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-billing_year", "property_record__property_reference"]
        constraints = [
            models.UniqueConstraint(
                fields=["property_record", "billing_year"],
                name="unique_bill_per_property_per_year",
            )
        ]
        indexes = [
            models.Index(fields=["bill_number"]),
            models.Index(fields=["billing_year", "status"]),
        ]

    @property
    def balance(self):
        return (self.amount_due or Decimal("0.00")) - (self.amount_paid or Decimal("0.00"))

    def refresh_status(self):
        amount_due = self.amount_due or Decimal("0.00")
        amount_paid = self.amount_paid or Decimal("0.00")

        if self.status == "cancelled":
            return

        if amount_due > 0 and amount_paid >= amount_due:
            self.status = "paid"
        elif amount_paid > 0:
            self.status = "part_paid"
        elif self.due_date and self.due_date < timezone.localdate():
            self.status = "overdue"
        else:
            self.status = "pending"

    def save(self, *args, **kwargs):
        if self.property_record_id and not self.assembly_id:
            self.assembly = self.property_record.assembly

        if self.property_record_id and not self.rateable_value_snapshot:
            self.rateable_value_snapshot = self.property_record.rateable_value or Decimal("0.00")

        if self.rate_policy_id and not self.rate_impost_snapshot:
            self.rate_impost_snapshot = self.rate_policy.rate_impost or Decimal("0.0000")

        rateable = self.rateable_value_snapshot or Decimal("0.00")
        impost = self.rate_impost_snapshot or Decimal("0.0000")
        principal = rateable * impost

        if self.rate_policy_id and principal < self.rate_policy.minimum_charge:
            principal = self.rate_policy.minimum_charge

        self.principal_amount = principal.quantize(Decimal("0.01"))
        self.amount_due = (
            self.principal_amount
            + (self.arrears_brought_forward or Decimal("0.00"))
            + (self.penalty_amount or Decimal("0.00"))
        ).quantize(Decimal("0.01"))

        if not self.bill_number and self.property_record_id and self.billing_year:
            self.bill_number = f"BILL-{self.billing_year}-{self.property_record.property_reference}"

        self.refresh_status()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.bill_number or f"Bill {self.billing_year}"


class BillDispute(TimeStampedModel):
    ISSUE_TYPE_CHOICES = [
        ("wrong_owner", "Wrong Owner"),
        ("wrong_classification", "Wrong Classification"),
        ("wrong_rateable_value", "Wrong Rateable Value"),
        ("payment_not_reflected", "Payment Not Reflected"),
        ("duplicate_property", "Duplicate Property"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("submitted", "Submitted"),
        ("under_review", "Under Review"),
        ("resolved", "Resolved"),
        ("rejected", "Rejected"),
    ]

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="disputes",
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="raised_bill_disputes",
    )
    issue_type = models.CharField(max_length=30, choices=ISSUE_TYPE_CHOICES)
    description = models.TextField()
    attachment = models.FileField(upload_to="bill_disputes/", null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="submitted")
    admin_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_bill_disputes",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolution_summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Dispute - {self.bill.bill_number}"