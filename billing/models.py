from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from admins.models import Assembly, TimeStampedModel
from properties.models import Property


RATE_POLICY_BUILDING_TYPE_CHOICES = [
    ("", "All Building Types"),
    *Property.BUILDING_TYPE_CHOICES,
]


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
    building_type = models.CharField(
        max_length=20,
        choices=RATE_POLICY_BUILDING_TYPE_CHOICES,
        blank=True,
        default="",
        help_text="Leave blank to make this policy the fallback for all building types under the selected property use.",
    )
    rate_impost = models.DecimalField(max_digits=10, decimal_places=5)
    minimum_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["assembly__name", "-year", "property_use", "building_type", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["assembly", "year", "property_use", "building_type", "effective_from"],
                name="unique_rate_policy_start_per_scope",
            )
        ]
        indexes = [
            models.Index(fields=["assembly", "year", "property_use", "building_type"]),
            models.Index(fields=["assembly", "is_active"]),
        ]

    def __str__(self):
        building_type = self.get_building_type_display() if self.building_type else "All Building Types"
        return f"{self.assembly.short_code} {self.year} - {self.get_property_use_display()} - {building_type}"

    def clean(self):
        super().clean()

        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "Effective to date cannot be earlier than effective from date."})

        if self.rate_impost < 0:
            raise ValidationError({"rate_impost": "Rate impost cannot be negative."})

        if self.minimum_charge < 0:
            raise ValidationError({"minimum_charge": "Minimum charge cannot be negative."})

        if self.effective_from and self.effective_from.year != self.year:
            raise ValidationError({"effective_from": "Effective from date must be within the selected policy year."})

        if self.effective_to and self.effective_to.year != self.year:
            raise ValidationError({"effective_to": "Effective to date must be within the selected policy year."})

        if self.is_active:
            conflicts = RatePolicy.objects.filter(
                assembly=self.assembly,
                year=self.year,
                property_use=self.property_use,
                building_type=self.building_type,
                is_active=True,
            ).exclude(pk=self.pk)

            for other in conflicts:
                other_end = other.effective_to or timezone.datetime.max.date()
                current_end = self.effective_to or timezone.datetime.max.date()
                if other.effective_from <= current_end and self.effective_from <= other_end:
                    raise ValidationError(
                        "Another active rate policy already overlaps with this assembly/property use/building type period."
                    )

    @classmethod
    def get_applicable_policy(cls, assembly, property_use, building_type="", on_date=None, year=None):
        if not assembly or not property_use:
            return None

        on_date = on_date or timezone.localdate()
        year = year or on_date.year

        base_qs = cls.objects.filter(
            assembly=assembly,
            year=year,
            property_use=property_use,
            is_active=True,
            effective_from__lte=on_date,
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
        )

        building_type = (building_type or "").strip()

        if building_type:
            exact_policy = base_qs.filter(building_type=building_type).order_by("-effective_from", "-created_at").first()
            if exact_policy:
                return exact_policy

        return base_qs.filter(building_type="").order_by("-effective_from", "-created_at").first()

    def calculate_principal(self, rateable_value):
        rateable_value = Decimal(rateable_value or 0)
        principal = rateable_value * (self.rate_impost or Decimal("0.00000"))
        if principal < (self.minimum_charge or Decimal("0.00")):
            principal = self.minimum_charge or Decimal("0.00")
        return principal.quantize(Decimal("0.01"))


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
    rate_impost_snapshot = models.DecimalField(max_digits=10, decimal_places=5, default=0)

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

    def _ensure_policy_and_snapshots(self):
        if self.property_record_id and not self.assembly_id:
            self.assembly = self.property_record.assembly

        if self.property_record_id and not self.rateable_value_snapshot:
            self.rateable_value_snapshot = self.property_record.rateable_value or Decimal("0.00")

        if self.property_record_id and not self.rate_policy_id and not self.property_record.is_exempt:
            policy_date = self.issued_at.date() if self.issued_at else timezone.localdate()
            self.rate_policy = RatePolicy.get_applicable_policy(
                assembly=self.property_record.assembly,
                property_use=self.property_record.property_use,
                building_type=self.property_record.building_type,
                on_date=policy_date,
                year=self.billing_year,
            )

        if self.rate_policy_id and not self.rate_impost_snapshot:
            self.rate_impost_snapshot = self.rate_policy.rate_impost or Decimal("0.00000")

    def _recalculate_totals(self):
        self._ensure_policy_and_snapshots()

        if self.property_record_id and self.property_record.is_exempt:
            self.rate_impost_snapshot = Decimal("0.00000")
            self.principal_amount = Decimal("0.00")
        else:
            if not self.rate_policy_id:
                raise ValidationError("No active rate policy matches this property's use/building type for the selected billing year.")
            self.principal_amount = self.rate_policy.calculate_principal(self.rateable_value_snapshot)

        self.amount_due = (
            (self.principal_amount or Decimal("0.00"))
            + (self.arrears_brought_forward or Decimal("0.00"))
            + (self.penalty_amount or Decimal("0.00"))
        ).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        self._recalculate_totals()

        if not self.bill_number and self.property_record_id and self.billing_year:
            self.bill_number = f"BILL-{self.billing_year}-{self.property_record.property_reference}"

        self.refresh_status()
        super().save(*args, **kwargs)

    @classmethod
    def generate_for_property(
        cls,
        *,
        property_record,
        billing_year,
        due_date,
        arrears_brought_forward=Decimal("0.00"),
        penalty_amount=Decimal("0.00"),
        notes="",
    ):
        bill, _ = cls.objects.get_or_create(
            property_record=property_record,
            billing_year=billing_year,
            defaults={
                "assembly": property_record.assembly,
                "due_date": due_date,
            },
        )

        bill.assembly = property_record.assembly
        bill.due_date = due_date
        bill.notes = notes
        bill.arrears_brought_forward = Decimal(arrears_brought_forward or 0)
        bill.penalty_amount = Decimal(penalty_amount or 0)
        bill.rateable_value_snapshot = property_record.rateable_value or Decimal("0.00")
        bill.rate_policy = RatePolicy.get_applicable_policy(
            assembly=property_record.assembly,
            property_use=property_record.property_use,
            building_type=property_record.building_type,
            on_date=timezone.localdate(),
            year=billing_year,
        )
        bill.save()
        return bill

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
