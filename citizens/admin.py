from django.contrib import admin
from .models import CitizenPreference, PropertyCertificate


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