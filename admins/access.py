from django.urls import reverse


ALL_MODULES = (
    "dashboard",
    "properties",
    "billing",
    "payments",
    "field_operations",
    "reports",
    "assembly",
    "settings",
)

ROLE_MODULES = {
    "sys_admin": {
        "dashboard",
        "properties",
        "billing",
        "payments",
        "field_operations",
        "reports",
        "assembly",
        "settings",
    },
    "revenue_admin": {
        "dashboard",
        "properties",
        "billing",
        "payments",
        "field_operations",
        "reports",
        "assembly",
        "settings",
    },
    "property_officer": {
        "dashboard",
        "properties",
        "settings",
    },
    "payment_officer": {
        "dashboard",
        "payments",
        "billing",
        "settings",
    },
    "billing_officer": {
        "dashboard",
        "billing",
        "payments",
        "reports",
        "settings",
    },
    "report_officer": {
        "dashboard",
        "reports",
        "settings",
    },
    "field_officer": {
        "field_operations",
        "settings",
    },
    "citizen": {
        "settings",
    },
}


def get_user_role(user):
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        return "sys_admin"

    profile = getattr(user, "profile", None)
    role = getattr(profile, "role", None)

    if role in ROLE_MODULES:
        return role

    return "citizen"


def build_portal_access(module_names):
    module_names = set(module_names or [])
    return {module: module in module_names for module in ALL_MODULES}


def get_allowed_module_names(user):
    role = get_user_role(user)
    return ROLE_MODULES.get(role, set())


def get_allowed_modules(user):
    """
    Returns a dict like:
    {
        "dashboard": True,
        "properties": True,
        ...
    }
    This is what your templates need for portal_access.dashboard, etc.
    """
    return build_portal_access(get_allowed_module_names(user))


def can_access(user, module_name):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return get_allowed_modules(user).get(module_name, False)


def landing_url_for_user(user):
    role = get_user_role(user)

    if role == "field_officer":
        return reverse("field_operations:field-operations")

    if role == "property_officer":
        return reverse("properties:property-registry")

    if role in ["billing_officer", "payment_officer"]:
        return reverse("billing:billing-management")

    if role == "report_officer":
        return reverse("admins:reports-analytics")

    if role in ["sys_admin", "revenue_admin"]:
        return reverse("admins:admin-dashboard")

    return reverse("admins:settings")