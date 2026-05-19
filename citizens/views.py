import io
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from admins.access import get_user_role
from admins.models import Assembly
from billing.models import Bill
from payments.models import Payment
from properties.models import Property

import uuid
from django.db import transaction
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.views.decorators.http import require_POST

from .forms import (
    CitizenAddressForm,
    CitizenEmailForm,
    CitizenNameForm,
    CitizenNotificationForm,
    CitizenPasswordForm,
    CitizenPhoneForm,
    CitizenPaymentForm,
)
from .models import CitizenPreference, PropertyCertificate

import qrcode
from django.conf import settings
from django.http import Http404, HttpResponse
from django.urls import reverse


MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)


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


def _payment_model_field_names():
    return {
        field.name
        for field in Payment._meta.get_fields()
        if getattr(field, "concrete", False) and not getattr(field, "auto_created", False)
    }


def _create_payment_record(bill, amount, network, mobile_number, transaction_reference):
    payment = Payment()
    field_names = _payment_model_field_names()

    if "bill" in field_names:
        payment.bill = bill

    if "property" in field_names:
        payment.property = getattr(bill, "property_record", None)

    if "assembly" in field_names and hasattr(bill, "assembly"):
        payment.assembly = bill.assembly

    if "amount" in field_names:
        payment.amount = amount

    if "status" in field_names:
        payment.status = "successful"

    if "payment_method" in field_names:
        payment.payment_method = "mobile_money"

    if "network" in field_names:
        payment.network = network

    if "mobile_number" in field_names:
        payment.mobile_number = mobile_number

    for field_name in ["transaction_reference", "reference", "external_reference"]:
        if field_name in field_names:
            setattr(payment, field_name, transaction_reference)
            break

    if "paid_at" in field_names:
        payment.paid_at = timezone.now()

    payment.save()
    return payment


def _mark_bill_paid(bill):
    balance = _bill_balance(bill)
    update_fields = []

    if hasattr(bill, "amount_paid"):
        bill.amount_paid = _safe_decimal(getattr(bill, "amount_paid", 0)) + balance
        update_fields.append("amount_paid")

    if hasattr(bill, "status"):
        bill.status = "paid"
        update_fields.append("status")

    if update_fields:
        bill.save(update_fields=update_fields)

    return balance


def _get_current_assembly(request):
    assembly_id = request.session.get("active_assembly_id")

    if assembly_id:
        try:
            return Assembly.objects.get(id=assembly_id, is_active=True)
        except Assembly.DoesNotExist:
            pass

    profile = getattr(request.user, "profile", None)
    if profile and profile.assembly_id:
        try:
            return Assembly.objects.get(id=profile.assembly_id, is_active=True)
        except Assembly.DoesNotExist:
            return None

    return None


def _get_owner_model():
    return Property._meta.get_field("owner").remote_field.model


def _owner_name(owner):
    if not owner:
        return "Property Owner"

    return (
        getattr(owner, "full_name", None)
        or getattr(owner, "name", None)
        or getattr(owner, "owner_name", None)
        or "Property Owner"
    )


def _find_owner_for_user(user):
    if not user or not user.is_authenticated:
        return None

    owner = getattr(user, "owner_profile", None)
    if owner:
        return owner

    owner_model = _get_owner_model()
    owner_field_names = {f.name for f in owner_model._meta.get_fields()}

    for field_name in ["user", "auth_user", "account"]:
        if field_name in owner_field_names:
            try:
                owner = owner_model.objects.filter(**{field_name: user}).first()
                if owner:
                    return owner
            except Exception:
                pass

    if user.email:
        for field_name in ["email", "email_address"]:
            if field_name in owner_field_names:
                try:
                    owner = owner_model.objects.filter(**{f"{field_name}__iexact": user.email}).first()
                    if owner:
                        return owner
                except Exception:
                    pass

    profile = getattr(user, "profile", None)
    phone_number = getattr(profile, "phone_number", "") if profile else ""
    if phone_number:
        for field_name in ["phone_number", "phone", "mobile"]:
            if field_name in owner_field_names:
                try:
                    owner = owner_model.objects.filter(**{field_name: phone_number}).first()
                    if owner:
                        return owner
                except Exception:
                    pass

    return None


