import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from admins.models import Assembly, UserProfile
from billing.models import Bill
from payments.models import Payment
from properties.models import Owner, Property


User = get_user_model()


@override_settings(
    EMAIL_BACKEND=(
        "django.core.mail.backends.locmem.EmailBackend"
    ),
    SECURE_SSL_REDIRECT=False,
)
class CitizenPasswordResetTests(TestCase):
    def _create_user(self, username, email, role):
        user = User.objects.create_user(
            username=username,
            email=email,
            password="Current-pass-123",
        )
        profile, _created = (
            UserProfile.objects.get_or_create(
                user=user
            )
        )
        profile.role = role
        profile.save(update_fields=["role"])
        return user

    def test_citizen_can_request_reset_email(self):
        self._create_user(
            "citizen",
            "citizen@example.com",
            "citizen",
        )

        response = self.client.post(
            reverse(
                "citizens:password-reset"
            ),
            {"email": "citizen@example.com"},
        )

        self.assertRedirects(
            response,
            reverse(
                "citizens:password-reset-done"
            ),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "/owner/password-reset/",
            mail.outbox[0].body,
        )

    def test_owner_reset_does_not_email_staff_account(self):
        self._create_user(
            "staff",
            "staff@example.com",
            "property_officer",
        )

        response = self.client.post(
            reverse(
                "citizens:password-reset"
            ),
            {"email": "staff@example.com"},
        )

        self.assertRedirects(
            response,
            reverse(
                "citizens:password-reset-done"
            ),
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_updates_password_and_clears_temporary_flag(self):
        user = self._create_user(
            "citizen-reset",
            "reset@example.com",
            "citizen",
        )
        user.profile.must_change_password = True
        user.profile.save(
            update_fields=["must_change_password"]
        )

        self.client.post(
            reverse(
                "citizens:password-reset"
            ),
            {"email": "reset@example.com"},
        )
        reset_path = re.search(
            r"http://testserver([^\s]+)",
            mail.outbox[0].body,
        ).group(1)

        token_response = self.client.get(reset_path)
        self.assertEqual(
            token_response.status_code,
            302,
        )
        response = self.client.post(
            token_response.url,
            {
                "new_password1": "New-owner-pass-4827",
                "new_password2": "New-owner-pass-4827",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "citizens:password-reset-complete"
            ),
        )
        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertTrue(
            user.check_password(
                "New-owner-pass-4827"
            )
        )
        self.assertFalse(
            user.profile.must_change_password
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class CitizenDashboardSummaryTests(TestCase):
    def test_dashboard_shows_payment_count_and_paid_amount(self):
        assembly = Assembly.objects.create(
            name="Citizen Summary Assembly",
            short_code="CS",
            assembly_type="municipal",
            region="Greater Accra",
        )
        user = User.objects.create_user(
            username="summary-citizen",
            password="Citizen-pass-123",
        )
        profile, _created = UserProfile.objects.get_or_create(user=user)
        profile.role = "citizen"
        profile.assembly = assembly
        profile.must_change_password = False
        profile.save(update_fields=["role", "assembly", "must_change_password"])
        owner = Owner.objects.create(
            assembly=assembly,
            linked_user=user,
            full_name="Summary Citizen",
            primary_phone="0241111111",
        )
        property_record = Property.objects.create(
            assembly=assembly,
            owner=owner,
            address_line="1 Summary Street",
            area_town="Accra",
            property_use="residential",
            building_type="apartment",
            is_exempt=True,
        )
        Payment.objects.create(
            assembly=assembly,
            property=property_record,
            amount=Decimal("75.00"),
            payment_method="cash",
            transaction_reference="CITIZEN-SUMMARY-PAYMENT",
            status="successful",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("citizens:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["payments_count"], 1)
        self.assertContains(response, "Payments")
        self.assertContains(response, "paid in")


@override_settings(SECURE_SSL_REDIRECT=False)
class CitizenVerifiedPaymentWorkflowTests(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(
            name="Citizen Payment Assembly",
            short_code="CPA",
            assembly_type="municipal",
            region="Greater Accra",
        )
        self.user = User.objects.create_user(
            username="payment-citizen",
            password="Citizen-pass-123",
        )
        profile, _created = UserProfile.objects.get_or_create(user=self.user)
        profile.role = "citizen"
        profile.assembly = self.assembly
        profile.must_change_password = False
        profile.save(update_fields=["role", "assembly", "must_change_password"])
        self.owner = Owner.objects.create(
            assembly=self.assembly,
            linked_user=self.user,
            full_name="Citizen Payment Owner",
            primary_phone="0242222222",
        )
        self.pending_property = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="1 Pending Street",
            area_town="Accra",
            property_use="residential",
            building_type="detached",
            verification_status="pending",
            is_exempt=True,
        )
        self.verified_property = Property.objects.create(
            assembly=self.assembly,
            owner=self.owner,
            address_line="2 Verified Street",
            area_town="Accra",
            property_use="residential",
            building_type="detached",
            verification_status="verified",
            is_exempt=True,
        )
        self.pending_bill = Bill.objects.get(
            property_record=self.pending_property,
            billing_year=timezone.localdate().year,
        )
        self.verified_bill = Bill.objects.get(
            property_record=self.verified_property,
            billing_year=timezone.localdate().year,
        )
        for bill in (self.pending_bill, self.verified_bill):
            bill.arrears_brought_forward = Decimal("100.00")
            bill.save()
        self.client.force_login(self.user)

    def test_pending_property_cannot_enter_payment_confirmation(self):
        response = self.client.get(
            reverse("citizens:payment-confirm"),
            {"bill": self.pending_bill.pk},
        )
        self.assertRedirects(response, reverse("citizens:bills"))
        self.assertFalse(Payment.objects.filter(bill=self.pending_bill).exists())

    def test_verified_property_completes_mobile_money_payment(self):
        response = self.client.post(
            reverse("citizens:payment-confirm"),
            {
                "bill_ids": [str(self.verified_bill.pk)],
                "network": "mtn",
                "mobile_number": "0242222222",
            },
        )
        self.assertRedirects(response, reverse("citizens:payment-processing"))

        response = self.client.get(reverse("citizens:payment-success"))
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(bill=self.verified_bill)
        self.assertEqual(payment.payment_method, "momo")
        self.assertEqual(payment.status, "successful")
        self.verified_bill.refresh_from_db()
        self.assertEqual(self.verified_bill.status, "paid")
        self.assertEqual(self.verified_bill.amount_paid, Decimal("100.00"))
        history = self.client.get(reverse("citizens:payment-history"))
        self.assertContains(history, payment.transaction_reference)
