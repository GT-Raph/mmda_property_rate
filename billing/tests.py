from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.test import TestCase
from django.utils import timezone

from admins.models import Assembly
from billing.admin import BillAdmin
from billing.models import Bill, PropertyClass, RatePolicy
from billing.services import generate_bill_for_property
from payments.models import Payment
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


class IssuedBillSnapshotTests(TestCase):
    """An issued bill is priced from its own snapshot, not the live rate policy."""

    def setUp(self):
        self.year = timezone.localdate().year
        self.assembly = Assembly.objects.create(
            name="Snapshot Assembly",
            short_code="SNP",
            assembly_type="municipal",
            region="Greater Accra",
        )
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            full_name="Snapshot Owner",
            primary_phone="0240000300",
        )
        PropertyClass.objects.create(assembly=self.assembly, name="Class A")

    def make_policy(self, rate="0.00200", minimum="0.00", name="Policy A"):
        return RatePolicy.objects.create(
            assembly=self.assembly,
            policy_name=name,
            year=self.year,
            property_use="residential",
            property_class="Class A",
            building_type="",
            rate_impost=Decimal(rate),
            minimum_charge=Decimal(minimum),
            effective_from=date(self.year, 1, 1),
            effective_to=date(self.year, 12, 31),
            status="active",
        )

    def make_bill(self, rateable_value="50000.00"):
        property_record = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="1 Snapshot Street",
            area_town="Accra",
            property_use="residential",
            property_class="Class A",
            building_type="detached",
            rateable_value=Decimal(rateable_value),
            verification_status="verified",
        )
        return Bill.objects.get(
            property_record=property_record,
            billing_year=self.year,
        )

    def edit_policy(self, policy, **changes):
        for field, value in changes.items():
            setattr(policy, field, Decimal(value))
        policy.save()

    def reload(self, bill):
        return Bill.objects.get(pk=bill.pk)

    def pay(self, bill, amount, reference):
        return Payment.objects.create(
            assembly=self.assembly,
            property=bill.property_record,
            bill=bill,
            payer_name="Snapshot Owner",
            amount=Decimal(amount),
            payment_method="cash",
            transaction_reference=reference,
            status="successful",
        )

    def test_save_after_rate_edit_keeps_issued_price(self):
        policy = self.make_policy()
        bill = self.make_bill()
        self.assertEqual(bill.principal_amount, Decimal("100.00"))

        self.edit_policy(policy, rate_impost="0.00400")
        self.reload(bill).save()

        bill = self.reload(bill)
        self.assertEqual(bill.rate_impost_snapshot, Decimal("0.00200"))
        self.assertEqual(bill.principal_amount, Decimal("100.00"))
        self.assertEqual(bill.amount_due, Decimal("100.00"))

    def test_full_payment_after_rate_edit_marks_bill_paid(self):
        policy = self.make_policy()
        bill = self.make_bill()

        self.edit_policy(policy, rate_impost="0.00400")
        payment = self.pay(bill, "100.00", "SNAPSHOT-FULL-PAYMENT")

        payment.refresh_from_db()
        bill = self.reload(bill)
        self.assertTrue(payment.applied_to_bill)
        self.assertEqual(bill.principal_amount, Decimal("100.00"))
        self.assertEqual(bill.amount_due, Decimal("100.00"))
        self.assertEqual(bill.amount_paid, Decimal("100.00"))
        self.assertEqual(bill.status, "paid")

    def test_raising_minimum_charge_does_not_change_issued_bill(self):
        policy = self.make_policy(minimum="50.00")
        bill = self.make_bill()
        self.assertEqual(bill.principal_amount, Decimal("100.00"))

        self.edit_policy(policy, minimum_charge="300.00")
        self.reload(bill).save()

        self.assertEqual(self.reload(bill).principal_amount, Decimal("100.00"))

    def test_lowering_minimum_charge_does_not_change_issued_bill(self):
        policy = self.make_policy(minimum="150.00")
        bill = self.make_bill()
        self.assertEqual(bill.principal_amount, Decimal("150.00"))

        self.edit_policy(policy, minimum_charge="0.00")
        self.reload(bill).save()

        self.assertEqual(self.reload(bill).principal_amount, Decimal("150.00"))

    def test_zero_rate_policy_does_not_read_live_terms(self):
        policy = self.make_policy(rate="0.00000", minimum="50.00")
        bill = self.make_bill()
        self.assertEqual(bill.principal_amount, Decimal("50.00"))

        self.edit_policy(policy, rate_impost="0.00400", minimum_charge="80.00")
        self.reload(bill).save()

        bill = self.reload(bill)
        self.assertEqual(bill.rate_impost_snapshot, Decimal("0.00000"))
        self.assertEqual(bill.principal_amount, Decimal("50.00"))

    def test_deleted_policy_leaves_issued_price_alone(self):
        policy = self.make_policy()
        bill = self.make_bill()

        policy.delete()
        self.make_policy(rate="0.00400", name="Replacement Policy")
        self.reload(bill).save()

        bill = self.reload(bill)
        self.assertIsNone(bill.rate_policy)
        self.assertEqual(bill.policy_name_snapshot, "Policy A")
        self.assertEqual(bill.principal_amount, Decimal("100.00"))

    def test_bill_from_before_minimum_snapshot_keeps_stored_principal(self):
        policy = self.make_policy()
        bill = self.make_bill()
        # What the migration leaves behind. 150 cannot come from 50,000 x 0.002,
        # so it stands in for a minimum charge nobody recorded.
        Bill.objects.filter(pk=bill.pk).update(
            minimum_charge_snapshot=None,
            principal_amount=Decimal("150.00"),
            amount_due=Decimal("150.00"),
        )

        self.edit_policy(policy, rate_impost="0.00400", minimum_charge="500.00")
        self.reload(bill).save()

        bill = self.reload(bill)
        self.assertIsNone(bill.minimum_charge_snapshot)
        self.assertEqual(bill.principal_amount, Decimal("150.00"))
        self.assertEqual(bill.amount_due, Decimal("150.00"))

        self.pay(bill, "150.00", "SNAPSHOT-OLD-BILL-PAYMENT")
        self.assertEqual(self.reload(bill).status, "paid")

    def test_valuing_a_property_later_does_not_change_issued_bill(self):
        self.make_policy(minimum="50.00")
        bill = self.make_bill(rateable_value="0.00")
        self.assertEqual(bill.principal_amount, Decimal("50.00"))

        property_record = bill.property_record
        property_record.rateable_value = Decimal("50000.00")
        property_record.save()

        self.reload(bill).save()
        bill = self.reload(bill)
        self.assertEqual(bill.rateable_value_snapshot, Decimal("0.00"))
        self.assertEqual(bill.principal_amount, Decimal("50.00"))

        self.pay(bill, "50.00", "SNAPSHOT-ZERO-VALUE-PAYMENT")
        self.assertEqual(self.reload(bill).status, "paid")

    def test_generate_for_property_reprices_from_current_policy_and_value(self):
        policy = self.make_policy()
        bill = self.make_bill()
        property_record = bill.property_record

        policy.policy_name = "Policy A revised"
        self.edit_policy(policy, rate_impost="0.00400", minimum_charge="10.00")
        property_record.rateable_value = Decimal("60000.00")
        property_record.save()

        regenerated = Bill.generate_for_property(
            property_record=property_record,
            billing_year=self.year,
            due_date=date(self.year, 12, 31),
        )

        self.assertEqual(regenerated.pk, bill.pk)
        bill = self.reload(bill)
        self.assertEqual(bill.rateable_value_snapshot, Decimal("60000.00"))
        self.assertEqual(bill.rate_impost_snapshot, Decimal("0.00400"))
        self.assertEqual(bill.minimum_charge_snapshot, Decimal("10.00"))
        self.assertEqual(bill.policy_name_snapshot, "Policy A revised")
        self.assertEqual(bill.principal_amount, Decimal("240.00"))
        self.assertEqual(bill.amount_due, Decimal("240.00"))

        self.edit_policy(policy, rate_impost="0.00800")
        self.reload(bill).save()
        self.assertEqual(self.reload(bill).principal_amount, Decimal("240.00"))

    def test_generate_bill_for_property_leaves_existing_bill_alone(self):
        policy = self.make_policy()
        bill = self.make_bill()

        self.edit_policy(policy, rate_impost="0.00400")
        returned, created, reason = generate_bill_for_property(
            bill.property_record,
            billing_year=self.year,
        )

        self.assertEqual(returned.pk, bill.pk)
        self.assertFalse(created)
        self.assertEqual(reason, "existing_bill")
        bill = self.reload(bill)
        self.assertEqual(bill.rate_impost_snapshot, Decimal("0.00200"))
        self.assertEqual(bill.principal_amount, Decimal("100.00"))

    def test_new_bill_snapshots_policy_as_it_stands_then(self):
        policy = self.make_policy()
        self.make_bill()

        self.edit_policy(policy, rate_impost="0.00400", minimum_charge="20.00")
        new_bill = self.make_bill()

        self.assertEqual(new_bill.rate_impost_snapshot, Decimal("0.00400"))
        self.assertEqual(new_bill.minimum_charge_snapshot, Decimal("20.00"))
        self.assertEqual(new_bill.principal_amount, Decimal("200.00"))

    def test_exemption_zeroes_bill_and_lifting_it_prices_from_current_policy(self):
        policy = self.make_policy()
        bill = self.make_bill()
        property_record = bill.property_record

        property_record.is_exempt = True
        property_record.save()
        self.reload(bill).save()
        bill = self.reload(bill)
        self.assertEqual(bill.principal_amount, Decimal("0.00"))
        self.assertEqual(bill.rate_impost_snapshot, Decimal("0.00000"))

        self.edit_policy(policy, rate_impost="0.00400")
        property_record.is_exempt = False
        property_record.save()
        self.reload(bill).save()
        bill = self.reload(bill)
        self.assertEqual(bill.rate_impost_snapshot, Decimal("0.00400"))
        self.assertEqual(bill.principal_amount, Decimal("200.00"))

    def test_changing_policy_in_admin_reprices_bill(self):
        self.make_policy()
        bill = self.reload(self.make_bill())
        other_policy = self.make_policy(
            rate="0.00300",
            minimum="400.00",
            name="Policy B",
        )

        bill.rate_policy = other_policy
        BillAdmin(Bill, admin.site).save_model(
            request=None,
            obj=bill,
            form=SimpleNamespace(changed_data=["rate_policy"]),
            change=True,
        )

        bill = self.reload(bill)
        self.assertEqual(bill.policy_name_snapshot, "Policy B")
        self.assertEqual(bill.rate_impost_snapshot, Decimal("0.00300"))
        self.assertEqual(bill.minimum_charge_snapshot, Decimal("400.00"))
        self.assertEqual(bill.principal_amount, Decimal("400.00"))
