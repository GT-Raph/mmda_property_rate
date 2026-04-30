from .access import can_access, get_user_role


def portal_access(request):
    user = request.user

    return {
        "portal_role": get_user_role(user),
        "portal_access": {
            "dashboard": can_access(user, "dashboard"),
            "properties": can_access(user, "properties"),
            "billing": can_access(user, "billing"),
            "payments": can_access(user, "payments"),
            "field_operations": can_access(user, "field_operations"),
            "reports": can_access(user, "reports"),
            "settings": can_access(user, "settings"),
        },
    }