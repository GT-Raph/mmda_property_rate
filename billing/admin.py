from django import forms
from django.contrib import admin

from .models import Bill, BillDispute, CommunityArea, RatePolicy


class RatePolicyAdminForm(forms.ModelForm):
    class Meta:
        model = RatePolicy
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "covered_areas" in self.fields:
            self.fields["covered_areas"].queryset = CommunityArea.objects.filter(is_active=True).order_by("sub_metro", "name")


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
    autocomplete_fields = ()

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
