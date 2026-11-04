import re
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from properties.models import Owner, Property
from properties.utils import link_or_create_citizen_for_owner

from .models import Assembly, LoginFailure


User = get_user_model()

# Stated here rather than imported, so changing a limit has to be deliberate.
ACCOUNT_FAILURE_LIMIT = 5
IP_FAILURE_LIMIT = 20
FAILURE_WINDOW = timedelta(minutes=15)
TEMPORARY_PASSWORD_LIFETIME = timedelta(days=7)

OWNER_PHONE = "0240000099"
LOCKED = "Too many failed sign-in attempts"
WRONG_LOGIN = "Please enter the correct phone number and password."
EXPIRED = "This temporary password has expired"


def logged_in(response):
    return "_auth_user_id" in response.client.session


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    CLIENT_IP_HEADER=None,
)
class LoginSecurityTestCase(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Login Security Assembly",
            short_code="LSA",
            assembly_type="municipal",
            region="Greater Accra",
            is_active=True,
        )
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="Login Security Owner",
            primary_phone=OWNER_PHONE,
        )
        account = link_or_create_citizen_for_owner(self.owner)
        # Fetched again because the returned user caches its pre-expiry profile.
        self.citizen = User.objects.get(pk=account["user"].pk)
        self.temporary_password = account["temporary_password"]

    def owner_login(self, password, phone=OWNER_PHONE, **extra):
        return Client().post(
            reverse("owner-login"),
            {"username": phone, "password": password},
            **extra,
        )

    def portal_login(self, route, username, password):
        client = Client()
        client.post(
            reverse(route),
            {"stage": "assembly", "assembly_id": self.assembly.id},
        )
        return client.post(
            reverse(route),
            {"stage": "login", "username": username, "password": password},
        )

    def make_staff(self, username, role="field_officer", assembly=None, **extra):
        user = User.objects.create_user(
            username=username,
            password="Staff-pass-77123",
            **extra,
        )
        profile = user.profile
        profile.role = role
        profile.assembly = assembly or self.assembly
        profile.must_change_password = False
        profile.save()
        return user

    def age_failures(self):
        LoginFailure.objects.update(
            created_at=timezone.now() - FAILURE_WINDOW - timedelta(seconds=1)
        )

    def fail_until_locked(self):
        for attempt in range(ACCOUNT_FAILURE_LIMIT):
            self.owner_login(f"wrong-{attempt}")

    def expire_temporary_password(self):
        profile = self.citizen.profile
        profile.temporary_password_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        profile.save(update_fields=["temporary_password_expires_at"])


