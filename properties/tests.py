import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from admins.models import Assembly

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
