from django.contrib import admin

from .models import Assembly, UserProfile


@admin.register(Assembly)
class AssemblyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "short_code",
        "assembly_type",
        "region",
        "active_billing_year",
        "is_active",
    )
    list_filter = ("assembly_type", "region", "is_active")
    search_fields = ("name", "short_code", "region", "district")
    ordering = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "role",
        "assembly",
        "phone_number",
        "employee_id",
        "is_verified",
    )
    list_filter = ("role", "assembly", "is_verified")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "phone_number",
        "employee_id",
    )
    autocomplete_fields = ("user", "assembly")