def _owner_properties_queryset(owner, assembly=None):
    qs = Property.objects.filter(owner=owner).order_by("-created_at")
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
    house_number = getattr(prop, "house_number", "") or ""
    street_name = getattr(prop, "street_name", "") or ""
    suburb = getattr(prop, "suburb", "") or ""
    area_town = getattr(prop, "area_town", "") or ""

    first_line = " ".join(part for part in [house_number, street_name] if part).strip()
    second_line = ", ".join(part for part in [suburb, area_town] if part).strip(", ")

    if first_line and second_line:
        return f"{first_line}, {second_line}"
    return first_line or second_line or "Location not available"


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
    return _find_owner_for_user(request.user)


@login_required
def citizen_dashboard(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    context_assembly = _get_current_assembly(request)
    owner = _find_owner_for_user(request.user)

    if not owner:
        return render(
            request,
            "citizens/dashboard.html",
            {
                "page_title": "Owner Dashboard",
                "owner_name": request.user.get_full_name() or request.user.username,
                "owner_short_name": request.user.first_name or request.user.username,
                "owner_role": "Property Owner",
                "context_assembly": context_assembly,
                "stats": {
                    "properties_count": 0,
                    "outstanding_total": "GH₵ 0",
                    "paid_total": "GH₵ 0",
                    "bills_count": 0,
                },
                "properties": [],
                "bills": [],
                "payments": [],
                "has_owner_profile": False,
                "current_year": timezone.localdate().year,
            },
        )

    properties_qs = _owner_properties_queryset(owner, context_assembly)
    bills_qs = Bill.objects.filter(property_record__owner=owner).select_related("property_record").order_by("-created_at")
    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    payments_qs = Payment.objects.filter(
        Q(property__owner=owner) | Q(bill__property_record__owner=owner),
        status="successful",
    ).select_related("property", "bill").order_by("-paid_at", "-created_at")

    if context_assembly:
        payments_qs = payments_qs.filter(assembly=context_assembly)

    current_year = timezone.localdate().year

    outstanding_expr = ExpressionWrapper(
        F("amount_due") - F("amount_paid"),
        output_field=MONEY_FIELD,
    )

    outstanding_total = bills_qs.exclude(status__in=["paid", "cancelled"]).aggregate(
        total=Coalesce(Sum(outstanding_expr), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    paid_total = payments_qs.filter(paid_at__year=current_year).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    properties_data = []
    for prop in properties_qs[:5]:
        latest_bill = _latest_property_bill(prop)
        properties_data.append(
            {
                "id": prop.id,
                "reference": prop.property_reference,
                "location": _property_location(prop),
                "type_label": _property_type_label(prop),
                "type_class": "badge-commercial" if "commercial" in _property_type_label(prop).lower() else "badge-residential",
                "annual_rate": _money_full(latest_bill.amount_due if latest_bill else 0),
            }
        )

    bills_data = []
    for bill in bills_qs[:5]:
        status = (bill.status or "").lower()
        if status == "paid":
            status_label = "Paid"
            status_class = "bill-paid"
            action_label = ""
        else:
            status_label = "Unpaid"
            status_class = "bill-unpaid"
            action_label = "Pay Now"

        bills_data.append(
            {
                "bill_number": bill.bill_number,
                "property_reference": bill.property_record.property_reference,
                "amount_due": _money_full(bill.amount_due),
                "due_date": bill.due_date.strftime("%Y-%m-%d") if bill.due_date else "—",
                "status_label": status_label,
                "status_class": status_class,
                "action_label": action_label,
            }
        )

    payments_data = []
    for payment in payments_qs[:5]:
        property_reference = (
            payment.property.property_reference
            if getattr(payment, "property_id", None)
            else payment.bill.property_record.property_reference
            if getattr(payment, "bill_id", None)
            else "Payment"
        )

        payment_date = payment.paid_at or payment.created_at
        payments_data.append(
            {
                "property_reference": property_reference,
                "date_label": payment_date.strftime("%Y-%m-%d") if payment_date else "—",
                "method": (payment.payment_method or "Payment").replace("_", " ").title(),
                "amount": _money_full(payment.amount),
            }
        )

    context = {
        "page_title": "Owner Dashboard",
        "owner_name": _owner_name(owner),
        "owner_short_name": request.user.first_name or _owner_name(owner).split()[0],
        "owner_role": "Property Owner",
        "context_assembly": context_assembly,
        "has_owner_profile": True,
        "stats": {
            "properties_count": properties_qs.count(),
            "outstanding_total": _money(outstanding_total),
            "paid_total": _money(paid_total),
            "bills_count": bills_qs.count(),
        },
        "properties": properties_data,
        "bills": bills_data,
        "payments": payments_data,
        "current_year": current_year,
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

    property_qs = Property.objects.filter(owner=owner)
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

    property_qs = Property.objects.filter(owner=owner)
    if context_assembly:
        property_qs = property_qs.filter(assembly=context_assembly)

    property_obj = get_object_or_404(property_qs, id=property_id)
    latest_bill = _latest_property_bill(property_obj)
    metric_label, metric_value = _property_secondary_metric(property_obj)

    context = {
        "page_title": "Property Certificate",
        "owner_name": _owner_name(owner),
        "property_reference": property_obj.property_reference,
        "property_heading": _property_heading(property_obj),
        "property_location": _property_location(property_obj),
        "property_status": _property_status(property_obj),
        "digital_address": _digital_address(property_obj),
        "rateable_value": _money_full(getattr(property_obj, "rateable_value", 0)),
        "annual_rate": _money_full(latest_bill.amount_due if latest_bill else 0),
        "metric_label": metric_label,
        "metric_value": metric_value,
        "assembly_name": context_assembly.name if context_assembly else "MMDA",
        "issue_date": timezone.localdate().strftime("%Y-%m-%d"),
    }
    return render(request, "citizens/property_certificate.html", context)


@login_required
def citizen_bills(request):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    context_assembly = _get_current_assembly(request)
    owner = _citizen_owner_or_none(request)

    owner_name = _owner_name(owner) if owner else (request.user.get_full_name() or request.user.username)
    owner_short_name = request.user.first_name or owner_name.split()[0]

    unpaid_bills = []
    paid_bills = []
    outstanding_total = Decimal("0.00")
    unpaid_count = 0

    if owner:
        bills_qs = Bill.objects.filter(property_record__owner=owner).select_related("property_record", "rate_policy").order_by("-billing_year", "-created_at")

        if context_assembly:
            bills_qs = bills_qs.filter(assembly=context_assembly)

        unpaid_qs = bills_qs.exclude(status__in=["paid", "cancelled"])
        paid_qs = bills_qs.filter(status="paid")

        unpaid_count = unpaid_qs.count()

        for bill in unpaid_qs:
            prop = bill.property_record
            balance = _bill_balance(bill)
            outstanding_total += balance

            unpaid_bills.append(
                {
                    "id": bill.id,
                    "bill_year": bill.billing_year,
                    "status_label": "Unpaid",
                    "account_number": _account_number_for_property(prop),
                    "property_location": _property_location(prop),
                    "property_type": _property_type_label(prop),
                    "rateable_value": _money_full(getattr(prop, "rateable_value", 0)),
                    "rate_impost": _rate_impost_value(bill),
                    "arrears": _money_full(_arrears_value(bill)),
                    "penalty": _money_full(_penalty_value(bill)),
                    "current_fee": _money_full(_current_fee_value(bill)),
                    "total_due": _money_full(balance),
                    "due_date": bill.due_date.strftime("%Y-%m-%d") if bill.due_date else "—",
                }
            )

        for bill in paid_qs[:10]:
            prop = bill.property_record
            paid_bills.append(
                {
                    "id": bill.id,
                    "bill_year": bill.billing_year,
                    "status_label": "Paid",
                    "account_number": _account_number_for_property(prop),
                    "property_location": _property_location(prop),
                    "amount": _money_full(getattr(bill, "amount_due", 0)),
                    "paid_on": (
                        getattr(bill, "updated_at", None) or getattr(bill, "created_at", None)
                    ).strftime("%Y-%m-%d") if (getattr(bill, "updated_at", None) or getattr(bill, "created_at", None)) else "—",
                }
            )

    context = {
        "page_title": "My Bills",
        "owner_name": owner_name,
        "owner_short_name": owner_short_name,
        "owner_role": "Property Owner",
        "outstanding_total": _money_full(outstanding_total),
        "unpaid_count": unpaid_count,
        "unpaid_bills": unpaid_bills,
        "paid_bills": paid_bills,
        "has_owner_profile": bool(owner),
    }
    return render(request, "citizens/bills.html", context)


@login_required
def citizen_bill_detail(request, bill_id):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        return redirect("citizens:bills")

    context_assembly = _get_current_assembly(request)

    bill_qs = Bill.objects.filter(property_record__owner=owner).select_related("property_record", "rate_policy")
    if context_assembly:
        bill_qs = bill_qs.filter(assembly=context_assembly)

    bill = get_object_or_404(bill_qs, id=bill_id)
    prop = bill.property_record

    context = {
        "bill": bill,
        "property": prop,
        "assembly_name": context_assembly.name if context_assembly else "MMDA",
        "account_number": _account_number_for_property(prop),
        "owner_name": _owner_name(owner),
        "suburb": getattr(prop, "suburb", "") or "—",
        "property_use": _property_type_label(prop),
        "zone": getattr(prop, "zone", "") or "—",
        "rateable_value": _money_full(getattr(prop, "rateable_value", 0)).replace("GH₵", "").strip(),
        "rate_impost": _rate_impost_value(bill),
        "arrears": _money_full(_arrears_value(bill)).replace("GH₵", "GHS "),
        "penalty": _money_full(_penalty_value(bill)).replace("GH₵", "GHS "),
        "current_fee": _money_full(_current_fee_value(bill)).replace("GH₵", "GHS "),
        "total_due": _money_full(_bill_balance(bill)).replace("GH₵", "GHS "),
        "due_date": bill.due_date.strftime("%Y-%m-%d") if bill.due_date else "—",
    }
    return render(request, "citizens/bill_detail.html", context)


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
                Bill.objects.filter(property_record__owner=owner)
                .exclude(status__in=["paid", "cancelled"])
                .values_list("id", flat=True)
            )
        form = CitizenPaymentForm()

    bills_qs = Bill.objects.filter(
        id__in=selected_bill_ids,
        property_record__owner=owner,
    ).select_related("property_record", "rate_policy")

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    selected_bills = []
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
        transaction_reference = f"TXN-{uuid.uuid4().hex[:16].upper()}"

        bills_qs = Bill.objects.filter(
            id__in=bill_ids,
            property_record__owner=owner,
        ).select_related("property_record")

        if context_assembly:
            bills_qs = bills_qs.filter(assembly=context_assembly)

        bills_paid = []
        total_paid = Decimal("0.00")

        with transaction.atomic():
            for bill in bills_qs:
                amount_paid_now = _mark_bill_paid(bill)
                total_paid += amount_paid_now
                _create_payment_record(
                    bill=bill,
                    amount=amount_paid_now,
                    network=network,
                    mobile_number=mobile_number,
                    transaction_reference=transaction_reference,
                )
                bills_paid.append(
                    {
                        "account_number": _account_number_for_property(bill.property_record),
                        "amount": _money_full(amount_paid_now),
                    }
                )

        result = {
            "transaction_reference": transaction_reference,
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
        Q(property__owner=owner) | Q(bill__property_record__owner=owner),
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
        for field_name in ["phone_number", "phone", "mobile"]:
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
        for field_name in ["address", "residential_address", "postal_address", "location"]:
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
    owner = _find_owner_for_user(request.user)
    preference = _get_or_create_citizen_preference(request.user)

    properties_qs = (
        _owner_properties_queryset(owner, context_assembly)
        if owner
        else Property.objects.none()
    )

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

    owner = _find_owner_for_user(request.user)
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

    owner = _find_owner_for_user(request.user)
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

    owner = _find_owner_for_user(request.user)
    profile = getattr(request.user, "profile", None)
    form = CitizenPhoneForm(request.POST)

    if form.is_valid():
        phone_number = form.cleaned_data["phone_number"].strip()

        if profile:
            profile.phone_number = phone_number
            profile.save(update_fields=["phone_number"])

        owner_updates = []
        updated_field = _set_owner_value(owner, ["phone_number", "phone", "mobile"], phone_number)
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

    owner = _find_owner_for_user(request.user)
    preference = _get_or_create_citizen_preference(request.user)
    form = CitizenAddressForm(request.POST)

    if form.is_valid():
        address = form.cleaned_data["address"].strip()

        preference.mailing_address = address
        preference.save(update_fields=["mailing_address", "updated_at"])

        owner_updates = []
        updated_field = _set_owner_value(owner, ["address", "residential_address", "postal_address", "location"], address)
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
    redirect_response = _citizen_only(request)
    if redirect_response:
        return redirect_response

    form = CitizenPasswordForm(request.user, request.POST)

    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Password updated successfully.")
        return redirect("citizens:profile")

    context = _build_citizen_profile_context(
        request,
        active_modal="password",
        form_overrides={"password_form": form},
    )
    return render(request, "citizens/profile.html", context)


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
                    "qr_url": _certificate_qr_absolute_url(request, certificate),
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

    certificate_qs = PropertyCertificate.objects.select_related("property").filter(
        property__owner=owner
    )

    if context_assembly:
        certificate_qs = certificate_qs.filter(property__assembly=context_assembly)

    certificate = get_object_or_404(certificate_qs, certificate_uuid=certificate_uuid)
    prop = certificate.property

    context = {
        "certificate": certificate,
        "certificate_number": _certificate_number(certificate),
        "qr_url": _certificate_qr_absolute_url(request, certificate),
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


@login_required
def citizen_certificate_qr(request, certificate_uuid):
    if get_user_role(request.user) != "citizen":
        return redirect("portal-login")

    owner = _citizen_owner_or_none(request)
    if not owner:
        raise Http404("No owner record is linked to this user.")

    context_assembly = _get_current_assembly(request)

    certificate_qs = PropertyCertificate.objects.select_related("property").filter(
        property__owner=owner
    )

    if context_assembly:
        certificate_qs = certificate_qs.filter(property__assembly=context_assembly)

    certificate = get_object_or_404(certificate_qs, certificate_uuid=certificate_uuid)

    verify_url = _certificate_verify_absolute_url(request, certificate)

    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=2,
    )
    qr.add_data(verify_url)
    qr.make(fit=True)

    image = qr.make_image(fill_color="#d8bf7c", back_color="white")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(buffer.getvalue(), content_type="image/png")


def certificate_verify(request, certificate_uuid):
    certificate = get_object_or_404(
        PropertyCertificate.objects.select_related("property"),
        certificate_uuid=certificate_uuid,
        is_active=True,
    )

    prop = certificate.property
    owner = getattr(prop, "owner", None)

    context = {
        "certificate": certificate,
        "certificate_number": _certificate_number(certificate),
        "property_reference": prop.property_reference,
        "property_type": _property_type_label(prop),
        "property_location": _property_location(prop),
        "digital_address": _digital_address(prop),
        "rateable_value": _money_full(getattr(prop, "rateable_value", 0)),
        "registered_date": _property_registered_date(prop),
        "owner_name": _owner_name(owner),
        "status_label": "Verified & Active" if getattr(prop, "is_active", True) else "Inactive",
    }
    return render(request, "citizens/certificate_verify.html", context)


def _ensure_certificate_for_property(property_obj):
    certificate, _ = PropertyCertificate.objects.get_or_create(property=property_obj)
    return certificate


def _certificate_verify_absolute_url(request, certificate):
    relative_url = reverse("citizens:certificate-verify", args=[certificate.certificate_uuid])

    site_public_url = getattr(settings, "SITE_PUBLIC_URL", "").strip()
    if site_public_url:
        return f"{site_public_url.rstrip('/')}{relative_url}"

    return request.build_absolute_uri(relative_url)


def _certificate_qr_absolute_url(request, certificate):
    relative_url = reverse("citizens:certificate-qr", args=[certificate.certificate_uuid])
    site_public_url = getattr(settings, "SITE_PUBLIC_URL", "").strip()
    if site_public_url:
        return f"{site_public_url.rstrip('/')}{relative_url}"
    return request.build_absolute_uri(relative_url)


def _certificate_number(certificate):
    year = getattr(certificate.property, "created_at", None)
    year_value = year.year if year else 2026
    return f"{certificate.property.property_reference}-CERT-{year_value}"


def _property_registered_date(prop):
    created = getattr(prop, "created_at", None)
    if created:
        return created.strftime("%Y-%m-%d")
    return "—"