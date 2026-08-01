from django.contrib.auth import get_user_model
from django.test import TestCase

from admins.models import Assembly, UserProfile
from admins.views import PortalLoginView, _find_citizen_user_by_phone
from properties.models import Owner

User = get_user_model()


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
        UserProfile.objects.create(
            user=user,
            role="citizen",
            assembly=self.assembly,
            phone_number=phone_number,
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
        UserProfile.objects.create(
            user=user,
            role="citizen",
            assembly=assigned_assembly,
            phone_number="0241234567",
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
