from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from admins.models import Assembly, TimeStampedModel
from properties.models import Property


SUB_METRO_CHOICES = [
    ("OKS", "Okaikoi South Sub-Metro (OKS)"),
    ("ABS", "Ablekuma South Sub-Metro (ABS)"),
    ("AKS", "Ashiedu Keteke Sub-Metro (AKS)"),
]

RATE_POLICY_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("active", "Active"),
    ("inactive", "Inactive"),
]

RATE_POLICY_BUILDING_TYPE_CHOICES = [
    ("", "All Building Types"),
    *Property.BUILDING_TYPE_CHOICES,
]


class CommunityArea(TimeStampedModel):
    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="community_areas",
    )
    sub_metro = models.CharField(max_length=10, choices=SUB_METRO_CHOICES)
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sub_metro", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["assembly", "sub_metro", "name"],
                name="unique_community_area_per_assembly_submetro",
            )
        ]
        indexes = [
            models.Index(fields=["assembly", "sub_metro"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_sub_metro_display()})"


class RatePolicy(TimeStampedModel):
    assembly = models.ForeignKey(
        Assembly,
        on_delete=models.CASCADE,
        related_name="rate_policies",
    )
    policy_name = models.CharField(max_length=150)
    year = models.PositiveIntegerField(db_index=True)
    property_use = models.CharField(
        max_length=20,
        choices=Property.PROPERTY_USE_CHOICES,
    )
    property_class = models.CharField(max_length=100)
    covered_areas = models.ManyToManyField(
        CommunityArea,
        blank=True,
        related_name="rate_policies",
        help_text="Select one or more communities/areas this class applies to. Leave empty only for a broad fallback policy.",
    )
    building_type = models.CharField(
        max_length=20,
        choices=RATE_POLICY_BUILDING_TYPE_CHOICES,
        blank=True,
        default="",
        help_text="Leave blank to make this policy apply to all building types within the selected class and area(s).",
    )
    rate_impost = models.DecimalField(max_digits=10, decimal_places=5)
    minimum_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=RATE_POLICY_STATUS_CHOICES, default="draft")
    is_active = models.BooleanField(default=False, editable=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["assembly__name", "-year", "property_use", "property_class", "building_type", "-effective_from"]
        indexes = [
            models.Index(fields=["assembly", "year", "property_use", "building_type"]),
            models.Index(fields=["assembly", "status"]),
        ]

    def __str__(self):
        building_type = self.get_building_type_display() if self.building_type else "All Building Types"
        return f"{self.policy_name} - {self.get_property_use_display()} - {self.property_class} - {building_type}"

    def clean(self):
        super().clean()

        self.policy_name = (self.policy_name or "").strip()
        self.property_class = (self.property_class or "").strip()

        if not self.policy_name:
            raise ValidationError({"policy_name": "Policy name is required."})

        if not self.property_class:
            raise ValidationError({"property_class": "Property class is required."})

        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "Effective to date cannot be earlier than effective from date."})

        if self.rate_impost < 0:
            raise ValidationError({"rate_impost": "Rate impost cannot be negative."})

        if self.minimum_charge < 0:
            raise ValidationError({"minimum_charge": "Minimum charge cannot be negative."})

        if self.effective_from and self.effective_from.year != self.year:
            raise ValidationError({"effective_from": "Effective from date must be within the selected billing year."})

        if self.effective_to and self.effective_to.year != self.year:
            raise ValidationError({"effective_to": "Effective to date must be within the selected billing year."})

        self.is_active = self.status == "active"

    def save(self, *args, **kwargs):
        self.full_clean()
        self.is_active = self.status == "active"
        super().save(*args, **kwargs)

    @classmethod
    def get_applicable_policy(cls, assembly, property_use, community_area=None, building_type="", on_date=None, year=None):
        if not assembly or not property_use:
            return None

        on_date = on_date or timezone.localdate()
        year = year or on_date.year
        building_type = (building_type or "").strip()

        base_qs = cls.objects.filter(
            assembly=assembly,
            year=year,
            property_use=property_use,
            status="active",
            effective_from__lte=on_date,
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
        ).prefetch_related("covered_areas")

        def ordered(qs):
            return qs.order_by("-effective_from", "-created_at")

        if community_area:
            exact_area_qs = base_qs.filter(covered_areas=community_area)
            if building_type:
                exact_area_exact_type = ordered(exact_area_qs.filter(building_type=building_type)).first()
                if exact_area_exact_type:
                    return exact_area_exact_type

            exact_area_all_type = ordered(exact_area_qs.filter(building_type="")).first()
            if exact_area_all_type:
                return exact_area_all_type

        no_area_qs = base_qs.annotate(area_count=models.Count("covered_areas")).filter(area_count=0)
        if building_type:
            no_area_exact_type = ordered(no_area_qs.filter(building_type=building_type)).first()
            if no_area_exact_type:
                return no_area_exact_type

        return ordered(no_area_qs.filter(building_type="")).first()

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

    policy_name_snapshot = models.CharField(max_length=150, blank=True)
    property_class_snapshot = models.CharField(max_length=100, blank=True)
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
                community_area=self.property_record.community_area,
                building_type=self.property_record.building_type,
                on_date=policy_date,
                year=self.billing_year,
            )

        if self.rate_policy_id:
            if not self.policy_name_snapshot:
                self.policy_name_snapshot = self.rate_policy.policy_name
            if not self.property_class_snapshot:
                self.property_class_snapshot = self.rate_policy.property_class
            if not self.rate_impost_snapshot:
                self.rate_impost_snapshot = self.rate_policy.rate_impost or Decimal("0.00000")

    def _recalculate_totals(self):
        self._ensure_policy_and_snapshots()

        if self.property_record_id and self.property_record.is_exempt:
            self.rate_impost_snapshot = Decimal("0.00000")
            self.principal_amount = Decimal("0.00")
            if not self.property_class_snapshot:
                self.property_class_snapshot = ""
        else:
            if not self.rate_policy_id:
                raise ValidationError("No active rate policy matches this property's billing year, area, use, class and building type.")
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
            community_area=property_record.community_area,
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
