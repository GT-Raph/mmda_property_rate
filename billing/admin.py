from django.contrib import admin

from .models import Bill, BillDispute, RatePolicy


@admin.register(RatePolicy)
class RatePolicyAdmin(admin.ModelAdmin):
    list_display = (
        "assembly",
        "year",
        "property_use",
        "building_type",
        "rate_impost",
        "minimum_charge",
        "effective_from",
        "effective_to",
        "is_active",
    )
    list_filter = ("assembly", "year", "property_use", "building_type", "is_active")
    search_fields = ("assembly__name", "assembly__short_code", "notes")
    list_editable = ("rate_impost", "minimum_charge", "is_active")


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        "bill_number",
        "property_record",
        "billing_year",
        "rate_policy",
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
