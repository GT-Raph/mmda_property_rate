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


MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)


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