from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from admins.models import Assembly, UserProfile
from admins.views import PortalLoginView, _find_citizen_user_by_phone
from properties.models import Owner

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminPasswordVisibilityTests(TestCase):
    def test_admin_login_loads_password_visibility_control(self):
        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "css/password_visibility.css",
        )
        self.assertContains(
            response,
            "js/password_visibility.js",
        )


class CitizenPhoneLookupTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Test Assembly",
            short_code="TA",
            assembly_type="municipal",
            region="Greater Accra",
            is_active=True,
        )

    def _create_citizen(self, username, phone_number=""):
        user = User.objects.create_user(
            username=username,
            password="secret123",
            is_active=True,
        )
        profile, _created = UserProfile.objects.get_or_create(
            user=user,
        )
        profile.role = "citizen"
        profile.assembly = self.assembly
        profile.phone_number = phone_number
        profile.save(
            update_fields=[
                "role",
                "assembly",
                "phone_number",
            ]
        )
        return user

    def test_find_citizen_user_by_phone_returns_single_match_once(self):
        user = self._create_citizen("citizen-one", "")
        Owner.objects.create(
            assembly=self.assembly,
            linked_user=user,
            full_name="Citizen One",
            primary_phone="233241234567",
        )

        with self.assertNumQueries(2):
            matched_user = _find_citizen_user_by_phone("0241234567")

        self.assertEqual(matched_user.pk, user.pk)


class PortalLoginViewAccessTests(TestCase):
    def test_citizen_denial_message_covers_all_access_checks(self):
        assigned_assembly = Assembly.objects.create(
            name="Assigned Assembly",
            short_code="AA",
            assembly_type="municipal",
            region="Greater Accra",
            is_active=True,
        )
        selected_assembly = Assembly.objects.create(
            name="Selected Assembly",
            short_code="SA",
            assembly_type="municipal",
            region="Greater Accra",
            is_active=True,
        )
        user = User.objects.create_user(
            username="citizen-two",
            password="secret123",
            is_active=True,
        )
        profile, _created = UserProfile.objects.get_or_create(
            user=user,
        )
        profile.role = "citizen"
        profile.assembly = assigned_assembly
        profile.phone_number = "0241234567"
        profile.save(
            update_fields=[
                "role",
                "assembly",
                "phone_number",
            ]
        )

        allowed, message = PortalLoginView().user_can_access_selected_assembly(
            user,
            selected_assembly,
        )

        self.assertFalse(allowed)
        self.assertEqual(
            str(message),
            (
                "This citizen account is not authorized to access the selected "
                "assembly because it is not linked to a property owner record, "
                "does not use the selected assembly as its default assembly, "
                "and is not included in its allowed assemblies."
            ),
        )


class AdminAnalyticsViewTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Analytics Assembly",
            short_code="AN",
            assembly_type="municipal",
            region="Greater Accra",
            is_active=True,
        )
        self.user = User.objects.create_superuser(
            username="analytics-admin",
            email="analytics@example.com",
            password="Admin-pass-123",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_assembly_id"] = self.assembly.pk
        session.save()

    def test_dashboard_exposes_complete_operational_summary(self):
        response = self.client.get(
            reverse("admins:admin-dashboard"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        titles = {card["title"] for card in response.context["summary_cards"]}
        self.assertTrue(
            {
                "Total Properties",
                "Verified Properties",
                "Pending Verification",
                "Property Owners",
                "Bills Generated",
                "Payments Recorded",
                "Outstanding Payments",
            }.issubset(titles)
        )

    def test_reports_exposes_monthly_quarterly_and_yearly_datasets(self):
        response = self.client.get(
            reverse("admins:reports-analytics"),
            {"year": timezone.localdate().year},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        charts = response.context["analytics_charts"]
        self.assertEqual(len(charts["monthly"]["labels"]), 12)
        self.assertEqual(len(charts["quarterly"]["labels"]), 4)
        self.assertEqual(len(charts["yearly"]["labels"]), 5)
        self.assertContains(response, "Monthly Activity")
        self.assertContains(response, "Quarterly Finance")
        self.assertContains(response, "Yearly Activity")
