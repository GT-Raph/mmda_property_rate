from django.urls import reverse


ROLE_MODULES = {
    "super_admin": {
        "dashboard",
        "properties",
        "billing",
        "payments",
        "field_operations",
        "reports",
        "settings",
    },
    "property_officer": {
        "dashboard",
        "properties",
        "settings",
    },
    "billing_officer": {
        "dashboard",
        "billing",
        "payments",
        "reports",
        "settings",
    },
    "payment_officer": {
        "dashboard",
        "payments",
        "billing",
        "settings",
    },
    "field_officer": {
        "field_operations",
        "settings",
    },
    "report_officer": {
        "dashboard",
        "reports",
        "settings",
    },
    "viewer": {
        "dashboard",
        "settings",
    },
}


def get_user_role(user):
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        return "super_admin"

    profile = getattr(user, "profile", None)
    if profile and profile.role:
        return profile.role

    return "viewer"


def get_allowed_modules(user):
    role = get_user_role(user)
    return ROLE_MODULES.get(role, set())


def can_access(user, module_name):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return module_name in get_allowed_modules(user)


def landing_url_for_user(user):
    role = get_user_role(user)

    if role == "field_officer":
        return reverse("field_operations:field-operations")

    if role in ["billing_officer", "payment_officer"]:
        return reverse("billing:billing-management")

    if role == "property_officer":
        return reverse("properties:property-registry")

    if role == "report_officer":
        return reverse("admins:reports-analytics")

    return reverse("admins:admin-dashboard")