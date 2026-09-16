from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Payment


def apply_payment_to_bill(
    payment: Payment,
) -> bool:
    """
    Apply a successful payment to a bill.

    Security rule:
    An unverified property must never have a
    citizen payment applied to its bill.
    """

    if not payment.pk:
        return False

    with transaction.atomic():
        locked_payment = (
            Payment.objects
            .select_for_update()
            .get(
                pk=payment.pk
            )
        )

        # Do not select_related("bill") here. Payment.bill is nullable, so
        # PostgreSQL would build a LEFT OUTER JOIN and reject FOR UPDATE on
        # the nullable side. The bill is fetched and locked explicitly below.

        if (
            locked_payment.status
            != "successful"
        ):
            return False

        if not locked_payment.bill_id:
            return False

        if (
            locked_payment
            .applied_to_bill
        ):
            return False

        bill = (
            locked_payment.bill
            .__class__
            .objects
            .select_for_update()
            .select_related(
                "property_record"
            )
            .get(
                pk=(
                    locked_payment
                    .bill_id
                )
            )
        )

        property_obj = (
            bill.property_record
        )

        verification_status = (
            getattr(
                property_obj,
                "verification_status",
                "",
            )
            or ""
        ).lower()

        is_active = getattr(
            property_obj,
            "is_active",
            True,
        )

        if (
            verification_status
            != "verified"
            or not is_active
        ):
            Payment.objects.filter(
                pk=locked_payment.pk
            ).update(
                reconciliation_status=(
                    "manual_review"
                ),
                applied_to_bill=False,
            )

            return False

        amount = (
            locked_payment.amount
            or Decimal("0.00")
        )

        bill.amount_paid = (
            bill.amount_paid
            or Decimal("0.00")
        ) + amount

        bill.last_payment_at = (
            locked_payment.paid_at
            or timezone.now()
        )

        bill.refresh_status()

        bill.save(
            update_fields=[
                "amount_paid",
                "last_payment_at",
                "status",
                "updated_at",
            ]
        )

        Payment.objects.filter(
            pk=locked_payment.pk
        ).update(
            property=(
                bill.property_record
            ),
            assembly=(
                bill.assembly
            ),
            reconciliation_status=(
                "matched"
            ),
            reconciled_at=(
                timezone.now()
            ),
            applied_to_bill=True,
        )

    return True
