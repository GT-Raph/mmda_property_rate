from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from admins.access import get_user_role
from admins.models import LoginAudit


def _client_ip(request):
    forwarded = request.META.get(
        "HTTP_X_FORWARDED_FOR"
    )

    if forwarded:
        return (
            forwarded
            .split(",")[0]
            .strip()
        )

    return request.META.get(
        "REMOTE_ADDR"
    )


def _device_name(
    user_agent: str,
) -> str:
    ua = (
        user_agent
        or ""
    ).lower()

    browser = "Browser"

    if (
        "chrome" in ua
        and "edg" not in ua
    ):
        browser = "Chrome"

    elif "firefox" in ua:
        browser = "Firefox"

    elif (
        "safari" in ua
        and "chrome" not in ua
    ):
        browser = "Safari"

    elif "edg" in ua:
        browser = "Edge"

    if "windows" in ua:
        return (
            f"Windows PC - {browser}"
        )

    if (
        "mac os" in ua
        or "macintosh" in ua
    ):
        return (
            f"Mac - {browser}"
        )

    if "iphone" in ua:
        return (
            f"iPhone - {browser}"
        )

    if "android" in ua:
        return (
            f"Android - {browser}"
        )

    if "linux" in ua:
        return (
            f"Linux - {browser}"
        )

    return browser


class ForcePasswordChangeMiddleware:
    """
    Prevent a user with a temporary password
    from accessing the rest of the system
    until the password is changed.
    """

    def __init__(
        self,
        get_response,
    ):
        self.get_response = (
            get_response
        )

    def __call__(
        self,
        request,
    ):
        user = getattr(
            request,
            "user",
            None,
        )

        if (
            not user
            or not user.is_authenticated
            or user.is_superuser
        ):
            return self.get_response(
                request
            )

        profile = getattr(
            user,
            "profile",
            None,
        )

        if (
            not profile
            or not profile.must_change_password
        ):
            return self.get_response(
                request
            )

        role = get_user_role(
            user
        )

        if role == "citizen":
            profile_path = reverse(
                "citizens:profile"
            )

            password_post_path = reverse(
                "citizens:change-password"
            )

            if (
                request.path
                == password_post_path
                and request.method
                == "POST"
            ):
                return self.get_response(
                    request
                )

            if (
                request.path
                == profile_path
                and request.method
                == "GET"
                and request.GET.get(
                    "modal"
                )
                == "password"
            ):
                return self.get_response(
                    request
                )

            return redirect(
                (
                    f"{profile_path}"
                    "?modal=password"
                )
            )

        settings_path = reverse(
            "admins:settings"
        )

        if request.path == settings_path:

            if (
                request.method == "POST"
                and request.POST.get(
                    "action"
                )
                == "change_password"
            ):
                return self.get_response(
                    request
                )

            if (
                request.method == "GET"
                and request.GET.get(
                    "tab"
                )
                == "password"
            ):
                return self.get_response(
                    request
                )

        return redirect(
            (
                f"{settings_path}"
                "?tab=password"
            )
        )


class LoginAuditMiddleware:
    def __init__(
        self,
        get_response,
    ):
        self.get_response = (
            get_response
        )

    def __call__(
        self,
        request,
    ):
        response = self.get_response(
            request
        )

        if request.user.is_authenticated:

            if not request.session.session_key:
                request.session.save()

            session_key = (
                request.session.session_key
            )

            user_agent = (
                request.META.get(
                    "HTTP_USER_AGENT",
                    "",
                )
            )

            ip_address = _client_ip(
                request
            )

            LoginAudit.objects.update_or_create(
                session_key=session_key,
                defaults={
                    "user": request.user,
                    "user_agent": user_agent,
                    "ip_address": ip_address,
                    "device_name": (
                        _device_name(
                            user_agent
                        )
                    ),
                    "location_label": (
                        "Current session"
                    ),
                    "last_seen": (
                        timezone.now()
                    ),
                    "is_active": True,
                },
            )

        return response