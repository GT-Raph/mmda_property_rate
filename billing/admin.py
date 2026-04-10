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
        "is_active",
    )
    list_filter = ("assembly", "year", "property_use", "building_type", "is_active")
    search_fields = ("assembly__name", "assembly__short_code", "notes")
    autocomplete_fields = ("assembly",)


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        "bill_number",
        "property_record",
        "assembly",
        "billing_year",
        "amount_due",
        "amount_paid",
        "status",
        "due_date",
    )
    list_filter = ("assembly", "billing_year", "status", "due_date")
    search_fields = (
        "bill_number",
        "property_record__property_reference",
        "property_record__owner_name",
        "property_record__owner_phone",
    )
    autocomplete_fields = ("assembly", "property_record", "rate_policy")
    readonly_fields = (
        "bill_number",
        "principal_amount",
        "amount_due",
        "amount_paid",
        "last_payment_at",
        "issued_at",
        "created_at",
        "updated_at",
    )


@admin.register(BillDispute)
class BillDisputeAdmin(admin.ModelAdmin):
    list_display = (
        "bill",
        "issue_type",
        "status",
        "raised_by",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    )
    list_filter = ("issue_type", "status", "created_at")
    search_fields = (
        "bill__bill_number",
        "description",
        "resolution_summary",
        "admin_notes",
    )
    autocomplete_fields = ("bill", "raised_by", "reviewed_by")
    readonly_fields = ("reviewed_at", "created_at", "updated_at")