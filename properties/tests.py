import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from admins.models import Assembly
from billing.models import Bill
from payments.models import Payment

from .forms import PropertyCreateForm
from .models import Owner, Property
from .utils import generate_temporary_password


User = get_user_model()


class PropertyBuildingTypeValidationTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Test Assembly",
            short_code="TA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="Test Owner",
            primary_phone="0241234567",
            email="owner@example.com",
        )

    def _form(self, property_use, building_type):
        return PropertyCreateForm(
            data={
                "existing_owner": self.owner.pk,
                "property_use": property_use,
                "building_type": building_type,
                "occupancy_status": "occupied",
                "number_of_floors": 1,
                "number_of_units": 1,
                "address_line": "1 Test Street",
                "area_town": "Accra",
                "rateable_value": "100.00",
                "verification_status": "pending",
                "is_active": "on",
            },
            assembly=self.assembly,
        )

    def test_residential_rejects_warehouse(self):
        form = self._form(
            "residential",
            "warehouse",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("building_type", form.errors)

    def test_institutional_accepts_school(self):
        form = self._form(
            "institutional",
            "school",
        )

        form.is_valid()
        self.assertNotIn("building_type", form.errors)

    def test_property_use_mapping_matches_supported_choices(self):
        all_mapped_types = {
            item
            for items in Property.BUILDING_TYPES_BY_PROPERTY_USE.values()
            for item in items
        }
        available_types = {
            value
            for value, _label in Property.BUILDING_TYPE_CHOICES
        }

        self.assertEqual(all_mapped_types, available_types)

    def test_new_owner_ghana_card_starts_with_prefix(self):
        form = PropertyCreateForm(
            assembly=self.assembly
        )

        self.assertEqual(
            form["owner_ghana_card_number"].value(),
            "GHA-",
        )

    def test_existing_owner_blank_ghana_card_starts_with_prefix(self):
        from .forms import OwnerUpdateForm

        form = OwnerUpdateForm(
            instance=self.owner
        )

        self.assertEqual(
            form["ghana_card_number"].value(),
            "GHA-",
        )

    def test_new_owner_email_is_optional(self):
        form = PropertyCreateForm(
            data={
                "create_new_owner": "on",
                "owner_full_name": "Owner Without Email",
                "owner_primary_phone": "0245551234",
                "owner_email": "",
                "owner_ghana_card_number": "GHA-1234567890-1",
                "property_use": "residential",
                "building_type": "apartment",
                "occupancy_status": "occupied",
                "number_of_floors": 1,
                "number_of_units": 1,
                "address_line": "2 Test Street",
                "area_town": "Accra",
                "rateable_value": "100.00",
                "verification_status": "pending",
                "is_active": "on",
            },
            assembly=self.assembly,
        )

        self.assertFalse(form.fields["owner_email"].required)
        self.assertNotIn(
            "owner_email",
            form.owner_required_field_names,
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_existing_owner_can_remain_without_email(self):
        from .forms import OwnerUpdateForm

        form = OwnerUpdateForm(
            data={
                "full_name": self.owner.full_name,
                "primary_phone": self.owner.primary_phone,
                "alternate_phone": "",
                "email": "",
                "ghana_card_number": "GHA-1234567890-1",
                "postal_address": "",
                "residential_address": "",
            },
            instance=self.owner,
        )

        self.assertFalse(form.fields["email"].required)
        self.assertTrue(form.is_valid(), form.errors.as_json())


class TemporaryPasswordTests(TestCase):
    @patch(
        "properties.utils.secrets.randbelow",
        side_effect=[482731, 735194],
    )
    def test_temporary_password_is_easy_to_type_and_not_shared(
        self,
        _mock_randbelow,
    ):
        first = generate_temporary_password()
        second = generate_temporary_password()

        self.assertRegex(first, re.compile(r"^Prms-\d{6}$"))
        self.assertNotEqual(first, second)


class AdminRecordFilteringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="filter-admin",
            email="admin@example.com",
            password="Admin-pass-123",
        )
        self.assembly = Assembly.objects.create(
            name="Filter Assembly",
            short_code="FA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="Filter Owner",
            primary_phone="0240000000",
        )
        self.verified_property = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="1 Independence Avenue",
            area_town="Accra Central",
            property_use="residential",
            building_type="apartment",
            verification_status="verified",
            is_exempt=True,
        )
        self.pending_property = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="2 Harbour Road",
            area_town="Tema",
            property_use="commercial",
            building_type="shop",
            verification_status="pending",
            is_exempt=True,
        )
        self.bill, _created = Bill.objects.get_or_create(
            assembly=self.assembly,
            property_record=self.verified_property,
            billing_year=timezone.localdate().year,
            defaults={
                "arrears_brought_forward": Decimal("100.00"),
                "amount_paid": Decimal("25.00"),
                "due_date": timezone.localdate() + timedelta(days=30),
            },
        )
        self.bill.arrears_brought_forward = Decimal("100.00")
        self.bill.amount_paid = Decimal("25.00")
        self.bill.due_date = timezone.localdate() + timedelta(days=30)
        self.bill.save()
        Payment.objects.create(
            assembly=self.assembly,
            property=self.verified_property,
            bill=self.bill,
            amount=Decimal("25.00"),
            payment_method="cash",
            transaction_reference="FILTER-PAYMENT-1",
            status="successful",
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["active_assembly_id"] = self.assembly.pk
        session.save()

    def test_property_registry_combines_operational_filters(self):
        response = self.client.get(
            reverse("properties:property-registry"),
            {
                "location": "Accra",
                "type": "residential",
                "verification": "verified",
                "billing": "outstanding",
                "payment": "recorded",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["paginator"].count, 1)
        self.assertEqual(
            response.context["properties"][0]["reference"],
            self.verified_property.property_reference,
        )

    def test_billing_filters_preserve_selected_year_and_payment_state(self):
        response = self.client.get(
            reverse("billing:billing-management"),
            {
                "year": timezone.localdate().year,
                "location": "Accra",
                "type": "residential",
                "status": "outstanding",
                "payment": "recorded",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["paginator"].count, 1)
        self.assertEqual(response.context["bills"][0]["id"], self.bill.pk)
