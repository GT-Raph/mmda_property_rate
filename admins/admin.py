from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group

from .models import Assembly, ReportRun, UserProfile

User = get_user_model()


@admin.register(Assembly)
class AssemblyAdmin(admin.ModelAdmin):
    list_display = ("name", "short_code", "assembly_type", "region", "is_active")
    search_fields = ("name", "short_code", "region")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "assembly", "employee_id", "is_verified")
    list_filter = ("role", "assembly", "is_verified")
    search_fields = ("user__username", "user__first_name", "user__last_name", "employee_id")


@admin.register(ReportRun)
class ReportRunAdmin(admin.ModelAdmin):
    list_display = ("report_key", "generated_by", "file_format", "rows_count", "created_at")
    list_filter = ("report_key", "file_format", "created_at")
    search_fields = ("report_key", "generated_by__username")


def assign_group(modeladmin, request, queryset, group_name):
    group = Group.objects.get(name=group_name)
    updated = 0

    for user in queryset:
        user.groups.clear()
        user.groups.add(group)

        profile = getattr(user, "profile", None)
        if profile:
            profile.role = group_name
            profile.save(update_fields=["role"])

        updated += 1

    modeladmin.message_user(request, f"{updated} user(s) assigned to {group_name}.")


@admin.action(description="Assign selected users to sys_admin")
def make_sys_admin(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "sys_admin")


@admin.action(description="Assign selected users to revenue_admin")
def make_revenue_admin(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "revenue_admin")


@admin.action(description="Assign selected users to property_officer")
def make_property_officer(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "property_officer")


@admin.action(description="Assign selected users to billing_officer")
def make_billing_officer(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "billing_officer")


@admin.action(description="Assign selected users to payment_officer")
def make_payment_officer(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "payment_officer")


@admin.action(description="Assign selected users to report_officer")
def make_report_officer(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "report_officer")


@admin.action(description="Assign selected users to field_officer")
def make_field_officer(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "field_officer")


@admin.action(description="Assign selected users to citizen")
def make_citizen(modeladmin, request, queryset):
    assign_group(modeladmin, request, queryset, "citizen")


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    actions = [
        make_sys_admin,
        make_revenue_admin,
        make_property_officer,
        make_billing_officer,
        make_payment_officer,
        make_report_officer,
        make_field_officer,
        make_citizen,
    ]