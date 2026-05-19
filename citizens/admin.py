from django.contrib import admin
from .models import CitizenPreference


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