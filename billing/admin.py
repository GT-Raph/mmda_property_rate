from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import Bill, BillDispute, CommunityArea, RatePolicy


class RatePolicyAdminForm(forms.ModelForm):
    class Meta:
        model = RatePolicy
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "covered_areas" in self.fields:
            self.fields["covered_areas"].queryset = CommunityArea.objects.filter(
                is_active=True
            ).order_by("sub_metro", "name")

    def clean(self):
        cleaned_data = super().clean()

        assembly = cleaned_data.get("assembly")
        year = cleaned_data.get("year")
        property_use = cleaned_data.get("property_use")
        property_class = (cleaned_data.get("property_class") or "").strip()
        building_type = (cleaned_data.get("building_type") or "").strip()
        status = cleaned_data.get("status")
        effective_from = cleaned_data.get("effective_from")
        effective_to = cleaned_data.get("effective_to")
        covered_areas = cleaned_data.get("covered_areas")

        if covered_areas and assembly:
            bad_areas = covered_areas.exclude(assembly=assembly)
            if bad_areas.exists():
                raise ValidationError(
                    {"covered_areas": "All selected areas must belong to the selected assembly."}
                )

        if status == "active" and all([assembly, year, property_use, property_class, effective_from]):
            current_end = effective_to or effective_from.replace(month=12, day=31)

            conflicts = RatePolicy.objects.filter(
                assembly=assembly,
                year=year,
                property_use=property_use,
                property_class=property_class,
                building_type=building_type,
                status="active",
            ).exclude(pk=self.instance.pk)

            for other in conflicts:
                other_end = other.effective_to or other.effective_from.replace(month=12, day=31)

                if other.effective_from <= current_end and effective_from <= other_end:
                    if covered_areas:
                        other_area_ids = set(other.covered_areas.values_list("id", flat=True))
                        current_area_ids = set(area.id for area in covered_areas)
                        if current_area_ids & other_area_ids:
                            raise ValidationError(
                                "Another active rate policy overlaps with the same area(s), class, year and building type."
                            )
                    else:
                        other_area_count = other.covered_areas.count()
                        if other_area_count == 0:
                            raise ValidationError(
                                "Another active fallback policy already overlaps with the same class, year and building type."
                            )

        return cleaned_data


@admin.register(CommunityArea)
class CommunityAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "sub_metro", "assembly", "is_active")
    list_filter = ("assembly", "sub_metro", "is_active")
    search_fields = ("name",)
    list_editable = ("is_active",)
    ordering = ("sub_metro", "name")


@admin.register(RatePolicy)
class RatePolicyAdmin(admin.ModelAdmin):
    form = RatePolicyAdminForm
    list_display = (
        "policy_name",
        "assembly",
        "year",
        "property_use",
        "property_class",
        "building_type",
        "status",
        "rate_impost",
        "minimum_charge",
        "effective_from",
        "effective_to",
        "covered_area_count",
    )
    list_filter = (
        "assembly",
        "year",
        "property_use",
        "property_class",
        "building_type",
        "status",
    )
    search_fields = ("policy_name", "property_class", "notes", "covered_areas__name")
    filter_horizontal = ("covered_areas",)
    ordering = ("assembly__name", "-year", "property_use", "property_class", "building_type", "-effective_from")

    fieldsets = (
        ("Basic Policy Details", {
            "fields": (
                "assembly",
                "policy_name",
                "year",
                "property_use",
                "property_class",
                "covered_areas",
                "building_type",
            )
        }),
        ("Calculation", {
            "fields": (
                "rate_impost",
                "minimum_charge",
            )
        }),
        ("Validity & Status", {
            "fields": (
                "effective_from",
                "effective_to",
                "status",
                "notes",
            )
        }),
    )

    def covered_area_count(self, obj):
        return obj.covered_areas.count()
    covered_area_count.short_description = "Areas"


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        "bill_number",
        "property_record",
        "billing_year",
        "rate_policy",
        "policy_name_snapshot",
        "property_class_snapshot",
        "amount_due",
        "amount_paid",
        "status",
        "due_date",
    )
    list_filter = ("assembly", "billing_year", "status")
    search_fields = (
        "bill_number",
        "property_record__property_reference",
        "property_record__owner__full_name",
        "policy_name_snapshot",
        "property_class_snapshot",
    )
    autocomplete_fields = ("property_record", "rate_policy")


@admin.register(BillDispute)
class BillDisputeAdmin(admin.ModelAdmin):
    list_display = ("bill", "issue_type", "status", "raised_by", "created_at")
    list_filter = ("issue_type", "status")
    search_fields = (
        "bill__bill_number",
        "bill__property_record__property_reference",
        "bill__property_record__owner__full_name",
        "description",
    )