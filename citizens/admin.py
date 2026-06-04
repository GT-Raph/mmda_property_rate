from django.contrib import admin
from .models import CitizenDispute, CitizenDisputeAttachment, CitizenPreference, PropertyCertificate


@admin.register(CitizenPreference)
class CitizenPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "bill_reminders",
        "payment_confirmations",
        "property_updates",
        "promotions_offers",
        "updated_at",
    )
    search_fields = ("user__username", "user__email")


@admin.register(PropertyCertificate)
class PropertyCertificateAdmin(admin.ModelAdmin):
    list_display = (
        "property",
        "certificate_uuid",
        "is_active",
        "issued_at",
    )
    search_fields = (
        "property__property_reference",
        "certificate_uuid",
    )


class CitizenDisputeAttachmentInline(admin.TabularInline):
    model = CitizenDisputeAttachment
    extra = 0


@admin.register(CitizenDispute)
class CitizenDisputeAdmin(admin.ModelAdmin):
    list_display = (
        "dispute_number",
        "user",
        "property_record",
        "bill",
        "dispute_type",
        "status",
        "submitted_at",
    )
    list_filter = ("status", "dispute_type", "assembly", "submitted_at")
    search_fields = (
        "dispute_number",
        "description",
        "user__username",
        "user__email",
        "property_record__property_reference",
        "bill__bill_number",
    )
    readonly_fields = ("dispute_number", "submitted_at", "updated_at", "resolved_at")
    inlines = [CitizenDisputeAttachmentInline]


@admin.register(CitizenDisputeAttachment)
class CitizenDisputeAttachmentAdmin(admin.ModelAdmin):
    list_display = ("dispute", "original_name", "uploaded_at")
    search_fields = ("original_name", "dispute__dispute_number")