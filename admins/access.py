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
    "citizen_dashboard",
)

GROUP_MODULES = {
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
        "dashboard",
        "properties",
        "field_operations",
        "settings",
    },
    "citizen": {
        "citizen_dashboard",
        "settings",
    },
}


def get_user_role(user):
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        return "sys_admin"

    user_group_names = set(user.groups.values_list("name", flat=True))

    priority_order = [
        "sys_admin",
        "revenue_admin",
        "property_officer",
        "payment_officer",
        "billing_officer",
        "report_officer",
        "field_officer",
        "citizen",
    ]

    for role_name in priority_order:
        if role_name in user_group_names:
            return role_name

    return "citizen"


def build_portal_access(module_names):
    module_names = set(module_names or [])
    return {module: module in module_names for module in ALL_MODULES}


def get_allowed_module_names(user):
    if not user.is_authenticated:
        return set()

    if user.is_superuser:
        return set(ALL_MODULES)

    user_group_names = set(user.groups.values_list("name", flat=True))

    allowed = set()
    for group_name in user_group_names:
        allowed.update(GROUP_MODULES.get(group_name, set()))

    if not allowed:
        allowed = GROUP_MODULES.get("citizen", set())

    return allowed


def get_allowed_modules(user):
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

    if role == "citizen":
        return reverse("citizens:dashboard")

    if role in ["sys_admin", "revenue_admin"]:
        return reverse("admins:admin-dashboard")

    return reverse("admins:settings")