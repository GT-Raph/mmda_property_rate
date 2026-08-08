import io
import uuid
from decimal import Decimal

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, request
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from admins.access import get_user_role
from admins.models import Assembly
from billing.models import Bill
from payments.models import Payment
from properties.models import Property
from properties.utils import normalize_phone, normalize_text

from .forms import (
    CitizenAddressForm,
    CitizenDisputeForm,
    CitizenEmailForm,
    CitizenNameForm,
    CitizenNotificationForm,
    CitizenPasswordForm,
    CitizenPaymentForm,
    CitizenPhoneForm,
)
from .models import (
    CitizenDispute,
    CitizenDisputeAttachment,
    CitizenPreference,
    PropertyCertificate,
)


def _account_number_for_property(prop):
    reference = getattr(prop, "property_reference", "") or ""
    if reference.startswith("PROP-"):
        return reference.replace("PROP-", "ACC-", 1)
    return reference or "—"


def _safe_decimal(value):
    try:
        return Decimal(value or 0)
    except Exception:
        return Decimal("0.00")


def _bill_balance(bill):
    amount_due = _safe_decimal(getattr(bill, "amount_due", 0))
    amount_paid = _safe_decimal(getattr(bill, "amount_paid", 0))
    balance = amount_due - amount_paid
    return balance if balance > 0 else Decimal("0.00")


def _property_can_accept_payment(
    property_obj,
):
    """
    A property can only accept citizen payments
    after MMDA verification.
    """

    if not property_obj:
        return False

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

    return (
        is_active
        and verification_status
        == "verified"
    )


def _field_value(obj, field_names, default=Decimal("0.00")):
    for field_name in field_names:
        if hasattr(obj, field_name):
            value = getattr(obj, field_name)
            if value not in [None, ""]:
                return value
    return default


def _rate_impost_value(bill):
    direct_value = _field_value(
        bill,
        ["rate_impost", "rate", "rate_value"],
        default=None,
    )
    if direct_value not in [None, ""]:
        return direct_value

    rate_policy = getattr(bill, "rate_policy", None)
    if rate_policy:
        policy_value = _field_value(
            rate_policy,
            ["rate_impost", "rate", "rate_value"],
            default=None,
        )
        if policy_value not in [None, ""]:
            return policy_value

    return Decimal("0.00000")


def _arrears_value(bill):
    return _safe_decimal(_field_value(bill, ["arrears", "arrears_amount"], default=0))


def _penalty_value(bill):
    return _safe_decimal(_field_value(bill, ["penalty", "penalty_amount"], default=0))


def _current_fee_value(bill):
    direct = _field_value(bill, ["current_fee"], default=None)
    if direct not in [None, ""]:
        return _safe_decimal(direct)

    amount_due = _safe_decimal(getattr(bill, "amount_due", 0))
    arrears = _arrears_value(bill)
    penalty = _penalty_value(bill)

    computed = amount_due - arrears - penalty
    return computed if computed > 0 else amount_due


def _create_payment_record(bill, amount, network, mobile_number, transaction_reference):
    payment = Payment()

    payment.bill = bill
    payment.property = getattr(bill, "property_record", None)
    payment.assembly = getattr(bill, "assembly", None)

    payment.amount = amount
    payment.status = "successful"
    payment.payment_method = "momo"
    payment.provider = (network or "").strip().lower()
    payment.payer_phone = mobile_number or ""
    payment.payer_name = _owner_name(getattr(bill.property_record, "owner", None))
    payment.property_reference_entered = getattr(bill.property_record, "property_reference", "") or ""
    payment.transaction_reference = transaction_reference
    payment.external_reference = transaction_reference
    payment.reconciliation_status = "matched"
    payment.applied_to_bill = True
    payment.paid_at = timezone.now()

    payment.save()
    return payment


def _mark_bill_paid(bill, payment_amount):
    payment_amount = _safe_decimal(payment_amount)
    current_paid = _safe_decimal(getattr(bill, "amount_paid", 0))
    amount_due = _safe_decimal(getattr(bill, "amount_due", 0))

    new_amount_paid = current_paid + payment_amount
    if new_amount_paid > amount_due:
        new_amount_paid = amount_due

    bill.amount_paid = new_amount_paid
    bill.last_payment_at = timezone.now()

    if hasattr(bill, "refresh_status"):
        bill.refresh_status()
        bill.save(update_fields=["amount_paid", "last_payment_at", "status"])
    else:
        if new_amount_paid >= amount_due:
            bill.status = "paid"
        elif new_amount_paid > 0:
            bill.status = "part_paid"
        else:
            bill.status = "pending"
        bill.save(update_fields=["amount_paid", "last_payment_at", "status"])

    return payment_amount


def _get_owner_model():
    return Property._meta.get_field("owner").remote_field.model


def _accessible_assemblies_for_user(user):
    if not user or not user.is_authenticated:
        return Assembly.objects.none()

    profile = getattr(user, "profile", None)

    if profile and hasattr(profile, "accessible_assemblies"):
        return profile.accessible_assemblies()

    if profile and getattr(profile, "role", "") != "citizen":
        if profile.assembly_id:
            return Assembly.objects.filter(
                pk=profile.assembly_id,
                is_active=True,
            )
        return Assembly.objects.none()

    owner_model = _get_owner_model()
    owner_assembly_ids = owner_model.objects.filter(
        linked_user=user,
        assembly__is_active=True,
    ).values_list("assembly_id", flat=True)

    allowed_ids = set(owner_assembly_ids)

    if profile:
        if profile.assembly_id:
            allowed_ids.add(profile.assembly_id)

        allowed_manager = getattr(profile, "allowed_assemblies", None)
        if allowed_manager is not None:
            allowed_ids.update(
                allowed_manager.filter(is_active=True).values_list(
                    "id",
                    flat=True,
                )
            )

    return Assembly.objects.filter(
        id__in=allowed_ids,
        is_active=True,
    ).order_by("name")


def _get_current_assembly(request):
    profile = getattr(request.user, "profile", None)
    role = getattr(profile, "role", "") if profile else ""
    assembly_id = request.session.get("active_assembly_id")

    if role == "citizen":
        accessible = _accessible_assemblies_for_user(request.user)

        if assembly_id:
            selected = accessible.filter(pk=assembly_id).first()
            if selected:
                return selected

            request.session.pop("active_assembly_id", None)

        if profile and profile.assembly_id:
            default_assembly = accessible.filter(
                pk=profile.assembly_id
            ).first()
            if default_assembly:
                request.session["active_assembly_id"] = default_assembly.id
                return default_assembly

        first_assembly = accessible.first()
        if first_assembly:
            request.session["active_assembly_id"] = first_assembly.id
            return first_assembly

        return None

    if assembly_id:
        try:
            return Assembly.objects.get(
                id=assembly_id,
                is_active=True,
            )
        except Assembly.DoesNotExist:
            request.session.pop("active_assembly_id", None)

    if profile and profile.assembly_id:
        try:
            return Assembly.objects.get(
                id=profile.assembly_id,
                is_active=True,
            )
        except Assembly.DoesNotExist:
            return None

    return None


def _owner_name(owner):
    if not owner:
        return "Property Owner"

    return (
        getattr(owner, "full_name", None)
        or getattr(owner, "name", None)
        or getattr(owner, "owner_name", None)
        or "Property Owner"
    )


def _grant_owner_assembly_access(user, owner):
    profile = getattr(user, "profile", None)
    if not profile or not owner or not owner.assembly_id:
        return

    update_fields = []

    if getattr(profile, "role", "") != "citizen":
        profile.role = "citizen"
        update_fields.append("role")

    if not profile.assembly_id:
        profile.assembly = owner.assembly
        update_fields.append("assembly")

    if update_fields:
        profile.save(update_fields=update_fields)

    allowed_manager = getattr(profile, "allowed_assemblies", None)
    if allowed_manager is not None:
        allowed_manager.add(owner.assembly)


