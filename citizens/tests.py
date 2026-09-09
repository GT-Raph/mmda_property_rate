import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from admins.models import UserProfile


User = get_user_model()


@override_settings(
    EMAIL_BACKEND=(
        "django.core.mail.backends.locmem.EmailBackend"
    ),
    SECURE_SSL_REDIRECT=False,
)
class CitizenPasswordResetTests(TestCase):
    def _create_user(self, username, email, role):
        user = User.objects.create_user(
            username=username,
            email=email,
            password="Current-pass-123",
        )
        profile, _created = (
            UserProfile.objects.get_or_create(
                user=user
            )
        )
        profile.role = role
        profile.save(update_fields=["role"])
        return user

    def test_citizen_can_request_reset_email(self):
        self._create_user(
            "citizen",
            "citizen@example.com",
            "citizen",
        )

        response = self.client.post(
            reverse(
                "citizens:password-reset"
            ),
            {"email": "citizen@example.com"},
        )

        self.assertRedirects(
            response,
            reverse(
                "citizens:password-reset-done"
            ),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "/owner/password-reset/",
            mail.outbox[0].body,
        )

    def test_owner_reset_does_not_email_staff_account(self):
        self._create_user(
            "staff",
            "staff@example.com",
            "property_officer",
        )

        response = self.client.post(
            reverse(
                "citizens:password-reset"
            ),
            {"email": "staff@example.com"},
        )

        self.assertRedirects(
            response,
            reverse(
                "citizens:password-reset-done"
            ),
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_updates_password_and_clears_temporary_flag(self):
        user = self._create_user(
            "citizen-reset",
            "reset@example.com",
            "citizen",
        )
        user.profile.must_change_password = True
        user.profile.save(
            update_fields=["must_change_password"]
        )

        self.client.post(
            reverse(
                "citizens:password-reset"
            ),
            {"email": "reset@example.com"},
        )
        reset_path = re.search(
            r"http://testserver([^\s]+)",
            mail.outbox[0].body,
        ).group(1)

        token_response = self.client.get(reset_path)
        self.assertEqual(
            token_response.status_code,
            302,
        )
        response = self.client.post(
            token_response.url,
            {
                "new_password1": "New-owner-pass-4827",
                "new_password2": "New-owner-pass-4827",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "citizens:password-reset-complete"
            ),
        )
        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertTrue(
            user.check_password(
                "New-owner-pass-4827"
            )
        )
        self.assertFalse(
            user.profile.must_change_password
        )