class AccountLimitTests(LoginSecurityTestCase):
    def test_correct_password_is_refused_once_the_limit_is_reached(self):
        for attempt in range(ACCOUNT_FAILURE_LIMIT - 1):
            self.owner_login(f"wrong-{attempt}")

        self.owner_login("one-more-wrong-guess")
        response = self.owner_login(self.temporary_password)

        self.assertContains(response, LOCKED)
        self.assertFalse(logged_in(response))

    def test_correct_password_works_one_failure_below_the_limit(self):
        for attempt in range(ACCOUNT_FAILURE_LIMIT - 1):
            self.owner_login(f"wrong-{attempt}")

        response = self.owner_login(self.temporary_password)

        self.assertTrue(logged_in(response))

    def test_lock_ends_when_the_window_passes(self):
        self.fail_until_locked()
        self.age_failures()

        response = self.owner_login(self.temporary_password)

        self.assertTrue(logged_in(response))

    def test_lock_message_gives_the_wait_in_minutes(self):
        self.fail_until_locked()

        response = self.owner_login(self.temporary_password)

        self.assertContains(response, "Please try again in 15 minutes.")

    def test_successful_login_clears_the_account_count(self):
        for _round in range(2):
            for attempt in range(ACCOUNT_FAILURE_LIMIT - 1):
                self.owner_login(f"wrong-{attempt}")

            response = self.owner_login(self.temporary_password)
            self.assertTrue(logged_in(response))

    def test_attempts_while_locked_are_not_counted_or_hashed(self):
        self.fail_until_locked()
        count_before = LoginFailure.objects.count()

        with patch(
            "django.contrib.auth.base_user.AbstractBaseUser.check_password"
        ) as check_password:
            self.owner_login("another-wrong-guess")

        check_password.assert_not_called()
        self.assertEqual(LoginFailure.objects.count(), count_before)

    def test_unknown_phone_locks_like_a_real_one(self):
        unknown_phone = "0240000098"

        for attempt in range(ACCOUNT_FAILURE_LIMIT):
            response = self.owner_login(f"wrong-{attempt}", phone=unknown_phone)
            self.assertContains(response, WRONG_LOGIN)

        response = self.owner_login("wrong", phone=unknown_phone)

        self.assertContains(response, LOCKED)

    def test_phone_formats_share_one_count(self):
        phones = [OWNER_PHONE, "233240000099", "+233 24 000 0099"]

        for attempt in range(ACCOUNT_FAILURE_LIMIT):
            self.owner_login(f"wrong-{attempt}", phone=phones[attempt % len(phones)])

        response = self.owner_login(self.temporary_password)

        self.assertContains(response, LOCKED)

    def test_login_routes_share_one_count(self):
        self.fail_until_locked()

        response = self.portal_login(
            "portal-login",
            self.citizen.username,
            self.temporary_password,
        )

        self.assertContains(response, LOCKED)
        self.assertFalse(logged_in(response))

    def test_staff_login_routes_lock_after_the_limit(self):
        for route in ("admin-login", "portal-login"):
            with self.subTest(route=route):
                self.make_staff(f"staff-{route}")

                for attempt in range(ACCOUNT_FAILURE_LIMIT):
                    self.portal_login(route, f"staff-{route}", f"wrong-{attempt}")

                response = self.portal_login(
                    route,
                    f"staff-{route}",
                    "Staff-pass-77123",
                )

                self.assertContains(response, LOCKED)
                self.assertFalse(logged_in(response))

                LoginFailure.objects.all().delete()

    def test_staff_username_and_email_share_one_count(self):
        self.make_staff("staff-both", email="staff-both@example.com")

        for attempt in range(ACCOUNT_FAILURE_LIMIT):
            identifier = "staff-both" if attempt % 2 else "staff-both@example.com"
            self.portal_login("admin-login", identifier, f"wrong-{attempt}")

        response = self.portal_login(
            "admin-login",
            "staff-both",
            "Staff-pass-77123",
        )

        self.assertContains(response, LOCKED)

    def test_django_admin_login_locks_after_the_limit(self):
        User.objects.create_superuser(
            username="site-admin",
            email="site-admin@example.com",
            password="Admin-pass-77123",
        )
        url = reverse("admin:login")

        for attempt in range(ACCOUNT_FAILURE_LIMIT):
            Client().post(url, {"username": "site-admin", "password": f"wrong-{attempt}"})

        response = Client().post(
            url,
            {"username": "site-admin", "password": "Admin-pass-77123"},
        )

        self.assertContains(response, LOCKED)
        self.assertFalse(logged_in(response))

    def test_password_reset_clears_the_lock(self):
        self.citizen.email = "owner@example.com"
        self.citizen.save(update_fields=["email"])
        self.fail_until_locked()

        Client().post(
            reverse("citizens:password-reset"),
            {"email": "owner@example.com"},
        )
        reset_path = re.search(
            r"http://testserver([^\s]+)",
            mail.outbox[0].body,
        ).group(1)
        client = Client()
        token_response = client.get(reset_path)
        client.post(
            token_response.url,
            {
                "new_password1": "New-owner-pass-4827",
                "new_password2": "New-owner-pass-4827",
            },
        )

        response = self.owner_login("New-owner-pass-4827")

        self.assertTrue(logged_in(response))


class IpLimitTests(LoginSecurityTestCase):
    def fail_from_one_address(self, count, **extra):
        for attempt in range(count):
            self.owner_login("wrong", phone=f"02411{attempt:05d}", **extra)

    def test_address_locks_across_accounts(self):
        self.fail_from_one_address(IP_FAILURE_LIMIT)

        response = self.owner_login(self.temporary_password)

        self.assertContains(response, LOCKED)
        self.assertFalse(logged_in(response))

    def test_other_addresses_are_not_affected(self):
        self.fail_from_one_address(IP_FAILURE_LIMIT)

        response = self.owner_login(
            self.temporary_password,
            REMOTE_ADDR="10.0.0.2",
        )

        self.assertTrue(logged_in(response))

    def test_successful_login_does_not_clear_the_address_count(self):
        self.fail_from_one_address(IP_FAILURE_LIMIT - 1)

        response = self.owner_login(self.temporary_password)
        self.assertTrue(logged_in(response))

        self.owner_login("wrong", phone="0249999999")
        response = self.owner_login(self.temporary_password)

        self.assertContains(response, LOCKED)

    @override_settings(CLIENT_IP_HEADER="HTTP_TRUE_CLIENT_IP")
    def test_fake_forwarded_for_values_do_not_escape_the_limit(self):
        for attempt in range(IP_FAILURE_LIMIT):
            self.owner_login(
                "wrong",
                phone=f"02411{attempt:05d}",
                HTTP_TRUE_CLIENT_IP="203.0.113.5",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{attempt}",
            )

        locked = self.owner_login(
            self.temporary_password,
            HTTP_TRUE_CLIENT_IP="203.0.113.5",
            HTTP_X_FORWARDED_FOR="198.51.100.200",
        )
        self.assertContains(locked, LOCKED)

        other_address = self.owner_login(
            self.temporary_password,
            HTTP_TRUE_CLIENT_IP="203.0.113.6",
        )
        self.assertTrue(logged_in(other_address))

    @override_settings(CLIENT_IP_HEADER="HTTP_TRUE_CLIENT_IP")
    def test_missing_trusted_header_does_not_lock_everyone_together(self):
        self.fail_from_one_address(IP_FAILURE_LIMIT)

        response = self.owner_login(self.temporary_password)

        self.assertTrue(logged_in(response))

    def test_stored_keys_do_not_contain_phone_numbers_or_addresses(self):
        self.owner_login("wrong")

        keys = list(LoginFailure.objects.values_list("key", flat=True))

        self.assertEqual(len(keys), 2)
        for key in keys:
            self.assertEqual(len(key), 64)
            self.assertNotIn(OWNER_PHONE, key)
            self.assertNotIn("127.0.0.1", key)

    def test_old_failures_are_deleted_by_the_next_failure(self):
        self.owner_login("wrong")
        self.age_failures()

        self.owner_login("wrong again")

        self.assertEqual(LoginFailure.objects.count(), 2)


