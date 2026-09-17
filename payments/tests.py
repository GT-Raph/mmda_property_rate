from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from admins.models import Assembly
from billing.models import Bill
from properties.models import Owner, Property

from .models import Payment


class PaymentApplicationTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Payment Test Assembly",
            short_code="PTA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="Payment Test Owner",
            primary_phone="0240000100",
        )
        self.property = Property.objects.create(
            assembly=self.assembly,
            owner=owner,
            address_line="1 Payment Street",
            area_town="Accra",
            property_use="residential",
            building_type="detached",
            verification_status="verified",
            is_exempt=True,
        )
        self.bill = Bill.objects.get(
            property_record=self.property,
            billing_year=timezone.localdate().year,
        )
        self.bill.arrears_brought_forward = Decimal("200.00")
        self.bill.due_date = timezone.localdate() + timedelta(days=30)
        self.bill.save()

    def test_successful_payment_is_locked_and_applied_with_nullable_bill_fk(self):
        payment = Payment.objects.create(
            assembly=self.assembly,
            property=self.property,
            bill=self.bill,
            payer_name="Payment Test Owner",
            amount=Decimal("75.00"),
            payment_method="cash",
            transaction_reference="PAYMENT-LOCK-REGRESSION-1",
            status="successful",
        )

        payment.refresh_from_db()
        self.bill.refresh_from_db()

        self.assertTrue(payment.applied_to_bill)
        self.assertEqual(payment.reconciliation_status, "matched")
        self.assertEqual(self.bill.amount_paid, Decimal("75.00"))
        self.assertEqual(self.bill.status, "part_paid")
