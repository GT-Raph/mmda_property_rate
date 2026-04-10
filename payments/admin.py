from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_reference",
        "assembly",
        "property",
        "bill",
        "amount",
        "payment_method",
        "status",
        "reconciliation_status",
        "applied_to_bill",
        "paid_at",
    )
    list_filter = (
        "assembly",
        "payment_method",
        "status",
        "reconciliation_status",
        "applied_to_bill",
        "paid_at",
    )
    search_fields = (
        "transaction_reference",
        "external_reference",
        "payer_name",
        "payer_phone",
        "property_reference_entered",
        "property__property_reference",
        "bill__bill_number",
    )
    readonly_fields = (
        "paid_at",
        "reconciled_at",
        "applied_to_bill",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("assembly", "property", "bill")