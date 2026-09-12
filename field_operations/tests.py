from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from admins.models import Assembly, UserProfile
from properties.models import Owner, Property

from .models import FieldAssignment, FieldVisit
from .views import _prms_gps_distance_meters


User = get_user_model()


class GpsDistanceTests(TestCase):
    def test_haversine_distance_is_returned_in_meters(self):
        distance = _prms_gps_distance_meters(
            Decimal("5.600000"),
            Decimal("-0.180000"),
            Decimal("5.601000"),
            Decimal("-0.180000"),
        )

        self.assertGreater(distance, Decimal("110"))
        self.assertLess(distance, Decimal("112"))


@override_settings(
    SECURE_SSL_REDIRECT=False,
    FIELD_GPS_DEMO_MODE=False,
)
class FieldVerificationGpsTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="GPS Test Assembly",
            short_code="GPS",
            assembly_type="municipal",
            region="Greater Accra",
            field_gps_validation_enabled=True,
            field_gps_radius_meters=100,
        )
        self.officer = User.objects.create_user(
            username="field-officer",
            password="Officer-pass-123",
        )
        profile, _created = (
            UserProfile.objects.get_or_create(
                user=self.officer
            )
        )
        profile.role = "field_officer"
        profile.assembly = self.assembly
        profile.must_change_password = False
        profile.save(
            update_fields=[
                "role",
                "assembly",
                "must_change_password",
            ]
        )
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="GPS Owner",
            primary_phone="0240000000",
        )
        self.property = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="1 Location Street",
            area_town="Accra",
            latitude=Decimal("5.600000"),
            longitude=Decimal("-0.180000"),
            property_use="residential",
            building_type="apartment",
            rateable_value=Decimal("100.00"),
        )
        self.assignment = FieldAssignment.objects.create(
            assembly=self.assembly,
            property=self.property,
            officer=self.officer,
        )
        self.client.force_login(self.officer)

    def _post(self, latitude, longitude, status="verified"):
        return self.client.post(
            reverse(
                "field_operations:field-officer-verify-property",
                args=[self.property.pk],
            ),
            {
                "property_id": self.property.pk,
                "property_reference": self.property.property_reference,
                "verification_type": "property_verification",
                "verification_status": status,
                "owner_present": "yes",
                "notes": "The property details were checked on site.",
                "latitude": latitude,
                "longitude": longitude,
                "gps_accuracy": "8.50",
            },
        )

    def test_matching_gps_allows_verification_and_preserves_baseline(self):
        response = self._post(
            "5.600100",
            "-0.180100",
        )

        self.assertRedirects(
            response,
            reverse(
                "field_operations:field-officer-stats"
            ),
        )
        self.property.refresh_from_db()
        self.assertEqual(
            self.property.latitude,
            Decimal("5.600000"),
        )
        self.assertEqual(
            self.property.longitude,
            Decimal("-0.180000"),
        )
        self.assertEqual(
            self.property.verification_status,
            "verified",
        )
        visit = FieldVisit.objects.get(
            property=self.property
        )
        self.assertEqual(
            visit.gps_validation_status,
            "matched",
        )

    def test_outside_radius_cannot_be_marked_verified(self):
        response = self._post(
            "5.610000",
            "-0.180000",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GPS mismatch")
        self.property.refresh_from_db()
        self.assertEqual(
            self.property.verification_status,
            "pending",
        )
        self.assertFalse(
            FieldVisit.objects.filter(
                property=self.property
            ).exists()
        )

    def test_outside_radius_can_be_flagged_for_review(self):
        response = self._post(
            "5.610000",
            "-0.180000",
            status="flagged",
        )

        self.assertEqual(response.status_code, 302)
        visit = FieldVisit.objects.get(
            property=self.property
        )
        self.assertEqual(
            visit.gps_validation_status,
            "outside_radius",
        )

    @override_settings(FIELD_GPS_DEMO_MODE=True)
    def test_demo_mode_allows_remote_verification_and_records_mismatch(self):
        response = self._post(
            "5.610000",
            "-0.180000",
        )

        self.assertRedirects(
            response,
            reverse(
                "field_operations:field-officer-stats"
            ),
        )
        self.property.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.property.verification_status,
            "verified",
        )
        self.assertEqual(
            self.assignment.status,
            "completed",
        )
        visit = FieldVisit.objects.get(
            property=self.property
        )
        self.assertEqual(
            visit.gps_validation_status,
            "outside_radius",
        )

    @override_settings(FIELD_GPS_DEMO_MODE=True)
    def test_demo_mode_allows_verification_without_gps_capture(self):
        response = self._post("", "")

        self.assertRedirects(
            response,
            reverse(
                "field_operations:field-officer-stats"
            ),
        )
        self.property.refresh_from_db()
        self.assertEqual(
            self.property.verification_status,
            "verified",
        )
        visit = FieldVisit.objects.get(
            property=self.property
        )
        self.assertIsNone(visit.latitude)
        self.assertIsNone(visit.longitude)
        self.assertEqual(
            visit.gps_validation_status,
            "disabled",
        )
