from .access import (
    can_access,
    get_user_role,
)
from .models import (
    UserNotification,
)


def portal_access(request):
    user = request.user

    role = get_user_role(
        user
    )

    profile = (
        getattr(user, "profile", None)
        if user and user.is_authenticated
        else None
    )
    portal_mandatory_modal_active = bool(
        role == "citizen"
        and profile
        and profile.must_change_password
    )

    unread_notification_count = 0
    latest_unread_notification = None

    if (
        user
        and user.is_authenticated
    ):
        unread_notifications = (
            UserNotification.objects
            .filter(
                user=user,
                is_read=False,
            )
            .order_by(
                "-created_at",
            )
        )

        unread_notification_count = (
            unread_notifications.count()
        )

        if not portal_mandatory_modal_active:
            latest_unread_notification = (
                unread_notifications.first()
            )

    return {
        "portal_role": role,

        "portal_access": {
            "dashboard": (
                can_access(
                    user,
                    "dashboard",
                )
            ),
            "properties": (
                can_access(
                    user,
                    "properties",
                )
            ),
            "billing": (
                can_access(
                    user,
                    "billing",
                )
            ),
            "payments": (
                can_access(
                    user,
                    "payments",
                )
            ),
            "field_operations": (
                can_access(
                    user,
                    "field_operations",
                )
            ),
            "reports": (
                can_access(
                    user,
                    "reports",
                )
            ),
            "assembly": (
                can_access(
                    user,
                    "assembly",
                )
            ),
            "settings": (
                can_access(
                    user,
                    "settings",
                )
            ),
        },

        "unread_notification_count": (
            unread_notification_count
        ),

        "latest_unread_notification": (
            latest_unread_notification
        ),

        "portal_mandatory_modal_active": (
            portal_mandatory_modal_active
        ),
    }
