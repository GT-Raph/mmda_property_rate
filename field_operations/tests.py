from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from admins.models import Assembly, UserProfile
from citizens.views import _property_can_accept_payment
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


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminAssignmentSearchTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Assignment Search Assembly",
            short_code="ASA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        self.other_assembly = Assembly.objects.create(
            name="Other Search Assembly",
            short_code="OSA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        self.admin = User.objects.create_user(
            username="assignment-admin",
            password="Admin-pass-123",
        )
        admin_profile, _created = UserProfile.objects.get_or_create(user=self.admin)
        admin_profile.role = "property_officer"
        admin_profile.assembly = self.assembly
        admin_profile.must_change_password = False
        admin_profile.save(update_fields=["role", "assembly", "must_change_password"])
        self.officer = User.objects.create_user(
            username="search-field-officer",
            password="Officer-pass-123",
        )
        officer_profile, _created = UserProfile.objects.get_or_create(user=self.officer)
        officer_profile.role = "field_officer"
        officer_profile.assembly = self.assembly
        officer_profile.must_change_password = False
        officer_profile.save(update_fields=["role", "assembly", "must_change_password"])
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="Ama Searchable Owner",
            primary_phone="0247654321",
        )
        self.property = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="14 Liberation Road",
            area_town="Mamprobi",
            property_use="residential",
            building_type="detached",
            is_exempt=True,
        )
        other_owner = Owner.objects.create(
            assembly=self.other_assembly,
            full_name="Ama Searchable Owner",
            primary_phone="0247654321",
        )
        self.out_of_scope_property = Property.objects.create(
            assembly=self.other_assembly,
            owner=other_owner,
            address_line="14 Liberation Road",
            area_town="Mamprobi",
            property_use="residential",
            building_type="detached",
            is_exempt=True,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session["active_assembly_id"] = self.assembly.pk
        session.save()
        self.url = reverse("field_operations:assign-field-officer-property")

    def test_search_matches_exact_and_partial_reference(self):
        for query in (self.property.property_reference, self.property.property_reference[3:9]):
            with self.subTest(query=query):
                response = self.client.get(self.url, {"q": query})
                self.assertQuerySetEqual(
                    response.context["properties"],
                    [self.property],
                    transform=lambda item: item,
                )

    def test_search_matches_owner_address_town_and_phone(self):
        for query in ("Searchable Owner", "Liberation", "mamprobi", "0247654"):
            with self.subTest(query=query):
                response = self.client.get(self.url, {"q": query})
                self.assertEqual(list(response.context["properties"]), [self.property])

    def test_search_no_results_and_assembly_scope(self):
        response = self.client.get(self.url, {"q": "not-present"})
        self.assertEqual(list(response.context["properties"]), [])
        scoped = self.client.get(self.url, {"q": "Ama Searchable Owner"})
        self.assertEqual(list(scoped.context["properties"]), [self.property])
        self.assertNotContains(scoped, self.out_of_scope_property.property_reference)

    def test_assignment_works_from_filtered_results(self):
        response = self.client.post(
            f"{self.url}?q={self.property.property_reference}",
            {
                "property_ids": [str(self.property.pk)],
                "officer_id": str(self.officer.pk),
                "priority": "medium",
                "notes": "Search result assignment",
            },
        )
        self.assertRedirects(response, self.url)
        self.assertTrue(
            FieldAssignment.objects.filter(
                property=self.property,
                officer=self.officer,
                status="assigned",
            ).exists()
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class FieldOfficerAssignmentListTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Officer Assignment Assembly",
            short_code="OAA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        self.officer = self._officer("list-officer")
        self.other_officer = self._officer("other-list-officer")
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="Abena Assignment Owner",
            primary_phone="0551234567",
        )
        self.assigned = self._assignment(
            "1 Assigned Lane",
            "Dansoman",
            "assigned",
        )
        self.in_progress = self._assignment(
            "2 Progress Avenue",
            "Mamprobi",
            "in_progress",
        )
        self.completed = self._assignment(
            "3 Complete Road",
            "Chorkor",
            "completed",
        )
        self.rejected = self._assignment(
            "4 Rejected Road",
            "Glefe",
            "rejected",
        )
        self.cancelled = self._assignment(
            "5 Cancelled Road",
            "Korle Gonno",
            "cancelled",
        )
        self.other_assignment = self._assignment(
            "99 Private Officer Road",
            "Hidden Town",
            "completed",
            officer=self.other_officer,
        )
        self.unassigned_property = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="100 Unassigned Road",
            area_town="Hidden Town",
            property_use="residential",
            building_type="detached",
            is_exempt=True,
        )
        self.client.force_login(self.officer)
        session = self.client.session
        session["active_assembly_id"] = self.assembly.pk
        session.save()
        self.url = reverse("field_operations:field-officer-assignments")

    def _officer(self, username):
        user = User.objects.create_user(
            username=username,
            password="Officer-pass-123",
        )
        profile, _created = UserProfile.objects.get_or_create(user=user)
        profile.role = "field_officer"
        profile.assembly = self.assembly
        profile.must_change_password = False
        profile.save(update_fields=["role", "assembly", "must_change_password"])
        return user

    def _assignment(self, address, town, status, officer=None):
        property_record = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line=address,
            area_town=town,
            property_use="residential",
            building_type="detached",
            verification_status=("verified" if status == "completed" else "pending"),
            is_exempt=True,
        )
        return FieldAssignment.objects.create(
            assembly=self.assembly,
            property=property_record,
            officer=officer or self.officer,
            status=status,
        )

    def _references(self, response):
        return {
            assignment.property.property_reference
            for assignment in response.context["assignments"]
        }

    def test_searches_reference_owner_phone_address_and_town(self):
        searches = (
            (self.assigned.property.property_reference[3:9], self.assigned),
            ("Abena Assignment", self.assigned),
            ("0551234", self.assigned),
            ("Progress Avenue", self.in_progress),
            ("chorkor", self.completed),
        )
        for query, expected in searches:
            with self.subTest(query=query):
                response = self.client.get(self.url, {"q": query})
                self.assertIn(expected.property.property_reference, self._references(response))

    def test_search_cannot_expose_other_officer_or_unassigned_property(self):
        response = self.client.get(self.url, {"q": "Hidden Town"})
        references = self._references(response)
        self.assertNotIn(self.other_assignment.property.property_reference, references)
        self.assertNotIn(self.unassigned_property.property_reference, references)
        self.assertEqual(references, set())

    def test_real_assignment_status_filters(self):
        expected = {
            "assigned": self.assigned,
            "in_progress": self.in_progress,
            "completed": self.completed,
            "rejected": self.rejected,
            "cancelled": self.cancelled,
        }
        for status, assignment in expected.items():
            with self.subTest(status=status):
                response = self.client.get(self.url, {"status": status})
                self.assertEqual(
                    self._references(response),
                    {assignment.property.property_reference},
                )

    def test_search_and_status_filter_work_together(self):
        response = self.client.get(
            self.url,
            {"q": "Complete Road", "status": "completed"},
        )
        self.assertEqual(
            self._references(response),
            {self.completed.property.property_reference},
        )
        no_match = self.client.get(
            self.url,
            {"q": "Complete Road", "status": "in_progress"},
        )
        self.assertEqual(self._references(no_match), set())

    def test_pagination_preserves_search_and_status(self):
        for index in range(11):
            self._assignment(
                f"{index + 20} Bulk Completed Road",
                "Accra",
                "completed",
            )
        response = self.client.get(
            self.url,
            {"q": "Bulk Completed", "status": "completed"},
        )
        self.assertEqual(response.context["paginator"].num_pages, 2)
        self.assertEqual(
            response.context["filter_query"],
            "q=Bulk+Completed&status=completed",
        )
        self.assertContains(
            response,
            "q=Bulk+Completed&amp;status=completed&amp;page=2",
        )


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
        self.assertIsNotNone(self.property.last_verified_at)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "completed")
        self.assertIsNotNone(self.assignment.completed_at)
        visit = FieldVisit.objects.get(
            property=self.property
        )
        self.assertEqual(
            visit.gps_validation_status,
            "matched",
        )
        self.assertTrue(_property_can_accept_payment(self.property))
        assignments_response = self.client.get(
            reverse("field_operations:field-officer-assignments")
        )
        self.assertContains(assignments_response, "Completed")
        self.assertNotContains(assignments_response, "Continue Verification")

    def test_success_redirect_renders_feedback_modal_immediately(self):
        response = self.client.post(
            reverse(
                "field_operations:field-officer-verify-property",
                args=[self.property.pk],
            ),
            {
                "property_id": self.property.pk,
                "property_reference": self.property.property_reference,
                "verification_type": "property_verification",
                "verification_status": "verified",
                "owner_present": "yes",
                "notes": "The property details were checked on site.",
                "latitude": "5.600100",
                "longitude": "-0.180100",
                "gps_accuracy": "8.50",
            },
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse("field_operations:field-officer-stats"),
        )
        self.assertContains(response, 'id="systemNotificationModal"')
        self.assertContains(response, "was verified successfully")
        self.assertContains(response, "var modal = document.getElementById")

    def test_new_assignment_requires_explicit_verification_outcome(self):
        response = self.client.get(
            reverse(
                "field_operations:field-officer-verify-property",
                args=[self.property.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["verification_status"], "")
        self.assertContains(response, 'id="verificationSubmitButton"')
        self.assertContains(
            response,
            'data-submission-overlay="verificationProcessingOverlay"',
        )
        self.assertContains(response, 'id="verificationProcessingOverlay"')
        self.assertContains(response, "Submitting Verification")
        self.assertContains(response, "Submitting verification…")
        self.assertContains(response, "prms_submission.js")

    def test_pending_outcome_is_clearly_incomplete_and_not_payment_eligible(self):
        response = self._post("5.600100", "-0.180100", status="pending")
        self.assertRedirects(response, reverse("field_operations:field-officer-stats"))
        messages = [str(message) for message in response.wsgi_request._messages]
        self.assertTrue(any("remains in progress" in message for message in messages))
        self.property.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(self.property.verification_status, "pending")
        self.assertEqual(self.assignment.status, "in_progress")
        self.assertFalse(_property_can_accept_payment(self.property))

    def test_unassigned_officer_cannot_verify_property(self):
        other_officer = User.objects.create_user(
            username="unassigned-officer",
            password="Officer-pass-456",
        )
        profile, _created = UserProfile.objects.get_or_create(user=other_officer)
        profile.role = "field_officer"
        profile.assembly = self.assembly
        profile.must_change_password = False
        profile.save(update_fields=["role", "assembly", "must_change_password"])
        self.client.force_login(other_officer)
        response = self._post("5.600100", "-0.180100")
        self.assertRedirects(response, reverse("field_operations:field-officer-verify"))
        self.property.refresh_from_db()
        self.assertEqual(self.property.verification_status, "pending")
        self.assertFalse(FieldVisit.objects.filter(property=self.property).exists())

    def test_repeated_submission_does_not_create_duplicate_visit(self):
        first = self._post("5.600100", "-0.180100")
        self.assertEqual(first.status_code, 302)

        second = self._post("5.600100", "-0.180100")
        self.assertRedirects(
            second,
            reverse("field_operations:field-officer-verify"),
        )
        self.assertEqual(
            FieldVisit.objects.filter(property=self.property).count(),
            1,
        )
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "completed")

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