class OwnerLoginMessageTests(LoginSecurityTestCase):
    def test_unknown_phone_and_wrong_password_look_the_same(self):
        unknown = self.owner_login("wrong", phone="0240000098")
        wrong = self.owner_login("wrong")

        self.assertEqual(
            unknown.context["form"].non_field_errors(),
            wrong.context["form"].non_field_errors(),
        )
        self.assertContains(unknown, WRONG_LOGIN)
        self.assertNotContains(unknown, "No active property owner")

    def test_unknown_phone_still_hashes_the_password(self):
        with patch(
            "django.contrib.auth.base_user.AbstractBaseUser.set_password"
        ) as set_password:
            self.owner_login("wrong", phone="0240000098")

        set_password.assert_called_once_with("wrong")


class TemporaryPasswordExpiryTests(LoginSecurityTestCase):
    def test_new_account_gets_an_expiry(self):
        remaining = (
            self.citizen.profile.temporary_password_expires_at - timezone.now()
        )

        self.assertLessEqual(remaining, TEMPORARY_PASSWORD_LIFETIME)
        self.assertGreater(
            remaining,
            TEMPORARY_PASSWORD_LIFETIME - timedelta(minutes=1),
        )

    def test_password_works_before_it_expires(self):
        response = self.owner_login(self.temporary_password)

        self.assertTrue(logged_in(response))

    def test_expired_password_is_refused_on_owner_login(self):
        self.expire_temporary_password()

        response = self.owner_login(self.temporary_password)

        self.assertContains(response, EXPIRED)
        self.assertFalse(logged_in(response))

    def test_expired_password_is_refused_on_portal_login(self):
        self.expire_temporary_password()

        response = self.portal_login(
            "portal-login",
            self.citizen.username,
            self.temporary_password,
        )

        self.assertContains(response, EXPIRED)
        self.assertFalse(logged_in(response))

    def test_wrong_password_does_not_reveal_expiry(self):
        self.expire_temporary_password()

        response = self.owner_login("wrong")

        self.assertContains(response, WRONG_LOGIN)
        self.assertNotContains(response, EXPIRED)

    def test_owner_who_set_their_own_password_is_not_affected(self):
        self.expire_temporary_password()
        self.citizen.set_password("Own-owner-pass-4827")
        self.citizen.save(update_fields=["password"])
        profile = self.citizen.profile
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])

        response = self.owner_login("Own-owner-pass-4827")

        self.assertTrue(logged_in(response))

    def test_password_reset_replaces_an_expired_password(self):
        self.citizen.email = "owner@example.com"
        self.citizen.save(update_fields=["email"])
        self.expire_temporary_password()

        Client().post(
            reverse("citizens:password-reset"),
            {"email": "owner@example.com"},
        )
        reset_path = re.search(
            r"http://testserver([^\s]+)",
            mail.outbox[0].body,
        ).group(1)
        client = Client()
        token_response = client.get(reset_path)
        client.post(
            token_response.url,
            {
                "new_password1": "New-owner-pass-4827",
                "new_password2": "New-owner-pass-4827",
            },
        )

        response = self.owner_login("New-owner-pass-4827")

        self.assertTrue(logged_in(response))

    def test_migration_starts_the_clock_for_pending_owners_only(self):
        migration = import_module(
            "admins.migrations.0007_login_failures_and_temporary_password_expiry"
        )
        pending_owner = self.citizen.profile
        pending_owner.temporary_password_expires_at = None
        pending_owner.save(update_fields=["temporary_password_expires_at"])

        changed_owner = User.objects.create_user(username="changed-owner").profile
        changed_owner.must_change_password = False
        changed_owner.save(update_fields=["must_change_password"])

        pending_staff = self.make_staff("pending-staff").profile
        pending_staff.must_change_password = True
        pending_staff.save(update_fields=["must_change_password"])

        migration.start_expiry_for_pending_owners(apps, None)

        for profile in (pending_owner, changed_owner, pending_staff):
            profile.refresh_from_db()

        self.assertIsNotNone(pending_owner.temporary_password_expires_at)
        self.assertIsNone(changed_owner.temporary_password_expires_at)
        self.assertIsNone(pending_staff.temporary_password_expires_at)


