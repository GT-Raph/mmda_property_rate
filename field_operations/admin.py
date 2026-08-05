from django.contrib import admin

from .models import EnumerationRecord, FieldAssignment, FieldVisit


@admin.register(EnumerationRecord)
class EnumerationRecordAdmin(admin.ModelAdmin):
    list_display = (
        "owner_name",
        "assembly",
        "area_town",
        "property_use",
        "building_type",
        "status",
        "enumerator",
        "converted_property",
        "created_at",
    )
    list_filter = (
        "assembly",
        "status",
        "property_use",
        "building_type",
        "created_at",
    )
    search_fields = (
        "owner_name",
        "owner_phone",
        "owner_email",
        "address_line",
        "area_town",
        "digital_address",
    )
    readonly_fields = ("reviewed_at", "created_at", "updated_at")
    autocomplete_fields = (
        "assembly",
        "enumerator",
        "reviewed_by",
        "converted_property",
    )


@admin.register(FieldVisit)
class FieldVisitAdmin(admin.ModelAdmin):
    list_display = (
        "property",
        "assembly",
        "officer",
        "visit_type",
        "payment_status_seen",
        "outcome",
        "amount_outstanding_snapshot",
        "visited_at",
    )
    list_filter = (
        "assembly",
        "visit_type",
        "payment_status_seen",
        "outcome",
        "visited_at",
    )
    search_fields = (
        "property__property_reference",
        "property__owner__full_name",
        "notes",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("assembly", "property", "officer")


@admin.register(FieldAssignment)
class FieldAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "property",
        "officer",
        "assembly",
        "status",
        "priority",
        "due_date",
        "assigned_at",
        "completed_at",
    )
    list_filter = ("status", "priority", "assembly", "due_date")
    search_fields = (
        "property__property_reference",
        "property__owner__full_name",
        "officer__username",
        "officer__first_name",
        "officer__last_name",
    )
    autocomplete_fields = ("property", "officer", "assigned_by")