def _find_owner_for_user(user, assembly=None):
    if not user or not user.is_authenticated:
        return None

    owner_model = _get_owner_model()
    owner_field_names = {
        field.name
        for field in owner_model._meta.get_fields()
    }

    linked_qs = owner_model.objects.filter(linked_user=user)
    if assembly is not None and "assembly" in owner_field_names:
        linked_qs = linked_qs.filter(assembly=assembly)

    owner = linked_qs.order_by("id").first()
    if owner:
        _grant_owner_assembly_access(user, owner)
        return owner

    fallback_qs = owner_model.objects.all()
    if assembly is not None and "assembly" in owner_field_names:
        fallback_qs = fallback_qs.filter(assembly=assembly)

    user_email = (user.email or "").strip().lower()
    if user_email and "email" in owner_field_names:
        owner = fallback_qs.filter(email__iexact=user_email).first()
        if owner:
            owner.linked_user = user
            owner.save(update_fields=["linked_user"])
            _grant_owner_assembly_access(user, owner)
            return owner

    profile = getattr(user, "profile", None)
    profile_phone = normalize_phone(
        getattr(profile, "phone_number", "") if profile else ""
    )

    if profile_phone:
        for phone_field in ["primary_phone", "alternate_phone"]:
            if phone_field not in owner_field_names:
                continue

            for candidate in fallback_qs.exclude(**{phone_field: ""}):
                if normalize_phone(getattr(candidate, phone_field, "")) == profile_phone:
                    candidate.linked_user = user
                    candidate.save(update_fields=["linked_user"])
                    _grant_owner_assembly_access(user, candidate)
                    return candidate

    full_name = normalize_text(user.get_full_name())
    if full_name and "full_name" in owner_field_names:
        owners_qs = fallback_qs.filter(
            full_name__iexact=user.get_full_name().strip()
        )

        if owners_qs.count() == 1:
            owner = owners_qs.first()
            owner.linked_user = user
            owner.save(update_fields=["linked_user"])
            _grant_owner_assembly_access(user, owner)
            return owner

    return None


def _owner_q(owner, prefix):
    if owner and getattr(owner, "linked_user_id", None):
        return Q(**{f"{prefix}__linked_user_id": owner.linked_user_id})
    return Q(**{prefix: owner})


def _owner_properties_queryset(owner, assembly=None):
    if not owner:
        return Property.objects.none()

    qs = Property.objects.filter(
        _owner_q(owner, "owner")
    ).order_by("-created_at")

    if assembly:
        qs = qs.filter(assembly=assembly)

    return qs

def _property_type_label(prop):
    if hasattr(prop, "get_property_use_display"):
        return prop.get_property_use_display()

    raw = (getattr(prop, "property_use", "") or "").replace("_", " ").title()
    return raw or "Property"


def _property_heading(prop):
    label = _property_type_label(prop)
    if label.lower().endswith("property"):
        return label
    return f"{label} Property"


def _property_location(prop):
    address_line = getattr(prop, "address_line", "") or ""
    suburb = getattr(prop, "suburb", "") or ""
    area_town = getattr(prop, "area_town", "") or ""

    parts = [part for part in [address_line, suburb, area_town] if part]
    return ", ".join(parts) if parts else "Location not available"


def _property_status(prop):
    verification_status = (getattr(prop, "verification_status", "") or "").lower()
    is_active = getattr(prop, "is_active", True)

    if not is_active:
        return "Inactive"

    if verification_status in ["pending", "under_review", "unverified"]:
        return "Pending"

    return "Active"


def _property_secondary_metric(prop):
    type_label = _property_type_label(prop).lower()

    bedroom_fields = [
        "bedrooms",
        "bedroom_count",
        "number_of_bedrooms",
        "no_of_bedrooms",
        "number_of_rooms",
        "rooms",
    ]

    size_fields = [
        "size_sqm",
        "square_meters",
        "sqm",
        "floor_area",
        "property_size",
        "size",
    ]

    if "residential" in type_label:
        for field_name in bedroom_fields:
            value = getattr(prop, field_name, None)
            if value not in [None, ""]:
                return "Bedrooms", f"{value} beds"
        return "Bedrooms", "—"

    if "commercial" in type_label:
        for field_name in size_fields:
            value = getattr(prop, field_name, None)
            if value not in [None, ""]:
                return "Size", f"{value} sqm"
        return "Size", "—"

    for field_name in size_fields:
        value = getattr(prop, field_name, None)
        if value not in [None, ""]:
            return "Size", f"{value} sqm"

    return "Type", _property_type_label(prop)


def _digital_address(prop):
    return getattr(prop, "digital_address", "") or "Not added"


def _money(value):
    value = Decimal(value or 0)
    if value >= 1000:
        return f"GH₵ {value / Decimal('1000'):.1f}k"
    return f"GH₵ {value:,.0f}"


def _money_full(value):
    return f"GH₵ {Decimal(value or 0):,.0f}"


def _latest_property_bill(property_obj):
    return (
        Bill.objects.filter(property_record=property_obj)
        .order_by("-billing_year", "-created_at")
        .first()
    )


def _annual_rate_for_property(property_obj):
    latest_bill = _latest_property_bill(property_obj)
    return latest_bill.amount_due if latest_bill else Decimal("0.00")


def _citizen_owner_or_none(request):
    if get_user_role(request.user) != "citizen":
        return None

    context_assembly = _get_current_assembly(request)
    return _find_owner_for_user(
        request.user,
        assembly=context_assembly,
    )


def _safe_reverse(name, fallback="#", *args, **kwargs):
    try:
        return reverse(name, args=args, kwargs=kwargs)
    except NoReverseMatch:
        return fallback


def _certificate_property_field_name():
    field_names = {field.name for field in PropertyCertificate._meta.get_fields()}
    if "property_record" in field_names:
        return "property_record"
    return "property"


def _certificate_property_obj(certificate):
    return getattr(certificate, _certificate_property_field_name())


def _certificate_queryset():
    field_name = _certificate_property_field_name()
    return PropertyCertificate.objects.select_related(field_name)


def _ensure_certificate_for_property(property_obj):
    field_name = _certificate_property_field_name()
    certificate, _ = PropertyCertificate.objects.get_or_create(**{field_name: property_obj})
    return certificate


def _certificate_verify_absolute_url(request, certificate):
    relative_url = reverse("citizens:certificate-verify", args=[certificate.certificate_uuid])

    site_public_url = getattr(settings, "SITE_PUBLIC_URL", "").strip()
    if site_public_url:
        return f"{site_public_url.rstrip('/')}{relative_url}"

    return request.build_absolute_uri(relative_url)


def _certificate_qr_url(certificate):
    return reverse(
        "citizens:certificate-qr",
        args=[certificate.certificate_uuid],
    )


def _certificate_number(certificate):
    prop = _certificate_property_obj(certificate)
    year = getattr(prop, "created_at", None)
    year_value = year.year if year else 2026
    return f"{prop.property_reference}-CERT-{year_value}"


def _property_registered_date(prop):
    created = getattr(prop, "created_at", None)
    if created:
        return created.strftime("%Y-%m-%d")
    return "—"


