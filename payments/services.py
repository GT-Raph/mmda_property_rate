from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Payment


def apply_payment_to_bill(payment: Payment) -> bool:
    if not payment.pk:
        return False

    with transaction.atomic():
        locked_payment = (
            Payment.objects.select_for_update()
            .select_related("bill")
            .get(pk=payment.pk)
        )

        if locked_payment.status != "successful":
            return False

        if not locked_payment.bill_id:
            return False

        if locked_payment.applied_to_bill:
            return False

        bill = locked_payment.bill.__class__.objects.select_for_update().get(
            pk=locked_payment.bill_id
        )

        bill.amount_paid = (bill.amount_paid or Decimal("0.00")) + locked_payment.amount
        bill.last_payment_at = locked_payment.paid_at or timezone.now()
        bill.save()

        Payment.objects.filter(pk=locked_payment.pk).update(
            property=bill.property_record,
            assembly=bill.assembly,
            reconciliation_status="matched",
            reconciled_at=timezone.now(),
            applied_to_bill=True,
        )

    return True