class ReissueTemporaryPasswordTests(LoginSecurityTestCase):
    def setUp(self):
        super().setUp()
        self.property = self.make_property(self.owner, self.assembly)
        self.officer = self.make_staff("property-officer", role="property_officer")
        self.url = reverse(
            "properties:reissue-temporary-password",
            args=[self.property.id],
        )
        self.client.force_login(self.officer)

    def make_property(self, owner, assembly):
        return Property.objects.create(
            assembly=assembly,
            owner=owner,
            address_line="1 Login Road",
            area_town="Accra",
            property_use="residential",
            building_type="apartment",
            verification_status="pending",
            is_exempt=True,
        )

    def test_staff_can_issue_a_new_password_to_an_expired_owner(self):
        self.expire_temporary_password()
        self.fail_until_locked()

        response = self.client.post(self.url, follow=True)

        new_password = re.search(
            r"Prms-\d{6}",
            response.content.decode(),
        ).group(0)
        login = self.owner_login(new_password)
        self.assertTrue(logged_in(login))

        self.citizen.profile.refresh_from_db()
        self.assertFalse(self.citizen.profile.temporary_password_expired)

    def test_old_password_stops_working(self):
        self.client.post(self.url)

        response = self.owner_login(self.temporary_password)

        self.assertContains(response, WRONG_LOGIN)

    def test_refused_once_the_owner_has_set_their_own_password(self):
        profile = self.citizen.profile
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
        password_hash = self.citizen.password

        response = self.client.post(self.url, follow=True)

        self.citizen.refresh_from_db()
        self.assertEqual(self.citizen.password, password_hash)
        self.assertContains(response, "no temporary password to replace")

    def test_refused_for_an_owner_linked_to_a_staff_account(self):
        staff_user = self.make_staff("linked-staff")
        profile = staff_user.profile
        profile.must_change_password = True
        profile.save(update_fields=["must_change_password"])
        self.owner.linked_user = staff_user
        self.owner.save(update_fields=["linked_user"])
        password_hash = staff_user.password

        self.client.post(self.url)

        staff_user.refresh_from_db()
        self.assertEqual(staff_user.password, password_hash)

    def test_get_is_not_allowed(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_citizen_cannot_issue_passwords(self):
        password_hash = self.citizen.password
        profile = self.citizen.profile
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
        client = Client()
        client.force_login(self.citizen)

        response = client.post(self.url)

        self.assertNotEqual(response.status_code, 200)
        self.citizen.refresh_from_db()
        self.assertEqual(self.citizen.password, password_hash)

    def test_staff_from_another_assembly_get_not_found(self):
        other_assembly = Assembly.objects.create(
            name="Other Assembly",
            short_code="OTH",
            assembly_type="municipal",
            region="Greater Accra",
            is_active=True,
        )
        client = Client()
        client.force_login(
            self.make_staff(
                "other-officer",
                role="property_officer",
                assembly=other_assembly,
            )
        )
        password_hash = self.citizen.password

        response = client.post(self.url)

        self.assertEqual(response.status_code, 404)
        self.citizen.refresh_from_db()
        self.assertEqual(self.citizen.password, password_hash)

    def test_unassigned_field_officer_gets_not_found(self):
        client = Client()
        client.force_login(self.make_staff("field-officer", role="field_officer"))

        response = client.post(self.url)

        self.assertEqual(response.status_code, 404)

    def test_button_shows_only_while_the_owner_is_on_a_temporary_password(self):
        detail_url = reverse(
            "properties:property-detail",
            args=[self.property.id],
        )

        self.assertContains(
            self.client.get(detail_url),
            "Issue New Temporary Password",
        )

        profile = self.citizen.profile
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])

        self.assertNotContains(
            self.client.get(detail_url),
            "Issue New Temporary Password",
        )
