"""Failed login limits and temporary password expiry."""

from datetime import timedelta
from math import ceil

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext_lazy as _, ngettext

from .models import LoginFailure


ACCOUNT_FAILURE_LIMIT = 5
# Higher than the account limit, because offices and mobile networks can put
# many people behind one address.
IP_FAILURE_LIMIT = 20
FAILURE_WINDOW = timedelta(minutes=15)
TEMPORARY_PASSWORD_LIFETIME = timedelta(days=7)

User = get_user_model()


def _hashed_key(scope, value):
    return salted_hmac(
        "admins.login_security",
        f"{scope}:{value}",
        algorithm="sha256",
    ).hexdigest()


def account_failure_key(user=None, identifier=""):
    """
    Failures count against the user when one matches, so every login route
    shares one count. An unknown identifier counts the same way, so the limit
    does not reveal which accounts exist.
    """
    if user is not None:
        return _hashed_key("user", user.pk)

    return _hashed_key("identifier", identifier.strip().lower())


def client_ip(request):
    """
    Return the address to limit by, or None when it cannot be trusted.

    With no trusted address the IP limit is skipped. Falling back to
    REMOTE_ADDR behind a proxy would put every visitor in one shared count.
    """
    if settings.CLIENT_IP_HEADER:
        return request.META.get(settings.CLIENT_IP_HEADER) or None

    return request.META.get("REMOTE_ADDR") or None


def _seconds_until_allowed(key, limit):
    now = timezone.now()
    # Once the limit-th newest failure leaves the window, the key is under the
    # limit again.
    blocking_failure = list(
        LoginFailure.objects.filter(
            key=key,
            created_at__gt=now - FAILURE_WINDOW,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)[limit - 1:limit]
    )

    if not blocking_failure:
        return 0

    return (blocking_failure[0] + FAILURE_WINDOW - now).total_seconds()


def _record_failure(keys):
    LoginFailure.objects.filter(
        created_at__lte=timezone.now() - FAILURE_WINDOW,
    ).delete()
    LoginFailure.objects.bulk_create(
        [LoginFailure(key=key) for key in keys]
    )


def clear_login_failures(user):
    """Clear a user's account count. The IP count is left alone on purpose."""
    LoginFailure.objects.filter(key=account_failure_key(user)).delete()


class LoginProtectionMixin:
    """
    Limit failed attempts on an AuthenticationForm and refuse expired
    temporary passwords.

    A form with its own login logic overrides check_credentials, not clean.
    """

    def login_account_key(self, identifier):
        return account_failure_key(
            User.objects.filter(username=identifier).first(),
            identifier,
        )

    def check_credentials(self):
        return super().clean()

    def clean(self):
        identifier = (self.cleaned_data.get("username") or "").strip()

        if not identifier or not self.cleaned_data.get("password"):
            return self.check_credentials()

        limits = [
            (self.login_account_key(identifier), ACCOUNT_FAILURE_LIMIT),
        ]

        ip_address = client_ip(self.request) if self.request else None
        if ip_address:
            limits.append((_hashed_key("ip", ip_address), IP_FAILURE_LIMIT))

        seconds = max(
            _seconds_until_allowed(key, limit)
            for key, limit in limits
        )

        if seconds:
            minutes = ceil(seconds / 60)
            raise forms.ValidationError(
                ngettext(
                    "Too many failed sign-in attempts. Please try again in %(minutes)d minute.",
                    "Too many failed sign-in attempts. Please try again in %(minutes)d minutes.",
                    minutes,
                ) % {"minutes": minutes},
                code="too_many_attempts",
            )

        try:
            cleaned_data = self.check_credentials()
        except forms.ValidationError:
            _record_failure([key for key, _limit in limits])
            raise

        clear_login_failures(self.get_user())
        return cleaned_data

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)

        profile = getattr(user, "profile", None)

        if profile and profile.temporary_password_expired:
            raise forms.ValidationError(
                _(
                    "This temporary password has expired. Use Forgot password "
                    "if your account has an email address, or ask your "
                    "assembly office for a new one."
                ),
                code="temporary_password_expired",
            )


class ProtectedAuthenticationForm(LoginProtectionMixin, AuthenticationForm):
    """Django's username and password form with the login protections added."""
