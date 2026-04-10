from django.contrib import admin

from .models import Owner, Property, PropertyPhoto


class PropertyPhotoInline(admin.TabularInline):
    model = PropertyPhoto
    extra = 1
    fields = ("image", "caption", "is_primary", "uploaded_by")
    autocomplete_fields = ("uploaded_by",)


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "primary_phone",
        "email",
        "assembly",
        "linked_user",
    )
    list_filter = ("assembly",)
    search_fields = (
        "full_name",
        "primary_phone",
        "alternate_phone",
        "email",
        "ghana_card_number",
    )
    autocomplete_fields = ("assembly", "linked_user")


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        "property_reference",
        "owner",
        "assembly",
        "area_town",
        "property_use",
        "building_type",
        "rateable_value",
        "verification_status",
        "is_active",
    )
    list_filter = (
        "assembly",
        "property_use",
        "building_type",
        "occupancy_status",
        "verification_status",
        "registration_source",
        "is_exempt",
        "is_active",
    )
    search_fields = (
        "property_reference",
        "owner__full_name",
        "digital_address",
        "address_line",
        "area_town",
        "suburb",
        "landmark",
    )
    readonly_fields = (
        "property_reference",
        "created_at",
        "updated_at",
        "last_verified_at",
    )
    autocomplete_fields = ("assembly", "owner", "registered_by")
    inlines = [PropertyPhotoInline]

    fieldsets = (
        ("Identification", {
            "fields": ("assembly", "owner", "property_reference")
        }),
        ("Location", {
            "fields": (
                "digital_address",
                "address_line",
                "area_town",
                "suburb",
                "landmark",
                "latitude",
                "longitude",
            )
        }),
        ("Classification", {
            "fields": (
                "property_use",
                "building_type",
                "number_of_floors",
                "number_of_units",
                "year_built",
                "occupancy_status",
            )
        }),
        ("Valuation", {
            "fields": (
                "rateable_value",
                "is_exempt",
                "exemption_reason",
            )
        }),
        ("Operations", {
            "fields": (
                "registration_source",
                "verification_status",
                "registered_by",
                "last_verified_at",
                "is_active",
            )
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(PropertyPhoto)
class PropertyPhotoAdmin(admin.ModelAdmin):
    list_display = (
        "property",
        "caption",
        "is_primary",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("is_primary", "created_at")
    search_fields = (
        "property__property_reference",
        "property__owner__full_name",
        "caption",
    )
    autocomplete_fields = ("property", "uploaded_by")