@login_required
def citizen_dashboard(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    context_assembly = _get_current_assembly(request)
    owner = _find_owner_for_user(
        request.user,
        assembly=context_assembly,
    )

    owner_name = _owner_name(owner) if owner else (request.user.get_full_name() or request.user.username)
    owner_short_name = request.user.first_name or owner_name.split()[0]

    if not owner:
        context = {
            "page_title": "Owner Dashboard",
            "owner_name": owner_name,
            "owner_short_name": owner_short_name,
            "owner_role": "Property Owner",
            "current_year": timezone.localdate().year,
            "stats": {
                "properties_count": 0,
                "outstanding_total": "GH₵ 0",
                "paid_total": "GH₵ 0",
                "bills_count": 0,
            },
            "quick_links": {
                "pay_bills": _safe_reverse("citizens:bills"),
                "certificates": _safe_reverse("citizens:certificates"),
                "dispute": _safe_reverse("citizens:submit-dispute"),
                "receipts": _safe_reverse("citizens:payment-history"),
            },
            "section_links": {
                "dashboard": _safe_reverse("citizens:dashboard"),
                "properties": _safe_reverse("citizens:properties"),
                "bills": _safe_reverse("citizens:bills"),
                "payments": _safe_reverse("citizens:payment-history"),
                "profile": _safe_reverse("citizens:profile"),
                "certificates": _safe_reverse("citizens:certificates"),
            },
            "properties": [],
            "bills": [],
            "payments": [],
            "display_email": request.user.email or "No email added",
        }
        return render(request, "citizens/dashboard.html", context)

    properties_qs = _owner_properties_queryset(owner, context_assembly)

    bills_qs = Bill.objects.filter(_owner_q(owner, "property_record__owner")).select_related(
        "property_record",
        "rate_policy",
    ).order_by("-billing_year", "-created_at")

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    payments_qs = Payment.objects.filter(
        _owner_q(owner, "property__owner") | _owner_q(owner, "bill__property_record__owner"),
        status="successful",
    ).select_related("property", "bill").order_by("-paid_at", "-created_at")

    if context_assembly:
        payments_qs = payments_qs.filter(assembly=context_assembly)

    current_year = timezone.localdate().year

    outstanding_total = Decimal("0.00")
    for bill in bills_qs.exclude(status__in=["paid", "cancelled"]):
        outstanding_total += _bill_balance(bill)

    paid_total = Decimal("0.00")
    for payment in payments_qs:
        payment_date = getattr(payment, "paid_at", None) or getattr(payment, "created_at", None)
        if payment_date and payment_date.year == current_year:
            paid_total += Decimal(getattr(payment, "amount", 0) or 0)

    properties_data = []
    for prop in properties_qs[:2]:
        latest_bill = _latest_property_bill(prop)
        type_label = _property_type_label(prop)

        if "commercial" in type_label.lower():
            type_class = "type-commercial"
        elif "mixed" in type_label.lower():
            type_class = "type-mixed"
        else:
            type_class = "type-residential"

        properties_data.append(
            {
                "id": prop.id,
                "reference": prop.property_reference,
                "location": _property_location(prop),
                "type_label": type_label,
                "type_class": type_class,
                "annual_rate": _money_full(latest_bill.amount_due if latest_bill else 0),
                "details_url": _safe_reverse("citizens:properties"),
            }
        )

    bills_data = []
    for bill in bills_qs[:2]:
        status = (bill.status or "").lower()
        is_paid = status == "paid"

        bills_data.append(
            {
                "id": bill.id,
                "bill_number": bill.bill_number,
                "property_reference": bill.property_record.property_reference,
                "amount_due": _money_full(bill.amount_due),
                "due_date": bill.due_date.strftime("%Y-%m-%d") if bill.due_date else "—",
                "status_label": "Paid" if is_paid else "Unpaid",
                "status_class": "status-paid" if is_paid else "status-unpaid",
                "card_class": "paid" if is_paid else "unpaid",
                "pay_url": _safe_reverse("citizens:payment-confirm") + f"?bill={bill.id}" if not is_paid else "",
                "view_url": _safe_reverse("citizens:bill-detail", kwargs={"bill_id": bill.id}),
            }
        )

    payments_data = []
    for payment in payments_qs[:2]:
        prop = getattr(payment, "property", None)
        bill = getattr(payment, "bill", None)

        if not prop and bill:
            prop = getattr(bill, "property_record", None)

        property_reference = prop.property_reference if prop else "Payment"
        payment_date = getattr(payment, "paid_at", None) or getattr(payment, "created_at", None)

        payments_data.append(
            {
                "property_reference": property_reference,
                "date_label": payment_date.strftime("%Y-%m-%d") if payment_date else "—",
                "method": (getattr(payment, "payment_method", "") or "Payment").replace("_", " ").title(),
                "amount": _money_full(getattr(payment, "amount", 0)),
                "receipt_url": _safe_reverse("citizens:payment-history"),
            }
        )

    context = {
        "page_title": "Owner Dashboard",
        "owner_name": owner_name,
        "owner_short_name": owner_short_name,
        "owner_role": "Property Owner",
        "current_year": current_year,
        "display_email": _display_owner_email(owner, request.user) or (request.user.email or "No email added"),
        "stats": {
            "properties_count": properties_qs.count(),
            "outstanding_total": _money(outstanding_total),
            "paid_total": _money(paid_total),
            "bills_count": bills_qs.count(),
        },
        "quick_links": {
            "pay_bills": _safe_reverse("citizens:bills"),
            "certificates": _safe_reverse("citizens:certificates"),
            "dispute": _safe_reverse("citizens:submit-dispute"),
            "receipts": _safe_reverse("citizens:payment-history"),
        },
        "section_links": {
            "dashboard": _safe_reverse("citizens:dashboard"),
            "properties": _safe_reverse("citizens:properties"),
            "bills": _safe_reverse("citizens:bills"),
            "payments": _safe_reverse("citizens:payment-history"),
            "profile": _safe_reverse("citizens:profile"),
            "certificates": _safe_reverse("citizens:certificates"),
        },
        "properties": properties_data,
        "bills": bills_data,
        "payments": payments_data,
    }
    return render(request, "citizens/dashboard.html", context)


@login_required
def citizen_properties(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    context_assembly = _get_current_assembly(request)
    owner = _citizen_owner_or_none(request)

    owner_name = _owner_name(owner) if owner else (request.user.get_full_name() or request.user.username)
    owner_short_name = request.user.first_name or owner_name.split()[0]

    property_cards = []
    properties_count = 0

    if owner:
        properties_qs = _owner_properties_queryset(owner, context_assembly)
        properties_count = properties_qs.count()

        for prop in properties_qs:
            metric_label, metric_value = _property_secondary_metric(prop)
            annual_rate = _annual_rate_for_property(prop)

            property_cards.append(
                {
                    "id": prop.id,
                    "reference": prop.property_reference,
                    "heading": _property_heading(prop),
                    "location": _property_location(prop),
                    "status": _property_status(prop),
                    "digital_address": _digital_address(prop),
                    "rateable_value": _money_full(getattr(prop, "rateable_value", 0)),
                    "annual_rate": _money_full(annual_rate),
                    "metric_label": metric_label,
                    "metric_value": metric_value,
                }
            )

    assembly_phone = getattr(context_assembly, "contact_phone", "") if context_assembly else ""
    if not assembly_phone:
        assembly_phone = "+233000000000"

    context = {
        "page_title": "My Properties",
        "owner_name": owner_name,
        "owner_short_name": owner_short_name,
        "owner_role": "Property Owner",
        "context_assembly": context_assembly,
        "properties_count": properties_count,
        "properties": property_cards,
        "assembly_phone": assembly_phone,
        "has_owner_profile": bool(owner),
    }
    return render(request, "citizens/properties.html", context)


@login_required
def citizen_property_bills(request, property_id):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        raise Http404("No owner record is linked to this user.")

    context_assembly = _get_current_assembly(request)

    property_qs = Property.objects.filter(_owner_q(owner, "owner"))
    if context_assembly:
        property_qs = property_qs.filter(assembly=context_assembly)

    property_obj = get_object_or_404(property_qs, id=property_id)

    bills_qs = Bill.objects.filter(property_record=property_obj).order_by("-billing_year", "-created_at")
    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    bills = []
    for bill in bills_qs:
        balance = Decimal(bill.amount_due or 0) - Decimal(bill.amount_paid or 0)
        status = (bill.status or "").lower()

        if status == "paid":
            status_label = "Paid"
            status_class = "status-paid"
        elif status in ["partial", "part_paid"]:
            status_label = "Partial"
            status_class = "status-partial"
        else:
            status_label = "Unpaid"
            status_class = "status-unpaid"

        bills.append(
            {
                "bill_number": bill.bill_number,
                "year": bill.billing_year,
                "amount_due": _money_full(bill.amount_due),
                "amount_paid": _money_full(bill.amount_paid),
                "balance": _money_full(balance),
                "due_date": bill.due_date.strftime("%Y-%m-%d") if bill.due_date else "—",
                "status_label": status_label,
                "status_class": status_class,
            }
        )

    context = {
        "page_title": "Property Bills",
        "owner_name": _owner_name(owner),
        "owner_short_name": request.user.first_name or _owner_name(owner).split()[0],
        "owner_role": "Property Owner",
        "property": {
            "id": property_obj.id,
            "reference": property_obj.property_reference,
            "heading": _property_heading(property_obj),
            "location": _property_location(property_obj),
        },
        "bills": bills,
    }
    return render(request, "citizens/property_bills.html", context)


@login_required
def citizen_property_certificate(request, property_id):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        raise Http404("No owner record is linked to this user.")

    context_assembly = _get_current_assembly(request)

    property_qs = Property.objects.filter(_owner_q(owner, "owner"))
    if context_assembly:
        property_qs = property_qs.filter(assembly=context_assembly)

    property_obj = get_object_or_404(property_qs, id=property_id)
    certificate = _ensure_certificate_for_property(property_obj)

    context = {
        "page_title": "Property Certificate",
        "owner_name": _owner_name(owner),
        "owner_short_name": request.user.first_name or _owner_name(owner).split()[0],
        "owner_role": "Property Owner",
        "certificate": certificate,
        "certificate_number": _certificate_number(certificate),
        "property_reference": property_obj.property_reference,
        "property_heading": _property_heading(property_obj),
        "property_type": _property_type_label(property_obj),
        "property_location": _property_location(property_obj),
        "property_status": _property_status(property_obj),
        "digital_address": _digital_address(property_obj),
        "rateable_value": _money_full(getattr(property_obj, "rateable_value", 0)),
        "registered_date": _property_registered_date(property_obj),
        "assembly_name": context_assembly.name if context_assembly else "MMDA",
        "issue_date": timezone.localdate().strftime("%Y-%m-%d"),
        "qr_url": reverse("citizens:certificate-qr", args=[certificate.certificate_uuid]),
        "verify_url": _certificate_verify_absolute_url(request, certificate),
        "download_url": reverse("citizens:certificate-download", args=[certificate.certificate_uuid]),
        "status_label": "Verified & Active" if getattr(property_obj, "is_active", True) else "Inactive",
    }
    return render(request, "citizens/property_certificate.html", context)



@login_required
def citizen_bills(request):
    if (
        get_user_role(request.user)
        != "citizen"
    ):
        return redirect(
            "portal-login"
        )

    context_assembly = (
        _get_current_assembly(
            request
        )
    )

    owner = (
        _citizen_owner_or_none(
            request
        )
    )

    owner_name = (
        _owner_name(owner)
        if owner
        else (
            request.user.get_full_name()
            or request.user.username
        )
    )

    owner_short_name = (
        request.user.first_name
        or owner_name.split()[0]
    )

    unpaid_bills = []
    paid_bills = []

    outstanding_total = (
        Decimal("0.00")
    )

    unpaid_count = 0
    payable_count = 0

    if owner:
        bills_qs = (
            Bill.objects
            .filter(
                _owner_q(
                    owner,
                    "property_record__owner",
                )
            )
            .select_related(
                "property_record",
                "rate_policy",
            )
            .order_by(
                "-billing_year",
                "-created_at",
            )
        )

        if context_assembly:
            bills_qs = (
                bills_qs.filter(
                    assembly=(
                        context_assembly
                    )
                )
            )

        unpaid_qs = (
            bills_qs.exclude(
                status__in=[
                    "paid",
                    "cancelled",
                ]
            )
        )

        paid_qs = (
            bills_qs.filter(
                status="paid",
            )
        )

        unpaid_count = (
            unpaid_qs.count()
        )

        for bill in unpaid_qs:
            prop = (
                bill.property_record
            )

            balance = (
                _bill_balance(
                    bill
                )
            )

            outstanding_total += (
                balance
            )

            can_pay = (
                _property_can_accept_payment(
                    prop
                )
            )

            if can_pay:
                payable_count += 1

            unpaid_bills.append(
                {
                    "id": bill.id,
                    "bill_year": (
                        bill.billing_year
                    ),
                    "status_label": (
                        "Unpaid"
                    ),
                    "account_number": (
                        _account_number_for_property(
                            prop
                        )
                    ),
                    "property_location": (
                        _property_location(
                            prop
                        )
                    ),
                    "property_type": (
                        _property_type_label(
                            prop
                        )
                    ),
                    "verification_status": (
                        prop.get_verification_status_display()
                        if hasattr(
                            prop,
                            (
                                "get_verification_"
                                "status_display"
                            ),
                        )
                        else (
                            prop.verification_status
                        )
                    ),
                    "can_pay": can_pay,
                    "rateable_value": (
                        _money_full(
                            getattr(
                                prop,
                                "rateable_value",
                                0,
                            )
                        )
                    ),
                    "rate_impost": (
                        _rate_impost_value(
                            bill
                        )
                    ),
                    "arrears": (
                        _money_full(
                            _arrears_value(
                                bill
                            )
                        )
                    ),
                    "penalty": (
                        _money_full(
                            _penalty_value(
                                bill
                            )
                        )
                    ),
                    "current_fee": (
                        _money_full(
                            _current_fee_value(
                                bill
                            )
                        )
                    ),
                    "total_due": (
                        _money_full(
                            balance
                        )
                    ),
                    "due_date": (
                        bill.due_date.strftime(
                            "%Y-%m-%d"
                        )
                        if bill.due_date
                        else "—"
                    ),
                }
            )

        for bill in paid_qs[:10]:
            prop = (
                bill.property_record
            )

            paid_date = (
                getattr(
                    bill,
                    "last_payment_at",
                    None,
                )
                or getattr(
                    bill,
                    "updated_at",
                    None,
                )
                or getattr(
                    bill,
                    "created_at",
                    None,
                )
            )

            paid_bills.append(
                {
                    "id": bill.id,
                    "bill_year": (
                        bill.billing_year
                    ),
                    "status_label": (
                        "Paid"
                    ),
                    "account_number": (
                        _account_number_for_property(
                            prop
                        )
                    ),
                    "property_location": (
                        _property_location(
                            prop
                        )
                    ),
                    "amount": (
                        _money_full(
                            getattr(
                                bill,
                                "amount_due",
                                0,
                            )
                        )
                    ),
                    "paid_on": (
                        paid_date.strftime(
                            "%Y-%m-%d"
                        )
                        if paid_date
                        else "—"
                    ),
                }
            )

    context = {
        "page_title": "My Bills",
        "owner_name": owner_name,
        "owner_short_name": (
            owner_short_name
        ),
        "owner_role": "Property Owner",
        "outstanding_total": (
            _money_full(
                outstanding_total
            )
        ),
        "unpaid_count": unpaid_count,
        "payable_count": payable_count,
        "unpaid_bills": unpaid_bills,
        "paid_bills": paid_bills,
        "has_owner_profile": (
            bool(owner)
        ),
    }

    return render(
        request,
        "citizens/bills.html",
        context,
    )


@login_required
def citizen_bill_detail(
    request,
    bill_id,
):
    if (
        get_user_role(request.user)
        != "citizen"
    ):
        return redirect(
            "portal-login"
        )

    owner = _citizen_owner_or_none(
        request
    )

    if not owner:
        return redirect(
            "citizens:bills"
        )

    context_assembly = (
        _get_current_assembly(
            request
        )
    )

    bill_qs = (
        Bill.objects
        .filter(
            _owner_q(
                owner,
                "property_record__owner",
            )
        )
        .select_related(
            "property_record",
            "rate_policy",
        )
    )

    if context_assembly:
        bill_qs = bill_qs.filter(
            assembly=context_assembly,
        )

    bill = get_object_or_404(
        bill_qs,
        id=bill_id,
    )

    prop = bill.property_record

    can_pay = (
        _property_can_accept_payment(
            prop
        )
        and bill.status
        not in [
            "paid",
            "cancelled",
        ]
        and _bill_balance(bill) > 0
    )

    verification_status = (
        prop.get_verification_status_display()
        if hasattr(
            prop,
            "get_verification_status_display",
        )
        else "Pending"
    )

    context = {
        "bill": bill,
        "property": prop,

        "assembly_name": (
            context_assembly.name
            if context_assembly
            else "MMDA"
        ),

        "account_number": (
            _account_number_for_property(
                prop
            )
        ),

        "owner_name": (
            _owner_name(owner)
        ),

        "suburb": (
            getattr(
                prop,
                "suburb",
                "",
            )
            or "—"
        ),

        "property_use": (
            _property_type_label(
                prop
            )
        ),

        "zone": (
            getattr(
                prop,
                "zone",
                "",
            )
            or "—"
        ),

        "rateable_value": (
            _money_full(
                getattr(
                    prop,
                    "rateable_value",
                    0,
                )
            )
            .replace(
                "GH₵",
                "",
            )
            .strip()
        ),

        "rate_impost": (
            _rate_impost_value(
                bill
            )
        ),

        "arrears": (
            _money_full(
                _arrears_value(
                    bill
                )
            ).replace(
                "GH₵",
                "GHS ",
            )
        ),

        "penalty": (
            _money_full(
                _penalty_value(
                    bill
                )
            ).replace(
                "GH₵",
                "GHS ",
            )
        ),

        "current_fee": (
            _money_full(
                _current_fee_value(
                    bill
                )
            ).replace(
                "GH₵",
                "GHS ",
            )
        ),

        "total_due": (
            _money_full(
                _bill_balance(
                    bill
                )
            ).replace(
                "GH₵",
                "GHS ",
            )
        ),

        "due_date": (
            bill.due_date.strftime(
                "%Y-%m-%d"
            )
            if bill.due_date
            else "—"
        ),

        "can_pay": can_pay,

        "verification_status": (
            verification_status
        ),
    }

    return render(
        request,
        "citizens/bill_detail.html",
        context,
    )

@login_required
def citizen_payment_confirm(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        return redirect("citizens:bills")

    context_assembly = _get_current_assembly(request)

    if request.method == "POST":
        selected_bill_ids = request.POST.getlist("bill_ids")
        form = CitizenPaymentForm(request.POST)
    else:
        selected_bill_ids = request.GET.getlist("bill")
        if request.GET.get("all") == "1":
            selected_bill_ids = list(
                Bill.objects
                .filter(
                    _owner_q(
                        owner,
                        "property_record__owner",
                    ),
                    property_record__verification_status=(
                        "verified"
                    ),
                    property_record__is_active=True,
                )
                .exclude(
                    status__in=[
                        "paid",
                        "cancelled",
                    ]
                )
                .values_list(
                    "id",
                    flat=True,
                )
            )
        form = CitizenPaymentForm()

    bills_qs = (
        Bill.objects
        .filter(
            _owner_q(
                owner,
                "property_record__owner",
            ),
            id__in=selected_bill_ids,
            property_record__verification_status=(
                "verified"
            ),
            property_record__is_active=True,
        )
        .select_related(
            "property_record",
            "rate_policy",
        )
    )

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    selected_bills = []
    requested_ids = {
        str(value)
        for value in selected_bill_ids
        if str(value).strip()
    }

    eligible_ids = {
        str(item["id"])
        for item in selected_bills
    }

    if requested_ids - eligible_ids:
        messages.warning(
            request,
            (
                "Payment is unavailable until "
                "the property has been verified "
                "by the MMDA."
            ),
        )

        return redirect(
            "citizens:bills"
        )

    if (
        request.method == "GET"
        and request.GET.get("all") == "1"
        and not selected_bills
    ):
        messages.warning(
            request,
            (
                "There are no verified bills "
                "available for payment."
            ),
        )

        return redirect(
            "citizens:bills"
        )
    total_amount = Decimal("0.00")

    for bill in bills_qs:
        balance = _bill_balance(bill)
        total_amount += balance
        selected_bills.append(
            {
                "id": bill.id,
                "account_number": _account_number_for_property(bill.property_record),
                "location": _property_location(bill.property_record),
                "current_fee": _money_full(_current_fee_value(bill)),
                "arrears": _money_full(_arrears_value(bill)),
                "penalty": _money_full(_penalty_value(bill)),
                "balance": _money_full(balance),
            }
        )

    if request.method == "POST" and form.is_valid() and selected_bills:
        request.session["citizen_payment_payload"] = {
            "bill_ids": [item["id"] for item in selected_bills],
            "network": form.cleaned_data["network"],
            "mobile_number": form.cleaned_data["mobile_number"],
            "total_amount": str(total_amount),
        }
        request.session.pop("citizen_payment_result", None)
        request.session.modified = True
        return redirect("citizens:payment-processing")

    context = {
        "page_title": "Confirm Payment",
        "owner_name": _owner_name(owner),
        "owner_short_name": request.user.first_name or _owner_name(owner).split()[0],
        "owner_role": "Property Owner",
        "selected_bills": selected_bills,
        "total_amount": _money_full(total_amount),
        "form": form,
    }
    return render(request, "citizens/payment_confirm.html", context)


@login_required
def citizen_payment_processing(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    if not request.session.get("citizen_payment_payload"):
        return redirect("citizens:bills")

    context = {
        "owner_short_name": request.user.first_name or request.user.username,
        "owner_role": "Property Owner",
    }
    return render(request, "citizens/payment_processing.html", context)


@login_required
def citizen_payment_success(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        return redirect("citizens:bills")

    payload = request.session.get("citizen_payment_payload")
    if not payload:
        return redirect("citizens:bills")

    result = request.session.get("citizen_payment_result")
    context_assembly = _get_current_assembly(request)

    if not result:
        bill_ids = payload.get("bill_ids", [])
        network = payload.get("network")
        mobile_number = payload.get("mobile_number")
        master_reference = f"TXN-{uuid.uuid4().hex[:16].upper()}"

        bills_qs = (
            Bill.objects
            .filter(
                _owner_q(
                    owner,
                    "property_record__owner",
                ),
                id__in=bill_ids,
                property_record__verification_status=(
                    "verified"
                ),
                property_record__is_active=True,
            )
            .select_related(
                "property_record"
            )
            .order_by(
                "id"
            )
        )
        
        if context_assembly:
            bills_qs = bills_qs.filter(assembly=context_assembly)

        bills_paid = []
        total_paid = Decimal("0.00")

        with transaction.atomic():
            for bill in bills_qs:
                balance = _bill_balance(bill)

                if balance <= 0:
                    continue

                bill_payment_reference = f"{master_reference}-B{bill.id}"

                _create_payment_record(
                    bill=bill,
                    amount=balance,
                    network=network,
                    mobile_number=mobile_number,
                    transaction_reference=bill_payment_reference,
                )

                _mark_bill_paid(bill, balance)
                total_paid += balance

                bills_paid.append(
                    {
                        "account_number": _account_number_for_property(bill.property_record),
                        "amount": _money_full(balance),
                    }
                )

        result = {
            "transaction_reference": master_reference,
            "payment_date": timezone.localdate().strftime("%d/%m/%Y"),
            "payment_method": "Mobile Money",
            "total_paid": _money_full(total_paid),
            "bills_paid": bills_paid,
        }
        request.session["citizen_payment_result"] = result
        request.session.modified = True

    context = {
        "owner_short_name": request.user.first_name or _owner_name(owner).split()[0],
        "owner_role": "Property Owner",
        "result": result,
    }
    return render(request, "citizens/payment_success.html", context)


@login_required
def citizen_payment_history(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        return redirect("citizens:dashboard")

    context_assembly = _get_current_assembly(request)

    payments_qs = Payment.objects.filter(
        _owner_q(owner, "property__owner") | _owner_q(owner, "bill__property_record__owner"),
        status="successful",
    ).select_related("property", "bill").order_by("-paid_at", "-created_at")

    if context_assembly:
        payments_qs = payments_qs.filter(assembly=context_assembly)

    payments = []
    total_amount = Decimal("0.00")

    for payment in payments_qs:
        amount = _safe_decimal(getattr(payment, "amount", 0))
        total_amount += amount

        bill = getattr(payment, "bill", None)
        prop = getattr(payment, "property", None) or (bill.property_record if bill else None)

        reference = (
            getattr(payment, "transaction_reference", None)
            or getattr(payment, "reference", None)
            or getattr(payment, "external_reference", None)
            or f"TXN-{payment.pk}"
        )

        paid_on = getattr(payment, "paid_at", None) or getattr(payment, "created_at", None)

        payments.append(
            {
                "transaction_reference": reference,
                "bill_number": getattr(bill, "bill_number", "—"),
                "location": _property_location(prop) if prop else "—",
                "payment_method": (getattr(payment, "payment_method", "") or "Payment").replace("_", " ").title(),
                "reference_code": reference,
                "time_label": paid_on.strftime("%H:%M") if paid_on else "—",
                "date_label": paid_on.strftime("%Y-%m-%d") if paid_on else "—",
                "amount": _money_full(amount),
            }
        )

    context = {
        "page_title": "Payment History",
        "owner_name": _owner_name(owner),
        "owner_short_name": request.user.first_name or _owner_name(owner).split()[0],
        "owner_role": "Property Owner",
        "payments": payments,
        "total_amount": _money_full(total_amount),
        "payments_count": len(payments),
    }
    return render(request, "citizens/payment_history.html", context)


def _citizen_only(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")
    return None


def _get_or_create_citizen_preference(user):
    preference, _ = CitizenPreference.objects.get_or_create(user=user)
    return preference


def _owner_field_names(owner):
    if not owner:
        return set()
    return {
        field.name
        for field in owner._meta.get_fields()
        if getattr(field, "concrete", False) and not getattr(field, "auto_created", False)
    }


def _set_owner_value(owner, candidate_fields, value):
    if not owner:
        return None

    field_names = _owner_field_names(owner)
    for field_name in candidate_fields:
        if field_name in field_names:
            setattr(owner, field_name, value)
            return field_name
    return None


def _save_owner(owner, update_fields):
    if owner and update_fields:
        owner.save(update_fields=update_fields)


def _split_name(full_name):
    full_name = (full_name or "").strip()
    if not full_name:
        return "", ""

    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _display_owner_email(owner, user):
    if owner:
        for field_name in ["email", "email_address"]:
            if hasattr(owner, field_name):
                value = getattr(owner, field_name, "") or ""
                if value:
                    return value
    return user.email or ""


def _display_owner_phone(owner, user):
    profile = getattr(user, "profile", None)

    if owner:
        for field_name in ["primary_phone", "alternate_phone", "phone_number", "phone", "mobile"]:
            if hasattr(owner, field_name):
                value = getattr(owner, field_name, "") or ""
                if value:
                    return value

    if profile and profile.phone_number:
        return profile.phone_number

    return ""


def _display_owner_address(owner, preference, properties_qs):
    if preference and preference.mailing_address:
        return preference.mailing_address

    if owner:
        for field_name in ["postal_address", "residential_address", "address", "location"]:
            if hasattr(owner, field_name):
                value = getattr(owner, field_name, "") or ""
                if value:
                    return value

    first_property = properties_qs.first() if properties_qs is not None else None
    if first_property:
        return _property_location(first_property)

    return ""


def _build_citizen_profile_context(request, *, active_modal="", form_overrides=None):
    context_assembly = _get_current_assembly(request)
    owner = _find_owner_for_user(
        request.user,
        assembly=context_assembly,
    )
    preference = _get_or_create_citizen_preference(request.user)

    properties_qs = _owner_properties_queryset(owner, context_assembly) if owner else Property.objects.none()

    owner_name = _owner_name(owner) if owner else (request.user.get_full_name() or request.user.username)
    owner_short_name = request.user.first_name or owner_name.split()[0]
    display_email = _display_owner_email(owner, request.user)
    display_phone = _display_owner_phone(owner, request.user)
    display_address = _display_owner_address(owner, preference, properties_qs)

    forms = {
        "name_form": CitizenNameForm(initial={"full_name": owner_name}),
        "email_form": CitizenEmailForm(initial={"email": display_email}),
        "phone_form": CitizenPhoneForm(initial={"phone_number": display_phone}),
        "address_form": CitizenAddressForm(initial={"address": display_address}),
        "password_form": CitizenPasswordForm(request.user),
        "notification_form": CitizenNotificationForm(instance=preference),
    }

    if form_overrides:
        forms.update(form_overrides)

    support_phone = getattr(context_assembly, "contact_phone", "") if context_assembly else ""
    support_email = getattr(context_assembly, "contact_email", "") if context_assembly else ""

    if not support_phone:
        support_phone = "0302123456"

    if not support_email:
        support_email = "support@mmda.gov.gh"

    context = {
        "page_title": "Profile",
        "owner_name": owner_name,
        "owner_short_name": owner_short_name,
        "owner_role": "Property Owner",
        "display_email": display_email or "No email added",
        "display_phone": display_phone or "No phone number added",
        "display_address": display_address or "No address added",
        "support_phone": support_phone,
        "support_email": support_email,
        "properties_count": properties_qs.count(),
        "property_items": properties_qs[:2],
        "active_modal": active_modal,
        "has_owner_profile": bool(owner),
        "app_version": "1.0.0",
        **forms,
    }
    return context


@login_required
def citizen_profile(request):
    redirect_response = _citizen_only(request)
    if redirect_response:
        return redirect_response

    modal = (request.GET.get("modal") or "").strip().lower()
    valid_modals = {"name", "email", "phone", "address", "password", "notifications"}
    if modal not in valid_modals:
        modal = ""

    context = _build_citizen_profile_context(request, active_modal=modal)
    return render(request, "citizens/profile.html", context)


@login_required
@require_POST
def citizen_update_name(request):
    redirect_response = _citizen_only(request)
    if redirect_response:
        return redirect_response

    owner = _citizen_owner_or_none(request)
    form = CitizenNameForm(request.POST)

    if form.is_valid():
        full_name = form.cleaned_data["full_name"].strip()
        first_name, last_name = _split_name(full_name)

        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.save(update_fields=["first_name", "last_name"])

        owner_updates = []
        updated_field = _set_owner_value(owner, ["full_name", "name", "owner_name"], full_name)
        if updated_field:
            owner_updates.append(updated_field)
        _save_owner(owner, owner_updates)

        messages.success(request, "Full name updated successfully.")
        return redirect("citizens:profile")

    context = _build_citizen_profile_context(
        request,
        active_modal="name",
        form_overrides={"name_form": form},
    )
    return render(request, "citizens/profile.html", context)


@login_required
@require_POST
def citizen_update_email(request):
    redirect_response = _citizen_only(request)
    if redirect_response:
        return redirect_response

    owner = _citizen_owner_or_none(request)
    form = CitizenEmailForm(request.POST)

    if form.is_valid():
        email = form.cleaned_data["email"].strip().lower()

        request.user.email = email
        request.user.save(update_fields=["email"])

        owner_updates = []
        updated_field = _set_owner_value(owner, ["email", "email_address"], email)
        if updated_field:
            owner_updates.append(updated_field)
        _save_owner(owner, owner_updates)

        messages.success(request, "Email address updated successfully.")
        return redirect("citizens:profile")

    context = _build_citizen_profile_context(
        request,
        active_modal="email",
        form_overrides={"email_form": form},
    )
    return render(request, "citizens/profile.html", context)


@login_required
@require_POST
def citizen_update_phone(request):
    redirect_response = _citizen_only(request)
    if redirect_response:
        return redirect_response

    owner = _citizen_owner_or_none(request)
    profile = getattr(request.user, "profile", None)
    form = CitizenPhoneForm(request.POST)

    if form.is_valid():
        phone_number = form.cleaned_data["phone_number"].strip()

        if profile:
            profile.phone_number = phone_number
            profile.save(update_fields=["phone_number"])

        owner_updates = []
        updated_field = _set_owner_value(owner, ["primary_phone", "alternate_phone", "phone_number", "phone", "mobile"], phone_number)
        if updated_field:
            owner_updates.append(updated_field)
        _save_owner(owner, owner_updates)

        messages.success(request, "Phone number updated successfully.")
        return redirect("citizens:profile")

    context = _build_citizen_profile_context(
        request,
        active_modal="phone",
        form_overrides={"phone_form": form},
    )
    return render(request, "citizens/profile.html", context)


@login_required
@require_POST
def citizen_update_address(request):
    redirect_response = _citizen_only(request)
    if redirect_response:
        return redirect_response

    owner = _citizen_owner_or_none(request)
    preference = _get_or_create_citizen_preference(request.user)
    form = CitizenAddressForm(request.POST)

    if form.is_valid():
        address = form.cleaned_data["address"].strip()

        preference.mailing_address = address
        preference.save(update_fields=["mailing_address", "updated_at"])

        owner_updates = []
        updated_field = _set_owner_value(owner, ["postal_address", "residential_address", "address", "location"], address)
        if updated_field:
            owner_updates.append(updated_field)
        _save_owner(owner, owner_updates)

        messages.success(request, "Address updated successfully.")
        return redirect("citizens:profile")

    context = _build_citizen_profile_context(
        request,
        active_modal="address",
        form_overrides={"address_form": form},
    )
    return render(request, "citizens/profile.html", context)


@login_required
@require_POST
def citizen_change_password(request):
    redirect_response = _citizen_only(
        request
    )

    if redirect_response:
        return redirect_response

    form = CitizenPasswordForm(
        request.user,
        request.POST,
    )

    if form.is_valid():
        user = form.save()

        update_session_auth_hash(
            request,
            user,
        )

        profile = getattr(
            user,
            "profile",
            None,
        )

        if profile:
            profile.must_change_password = False

            profile.save(
                update_fields=[
                    "must_change_password",
                    "updated_at",
                ]
            )

        messages.success(
            request,
            "Password updated successfully.",
        )

        return redirect(
            "citizens:profile"
        )

    context = (
        _build_citizen_profile_context(
            request,
            active_modal="password",
            form_overrides={
                "password_form": form,
            },
        )
    )

    return render(
        request,
        "citizens/profile.html",
        context,
    )


@login_required
@require_POST
def citizen_update_notifications(request):
    redirect_response = _citizen_only(request)
    if redirect_response:
        return redirect_response

    preference = _get_or_create_citizen_preference(request.user)
    form = CitizenNotificationForm(request.POST, instance=preference)

    if form.is_valid():
        form.save()
        messages.success(request, "Notification preferences saved.")
        return redirect("citizens:profile")

    context = _build_citizen_profile_context(
        request,
        active_modal="notifications",
        form_overrides={"notification_form": form},
    )
    return render(request, "citizens/profile.html", context)


@login_required
def citizen_certificates(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    context_assembly = _get_current_assembly(request)
    owner = _citizen_owner_or_none(request)

    owner_name = _owner_name(owner) if owner else (request.user.get_full_name() or request.user.username)
    owner_short_name = request.user.first_name or owner_name.split()[0]

    certificate_cards = []

    if owner:
        properties_qs = _owner_properties_queryset(owner, context_assembly)

        for prop in properties_qs:
            certificate = _ensure_certificate_for_property(prop)

            certificate_cards.append(
                {
                    "certificate_uuid": certificate.certificate_uuid,
                    "certificate_number": _certificate_number(certificate),
                    "property_reference": prop.property_reference,
                    "property_type": _property_type_label(prop),
                    "property_location": _property_location(prop),
                    "digital_address": _digital_address(prop),
                    "rateable_value": _money_full(getattr(prop, "rateable_value", 0)),
                    "registered_date": _property_registered_date(prop),
                    "owner_name": owner_name,
                    "qr_url": _certificate_qr_url(certificate),
                    "download_url": reverse("citizens:certificate-download", args=[certificate.certificate_uuid]),
                    "verify_url": _certificate_verify_absolute_url(request, certificate),
                    "status_label": "Verified & Active" if getattr(prop, "is_active", True) else "Inactive",
                }
            )

    context = {
        "page_title": "Property Certificates",
        "owner_name": owner_name,
        "owner_short_name": owner_short_name,
        "owner_role": "Property Owner",
        "certificate_cards": certificate_cards,
    }
    return render(request, "citizens/certificates.html", context)


@login_required
def citizen_certificate_download(request, certificate_uuid):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        raise Http404("No owner record is linked to this user.")

    context_assembly = _get_current_assembly(request)

    prop_filter = f"{_certificate_property_field_name()}__owner"
    assembly_filter = f"{_certificate_property_field_name()}__assembly"

    certificate_qs = _certificate_queryset().filter(
        _owner_q(owner, prop_filter)
    )

    if context_assembly:
        certificate_qs = certificate_qs.filter(**{assembly_filter: context_assembly})

    certificate = get_object_or_404(certificate_qs, certificate_uuid=certificate_uuid)
    prop = _certificate_property_obj(certificate)

    context = {
        "certificate": certificate,
        "certificate_number": _certificate_number(certificate),
        "qr_url": _certificate_qr_url(certificate),
        "verify_url": _certificate_verify_absolute_url(request, certificate),
        "assembly_name": context_assembly.name if context_assembly else "Ghana MMDA",
        "property_reference": prop.property_reference,
        "property_type": _property_type_label(prop),
        "property_location": _property_location(prop),
        "digital_address": _digital_address(prop),
        "rateable_value": _money_full(getattr(prop, "rateable_value", 0)),
        "registered_date": _property_registered_date(prop),
        "owner_name": _owner_name(owner),
        "status_label": "Verified & Active" if getattr(prop, "is_active", True) else "Inactive",
    }
    return render(request, "citizens/certificate_download.html", context)


def citizen_certificate_qr(request, certificate_uuid):
    certificate = get_object_or_404(
        _certificate_queryset(),
        certificate_uuid=certificate_uuid,
        is_active=True,
    )

    verify_url = _certificate_verify_absolute_url(
        request,
        certificate,
    )

    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=2,
    )

    qr.add_data(verify_url)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="#111111",
        back_color="white",
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(
        buffer.getvalue(),
        content_type="image/png",
    )


def _certificate_payment_summary(
    property_obj,
):
    today = timezone.localdate()

    current_year = today.year

    bills = (
        Bill.objects
        .filter(
            property_record=(
                property_obj
            )
        )
        .order_by(
            "-billing_year",
            "-created_at",
        )
    )

    current_bill = (
        bills.filter(
            billing_year=(
                current_year
            )
        )
        .first()
    )

    total_outstanding = (
        Decimal("0.00")
    )

    for bill in bills.exclude(
        status="cancelled"
    ):
        total_outstanding += (
            _bill_balance(
                bill
            )
        )

    payment_status = (
        "No Bill Issued"
    )

    payment_status_class = (
        "neutral"
    )

    current_amount_due = (
        Decimal("0.00")
    )

    current_amount_paid = (
        Decimal("0.00")
    )

    current_balance = (
        Decimal("0.00")
    )

    billing_year = (
        current_year
    )

    if current_bill:
        current_amount_due = (
            _safe_decimal(
                current_bill.amount_due
            )
        )

        current_amount_paid = (
            _safe_decimal(
                current_bill.amount_paid
            )
        )

        current_balance = (
            _bill_balance(
                current_bill
            )
        )

        billing_year = (
            current_bill.billing_year
        )

        if (
            current_bill.status
            == "paid"
            or (
                current_amount_due > 0
                and current_balance <= 0
            )
        ):
            payment_status = (
                "Paid"
            )

            payment_status_class = (
                "paid"
            )

        elif current_amount_paid > 0:
            payment_status = (
                "Part Paid"
            )

            payment_status_class = (
                "part-paid"
            )

        elif (
            current_bill.due_date
            and current_bill.due_date
            < today
        ):
            payment_status = (
                "Overdue"
            )

            payment_status_class = (
                "unpaid"
            )

        else:
            payment_status = (
                "Unpaid"
            )

            payment_status_class = (
                "unpaid"
            )

    last_payment = (
        Payment.objects
        .filter(
            Q(
                property=property_obj
            )
            | Q(
                bill__property_record=(
                    property_obj
                )
            ),
            status="successful",
        )
        .order_by(
            "-paid_at",
            "-created_at",
        )
        .first()
    )

    return {
        "billing_year": billing_year,
        "payment_status": (
            payment_status
        ),
        "payment_status_class": (
            payment_status_class
        ),
        "current_amount_due": (
            _money_full(
                current_amount_due
            )
        ),
        "current_amount_paid": (
            _money_full(
                current_amount_paid
            )
        ),
        "current_balance": (
            _money_full(
                current_balance
            )
        ),
        "total_outstanding": (
            _money_full(
                total_outstanding
            )
        ),
        "last_payment_date": (
            timezone.localtime(
                last_payment.paid_at
            ).strftime(
                "%d %b %Y %H:%M"
            )
            if (
                last_payment
                and last_payment.paid_at
            )
            else "No successful payment"
        ),
    }


def certificate_verify(
    request,
    certificate_uuid,
):
    certificate = get_object_or_404(
        _certificate_queryset(),
        certificate_uuid=(
            certificate_uuid
        ),
        is_active=True,
    )

    prop = (
        _certificate_property_obj(
            certificate
        )
    )

    payment_summary = (
        _certificate_payment_summary(
            prop
        )
    )

    verification_status = (
        getattr(
            prop,
            "verification_status",
            "",
        )
        or ""
    ).lower()

    if (
        verification_status
        == "verified"
        and getattr(
            prop,
            "is_active",
            True,
        )
    ):
        verification_label = (
            "Verified"
        )

        verification_class = (
            "verified"
        )

    elif verification_status == "rejected":
        verification_label = (
            "Rejected"
        )

        verification_class = (
            "rejected"
        )

    else:
        verification_label = (
            "Pending Verification"
        )

        verification_class = (
            "pending"
        )

    context = {
        "certificate": certificate,
        "certificate_number": (
            _certificate_number(
                certificate
            )
        ),
        "property_reference": (
            prop.property_reference
        ),
        "property_type": (
            _property_type_label(
                prop
            )
        ),
        "property_location": (
            _property_location(
                prop
            )
        ),
        "digital_address": (
            _digital_address(
                prop
            )
        ),
        "registered_date": (
            _property_registered_date(
                prop
            )
        ),

        "verification_label": (
            verification_label
        ),
        "verification_class": (
            verification_class
        ),

        **payment_summary,
    }

    return render(
        request,
        (
            "citizens/"
            "certificate_verify.html"
        ),
        context,
    )


@login_required
def citizen_submit_dispute(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    context_assembly = _get_current_assembly(request)
    owner = _citizen_owner_or_none(request)

    if not owner:
        return redirect("citizens:dashboard")

    owner_name = _owner_name(owner)
    owner_short_name = request.user.first_name or owner_name.split()[0]
    display_email = _display_owner_email(owner, request.user)

    properties_qs = _owner_properties_queryset(owner, context_assembly)

    bills_qs = Bill.objects.filter(
        _owner_q(owner, "property_record__owner")
    ).select_related("property_record").order_by("-billing_year", "-created_at")

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    if request.method == "POST":
        form = CitizenDisputeForm(
            request.POST,
            request.FILES,
            property_queryset=properties_qs,
            bill_queryset=bills_qs,
        )

        if form.is_valid():
            with transaction.atomic():
                dispute = form.save(commit=False)
                dispute.user = request.user
                dispute.assembly = context_assembly
                dispute.save()

                for file in request.FILES.getlist("supporting_documents"):
                    CitizenDisputeAttachment.objects.create(
                        dispute=dispute,
                        file=file,
                        original_name=file.name,
                    )

            messages.success(
                request,
                f"Your dispute {dispute.dispute_number} has been submitted successfully."
            )
            return redirect("citizens:dashboard")
    else:
        initial = {}
        property_id = request.GET.get("property")
        bill_id = request.GET.get("bill")

        if property_id and properties_qs.filter(id=property_id).exists():
            initial["property_record"] = property_id

        if bill_id and bills_qs.filter(id=bill_id).exists():
            initial["bill"] = bill_id
            bill_obj = bills_qs.filter(id=bill_id).first()
            if bill_obj:
                initial["property_record"] = bill_obj.property_record_id

        form = CitizenDisputeForm(
            initial=initial,
            property_queryset=properties_qs,
            bill_queryset=bills_qs,
        )

    context = {
        "page_title": "Submit Dispute",
        "owner_short_name": owner_short_name,
        "owner_role": "Property Owner",
        "display_email": display_email or "No email added",
        "section_links": {
            "dashboard": reverse("citizens:dashboard"),
            "properties": reverse("citizens:properties"),
            "bills": reverse("citizens:bills"),
            "certificates": reverse("citizens:certificates"),
            "profile": reverse("citizens:profile"),
        },
        "cancel_url": reverse("citizens:dashboard"),
        "form": form,
    }
    return render(request, "citizens/submit_dispute.html", context)