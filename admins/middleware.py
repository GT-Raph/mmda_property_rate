from django.utils import timezone

from admins.models import LoginAudit


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _device_name(user_agent: str) -> str:
    ua = (user_agent or "").lower()

    browser = "Browser"
    if "chrome" in ua and "edg" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    elif "edg" in ua:
        browser = "Edge"

    if "windows" in ua:
        return f"Windows PC - {browser}"
    if "mac os" in ua or "macintosh" in ua:
        return f"Mac - {browser}"
    if "iphone" in ua:
        return f"iPhone - {browser}"
    if "android" in ua:
        return f"Android - {browser}"
    if "linux" in ua:
        return f"Linux - {browser}"

    return browser


class LoginAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated:
            if not request.session.session_key:
                request.session.save()

            session_key = request.session.session_key
            user_agent = request.META.get("HTTP_USER_AGENT", "")
            ip_address = _client_ip(request)

            LoginAudit.objects.update_or_create(
                session_key=session_key,
                defaults={
                    "user": request.user,
                    "user_agent": user_agent,
                    "ip_address": ip_address,
                    "device_name": _device_name(user_agent),
                    "location_label": "Current session",
                    "last_seen": timezone.now(),
                    "is_active": True,
                },
            )

        return response