from unittest.mock import patch

from django.test import TestCase

from admins.models import Assembly
from properties.models import Owner, Property


class PropertyBillingSignalTests(TestCase):
    def setUp(self):
        assembly = Assembly.objects.create(
            name="Billing Signal Assembly",
            short_code="BSA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        owner = Owner.objects.create(
            assembly=assembly,
            full_name="Billing Signal Owner",
            primary_phone="0240000200",
        )
        self.property = Property.objects.create(
            assembly=assembly,
            owner=owner,
            address_line="1 Signal Street",
            area_town="Accra",
            property_use="residential",
            building_type="detached",
            is_exempt=True,
        )

    @patch("billing.signals.generate_bill_for_property")
    def test_verification_only_update_skips_bill_generation_lookup(self, generate):
        self.property.verification_status = "verified"
        self.property.save(
            update_fields=["verification_status", "last_verified_at", "updated_at"]
        )
        generate.assert_not_called()

    @patch("billing.signals.generate_bill_for_property")
    def test_billing_input_update_still_runs_bill_generation(self, generate):
        self.property.rateable_value = 500
        self.property.save(update_fields=["rateable_value", "updated_at"])
        generate.assert_called_once()
