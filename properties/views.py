from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from admins.access import get_allowed_modules, get_user_role
from admins.decorators import module_required
from admins.models import Assembly
from billing.models import Bill, CommunityArea, RatePolicy
from payments.models import Payment
from properties.forms import PropertyCreateForm, PropertyUpdateForm, OwnerUpdateForm
from properties.models import Property
from properties.utils import link_or_create_citizen_for_owner
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def log_view_errors(view_function):
    @wraps(view_function)
    def wrapper(*args, **kwargs):
        try:
            return view_function(
                *args,
                **kwargs,
            )
        except Exception:
            logger.exception(
                "Unhandled error inside %s",
                view_function.__name__,
            )
            raise

    return wrapper

@log_view_errors
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


def _property_type_label(prop):
    if hasattr(prop, "get_property_use_display"):
        return prop.get_property_use_display()

    raw = (getattr(prop, "property_use", "") or "").replace("_", " ").title()
    return raw or "—"


def _property_type_class(prop):
    label = _property_type_label(prop).lower()
    if "mixed" in label:
        return "type-mixed"
    if "commercial" in label:
        return "type-commercial"
    return "type-residential"


def _property_status(prop):
    verification_status = (getattr(prop, "verification_status", "") or "").lower()
    is_active = getattr(prop, "is_active", True)

    if not is_active:
        return "Inactive", "status-inactive"

    if verification_status in ["pending", "under_review", "unverified"]:
        return "Pending", "status-pending"

    return "Active", "status-active"


def _property_location(prop):
    parts = []
    address_line = getattr(prop, "address_line", "") or ""
    suburb = getattr(prop, "suburb", "") or ""
    area = getattr(prop, "area_town", "") or ""

    if address_line:
        parts.append(address_line)
    if suburb:
        parts.append(suburb)
    if area and area not in parts:
        parts.append(area)

    return ", ".join(parts) if parts else "—"


def _get_active_rate_policy(*, assembly, property_use, community_area, building_type, preview_date=None):
    preview_date = preview_date or timezone.localdate()
    return RatePolicy.get_applicable_policy(
        assembly=assembly,
        property_use=property_use,
        community_area=community_area,
        building_type=building_type,
        on_date=preview_date,
        year=preview_date.year,
    )


@module_required("properties")
@require_GET
def property_rate_preview(request):
    context_assembly = _get_current_assembly(request)

    if not context_assembly:
        return JsonResponse({"error": "No active assembly found."}, status=400)

    property_use = (request.GET.get("property_use") or "").strip()
    building_type = (request.GET.get("building_type") or "").strip()
    rateable_value_raw = (request.GET.get("rateable_value") or "").strip()
    community_area_id = (request.GET.get("community_area") or "").strip()

    if not property_use or not community_area_id or not rateable_value_raw:
        return JsonResponse({"error": "Property use, community / area and rateable value are required."}, status=400)

    try:
        rateable_value = Decimal(rateable_value_raw)
    except (InvalidOperation, TypeError):
        return JsonResponse({"error": "Invalid rateable value."}, status=400)

    if rateable_value < 0:
        return JsonResponse({"error": "Rateable value cannot be negative."}, status=400)

    try:
        community_area = CommunityArea.objects.get(
            pk=community_area_id,
            assembly=context_assembly,
            is_active=True,
        )
    except CommunityArea.DoesNotExist:
        return JsonResponse({"error": "Selected community / area was not found."}, status=404)

    policy = _get_active_rate_policy(
        assembly=context_assembly,
        property_use=property_use,
        community_area=community_area,
        building_type=building_type,
    )
    if not policy:
        return JsonResponse({"error": "No active rate policy matches the selected billing year, community / area, property use and building type."}, status=404)

    principal = policy.calculate_principal(rateable_value)

    return JsonResponse(
        {
            "policy_name": policy.policy_name,
            "property_class": policy.property_class,
            "rate_impost": str(policy.rate_impost),
            "minimum_charge": str(policy.minimum_charge),
            "annual_rate": str(principal),
            "annual_rate_display": f"GH₵ {principal:,.2f}",
            "policy_year": policy.year,
            "community_area": community_area.name,
            "sub_metro": community_area.get_sub_metro_display(),
        }
    )


@module_required("properties")
@log_view_errors
def property_registry(request):
    context_assembly = _get_current_assembly(request)
    portal_access = get_allowed_modules(request.user)
    user_role = get_user_role(request.user)

    search = (request.GET.get("q") or "").strip()
    location = (request.GET.get("location") or "").strip()
    property_type = (request.GET.get("type") or "").strip()
    record_status = (request.GET.get("status") or "").strip()
    verification = (request.GET.get("verification") or "").strip()
    billing_filter = (request.GET.get("billing") or "").strip()
    payment_filter = (request.GET.get("payment") or "").strip()
    page_number = request.GET.get("page", 1)

    property_bills = Bill.objects.filter(
        property_record_id=OuterRef("pk")
    )
    paid_property_bills = property_bills.exclude(
        status="cancelled"
    ).filter(
        amount_due__gt=0,
        amount_paid__gte=F("amount_due"),
    )
    outstanding_property_bills = property_bills.exclude(
        status="cancelled"
    ).filter(
        amount_due__gt=F("amount_paid")
    )
    successful_property_payments = Payment.objects.filter(
        status="successful"
    ).filter(
        Q(property_id=OuterRef("pk"))
        | Q(bill__property_record_id=OuterRef("pk"))
    )

    properties_qs = Property.objects.select_related(
        "owner",
        "assembly",
        "community_area",
        "applied_rate_policy",
    ).annotate(
        has_bill=Exists(property_bills),
        has_paid_bill=Exists(paid_property_bills),
        has_outstanding_bill=Exists(
            outstanding_property_bills
        ),
        has_successful_payment=Exists(
            successful_property_payments
        ),
    ).order_by("-created_at")
    

    if context_assembly:
        properties_qs = properties_qs.filter(assembly=context_assembly)

    if user_role == "field_officer":
        properties_qs = properties_qs.filter(registered_by=request.user)

    if search:
        properties_qs = properties_qs.filter(
            Q(property_reference__icontains=search)
            | Q(owner__full_name__icontains=search)
            | Q(area_town__icontains=search)
            | Q(suburb__icontains=search)
            | Q(address_line__icontains=search)
            | Q(property_class__icontains=search)
            | Q(community_area__name__icontains=search)
        )

    if location:
        properties_qs = properties_qs.filter(
            Q(area_town__icontains=location)
            | Q(suburb__icontains=location)
            | Q(address_line__icontains=location)
            | Q(digital_address__icontains=location)
            | Q(community_area__name__icontains=location)
        )

    if property_type:
        properties_qs = properties_qs.filter(property_use=property_type)

    if record_status == "active":
        properties_qs = properties_qs.filter(is_active=True)
    elif record_status == "inactive":
        properties_qs = properties_qs.filter(is_active=False)
    elif record_status == "pending":
        # Preserve older bookmarked links that used status=pending.
        verification = verification or "pending"

    if verification == "unverified":
        properties_qs = properties_qs.exclude(
            verification_status="verified"
        )
    elif verification == "awaiting_review":
        properties_qs = properties_qs.filter(
            verification_status__in=["pending", "under_review"]
        )
    elif verification:
        properties_qs = properties_qs.filter(
            verification_status=verification
        )

    if billing_filter == "billed":
        properties_qs = properties_qs.filter(has_bill=True)
    elif billing_filter == "unbilled":
        properties_qs = properties_qs.filter(has_bill=False)
    elif billing_filter == "paid":
        properties_qs = properties_qs.filter(has_paid_bill=True)
    elif billing_filter == "outstanding":
        properties_qs = properties_qs.filter(
            has_outstanding_bill=True
        )

    if payment_filter == "recorded":
        properties_qs = properties_qs.filter(
            has_successful_payment=True
        )
    elif payment_filter == "none":
        properties_qs = properties_qs.filter(
            has_successful_payment=False
        )

    paginator = Paginator(properties_qs, 6)
    page_obj = paginator.get_page(page_number)

    property_rows = []
    for prop in page_obj:
        status_label, status_class = _property_status(prop)

        owner_name = "—"
        owner = getattr(prop, "owner", None)
        if owner:
            owner_name = getattr(owner, "full_name", None) or str(owner)

        property_rows.append(
            {
                "id": prop.id,
                "reference": prop.property_reference,
                "owner_name": owner_name,
                "location": _property_location(prop),
                "type_label": _property_type_label(prop),
                "type_class": _property_type_class(prop),
                "property_class": (
                    prop.property_class
                    or "—"
                ),
                "community_area": getattr(getattr(prop, "community_area", None), "name", "—"),
                "rateable_value": f"GH₵ {prop.rateable_value:,.0f}" if getattr(prop, "rateable_value", None) else "GH₵ 0",
                "status_label": status_label,
                "status_class": status_class,
            }
        )

    type_choices = list(Property.PROPERTY_USE_CHOICES)
    filter_query_params = request.GET.copy()
    filter_query_params.pop("page", None)

    context = {
        "page_title": "Property Registry" if user_role != "field_officer" else "My Registered Properties",
        "page_subtitle": (
            f"Manage and view all registered properties ({paginator.count} total)"
            if user_role != "field_officer"
            else f"Properties you registered ({paginator.count} total)"
        ),
        "context_assembly": context_assembly,
        "properties": property_rows,
        "page_obj": page_obj,
        "paginator": paginator,
        "start_index": page_obj.start_index() if paginator.count else 0,
        "end_index": page_obj.end_index() if paginator.count else 0,
        "search": search,
        "location": location,
        "selected_type": property_type,
        "selected_status": record_status,
        "selected_verification": verification,
        "selected_billing": billing_filter,
        "selected_payment": payment_filter,
        "type_choices": type_choices,
        "verification_choices": [
            ("verified", "Verified"),
            ("unverified", "All Unverified"),
            ("awaiting_review", "Pending / Under Review"),
            ("pending", "Pending"),
            ("under_review", "Under Review"),
            ("flagged", "Flagged"),
            ("possible_duplicate", "Possible Duplicate"),
            ("rejected", "Rejected"),
        ],
        "filter_query": filter_query_params.urlencode(),
        "portal_access": portal_access,
    }
    return render(request, "properties/property_registry.html", context)


@module_required("properties")
def add_property(request):
    context_assembly = _get_current_assembly(request)
    portal_access = get_allowed_modules(request.user)

    if not context_assembly:
        messages.error(
            request,
            "No active assembly was found for your account.",
        )
        return redirect(
            "properties:property-registry"
        )

    if request.method == "POST":
        form = PropertyCreateForm(
            request.POST,
            assembly=context_assembly,
        )

        if form.is_valid():
            property_instance = None

            try:
                with transaction.atomic():
                    property_instance = form.save(
                        assembly=context_assembly
                    )

                    update_fields = []

                    if (
                        hasattr(
                            property_instance,
                            "registered_by_id",
                        )
                        and not property_instance.registered_by_id
                    ):
                        property_instance.registered_by = (
                            request.user
                        )
                        update_fields.append(
                            "registered_by"
                        )

                    if hasattr(
                        property_instance,
                        "registration_source",
                    ):
                        role = get_user_role(
                            request.user
                        )

                        property_instance.registration_source = (
                            "field"
                            if role == "field_officer"
                            else "admin"
                        )

                        update_fields.append(
                            "registration_source"
                        )

                    if update_fields:
                        property_instance.save(
                            update_fields=update_fields
                        )

            except ValidationError as exc:
                logger.exception(
                    "Rate policy validation failed "
                    "while saving property."
                )

                form.add_error(
                    None,
                    exc,
                )

                messages.error(
                    request,
                    (
                        "Please resolve the rate policy "
                        "validation error and try again."
                    ),
                )

            except Exception as exc:
                logger.exception(
                    "Property database save failed."
                )

                messages.error(
                    request,
                    (
                        "Could not save the property. "
                        f"Error: {exc}"
                    ),
                )

            else:
                owner = getattr(
                    property_instance,
                    "owner",
                    None,
                )

                account_result = {
                    "created": False,
                    "linked": False,
                    "username": "",
                }

                try:
                    account_result = (
                        link_or_create_citizen_for_owner(
                            owner,
                        )
                    )

                except Exception as exc:
                    logger.exception(
                        "Property saved, but citizen "
                        "account creation failed."
                    )

                    messages.warning(
                        request,
                        (
                            "The property was saved successfully, "
                            "but the citizen account could not be "
                            f"created automatically. Error: {exc}"
                        ),
                    )

                messages.success(
                    request,
                    (
                        f"Property "
                        f"{property_instance.property_reference} "
                        "was added successfully."
                    ),
                )

                if account_result.get("created"):
                    messages.info(
                        request,
                        (
                            "Citizen account created for "
                            f"{owner.full_name}.\n\n"
                            "Phone number: "
                            f"{account_result['login_phone']}\n"
                            "Temporary password: "
                            f"{account_result['temporary_password']}"
                        ),
                        extra_tags="credentials",
                    )

                elif account_result.get("linked"):
                    messages.info(
                        request,
                        (
                            f"Property owner {owner.full_name} "
                            "was linked to citizen account: "
                            f"{account_result['username']}."
                        ),
                    )

                return redirect(
                    "properties:property-registry"
                )

        else:
            messages.error(
                request,
                (
                    "Please correct the highlighted "
                    "errors and try again."
                ),
            )

    else:
        form = PropertyCreateForm(
            assembly=context_assembly,
        )

    context = {
        "page_title": "Add Property",
        "page_subtitle": (
            "Register a new property into the system"
        ),
        "context_assembly": context_assembly,
        "form": form,
        "property_fields": [
            form[name]
            for name in form.property_field_names
        ],
        "owner_selector_fields": [
            form[name]
            for name in form.owner_selector_field_names
        ],
        "owner_fields": [
            form[name]
            for name in form.owner_field_names
        ],
        "portal_access": portal_access,
    }

    return render(
        request,
        "properties/property_form.html",
        context,
    )


def _property_access_queryset(request):
    context_assembly = (
        _get_current_assembly(
            request
        )
    )

    user_role = get_user_role(
        request.user
    )

    queryset = (
        Property.objects
        .select_related(
            "owner",
            "assembly",
            "community_area",
            "applied_rate_policy",
            "registered_by",
        )
        .order_by(
            "-created_at"
        )
    )

    if context_assembly:
        queryset = queryset.filter(
            assembly=context_assembly
        )

    # Field officers should access properties
    # assigned to them, not only properties
    # they originally registered.
    if user_role == "field_officer":
        queryset = queryset.filter(
            field_assignments__officer=(
                request.user
            )
        ).distinct()

    return queryset


def _latest_bill_for_property(property_obj):
    return (
        Bill.objects
        .filter(property_record=property_obj)
        .select_related("rate_policy", "assembly")
        .order_by("-billing_year", "-created_at")
        .first()
    )


def _money_full(value):
    return f"GH₵ {Decimal(value or 0):,.2f}"


@module_required("properties")
def property_detail(request, property_id):
    property_obj = get_object_or_404(
        _property_access_queryset(request),
        pk=property_id,
    )

    latest_bill = _latest_bill_for_property(property_obj)
    portal_access = get_allowed_modules(request.user)

    context = {
        "page_title": "Property Details",
        "page_subtitle": property_obj.property_reference,
        "context_assembly": _get_current_assembly(request),
        "portal_access": portal_access,
        "property_obj": property_obj,
        "owner": property_obj.owner,
        "latest_bill": latest_bill,
        "rate_policy": property_obj.applied_rate_policy,
        "property_location": _property_location(property_obj),
        "property_type_label": _property_type_label(property_obj),
        "status_label": _property_status(property_obj)[0],
        "status_css_class": _property_status(property_obj)[1],
        "annual_rate": _money_full(getattr(latest_bill, "amount_due", 0)) if latest_bill else "GH₵ 0.00",
    }

    return render(request, "properties/property_detail.html", context)


@module_required("properties")
def edit_property(
    request,
    property_id,
):
    property_obj = get_object_or_404(
        _property_access_queryset(
            request
        ),
        pk=property_id,
    )

    portal_access = (
        get_allowed_modules(
            request.user
        )
    )

    user_role = get_user_role(
        request.user
    )

    old_verification_status = (
        property_obj.verification_status
    )

    if request.method == "POST":
        owner_form = OwnerUpdateForm(
            request.POST,
            instance=property_obj.owner,
            prefix="owner",
        )

        property_form = PropertyUpdateForm(
            request.POST,
            instance=property_obj,
            assembly=property_obj.assembly,
            prefix="property",
        )

        # Field officers verify through their
        # dedicated verification workflow.
        # They should not bypass it here.
        if user_role == "field_officer":
            property_form.fields.pop(
                "verification_status",
                None,
            )

        if (
            owner_form.is_valid()
            and property_form.is_valid()
        ):
            with transaction.atomic():
                owner_form.save()

                saved_property = (
                    property_form.save()
                )

                new_status = (
                    saved_property
                    .verification_status
                )

                # Admin/property officer verification.
                if (
                    user_role
                    != "field_officer"
                ):
                    if (
                        new_status
                        == "verified"
                    ):
                        saved_property.last_verified_at = (
                            timezone.now()
                        )

                        saved_property.save(
                            update_fields=[
                                "last_verified_at",
                                "updated_at",
                            ]
                        )

                    elif (
                        old_verification_status
                        == "verified"
                        and new_status
                        != "verified"
                    ):
                        saved_property.last_verified_at = None

                        saved_property.save(
                            update_fields=[
                                "last_verified_at",
                                "updated_at",
                            ]
                        )

                    # Keep any existing assignment
                    # synchronized with the admin decision.
                    from field_operations.models import (
                        FieldAssignment,
                    )

                    active_assignments = (
                        FieldAssignment.objects
                        .filter(
                            property=(
                                saved_property
                            ),
                            status__in=[
                                "assigned",
                                "in_progress",
                            ],
                        )
                    )

                    if (
                        new_status
                        == "verified"
                    ):
                        active_assignments.update(
                            status="completed",
                            completed_at=(
                                timezone.now()
                            ),
                        )

                    elif (
                        new_status
                        == "rejected"
                    ):
                        active_assignments.update(
                            status="rejected",
                            completed_at=(
                                timezone.now()
                            ),
                        )

                    elif new_status in {
                        "pending",
                        "under_review",
                        "flagged",
                        "possible_duplicate",
                    }:
                        active_assignments.update(
                            status="in_progress",
                            completed_at=None,
                        )

            messages.success(
                request,
                (
                    f"Property "
                    f"{property_obj.property_reference} "
                    "was updated successfully."
                ),
            )

            return redirect(
                "properties:property-detail",
                property_id=(
                    property_obj.id
                ),
            )

        messages.error(
            request,
            (
                "Please correct the highlighted "
                "errors and try again."
            ),
        )

    else:
        owner_form = OwnerUpdateForm(
            instance=property_obj.owner,
            prefix="owner",
        )

        property_form = PropertyUpdateForm(
            instance=property_obj,
            assembly=property_obj.assembly,
            prefix="property",
        )

        if user_role == "field_officer":
            property_form.fields.pop(
                "verification_status",
                None,
            )

    context = {
        "page_title": "Edit Property",
        "page_subtitle": (
            property_obj.property_reference
        ),
        "context_assembly": (
            _get_current_assembly(
                request
            )
        ),
        "portal_access": portal_access,
        "property_obj": property_obj,
        "owner_form": owner_form,
        "property_form": property_form,
    }

    return render(
        request,
        "properties/property_edit.html",
        context,
    )


@module_required("properties")
def property_document(request, property_id):
    property_obj = get_object_or_404(
        _property_access_queryset(request),
        pk=property_id,
    )

    latest_bill = _latest_bill_for_property(property_obj)
    portal_access = get_allowed_modules(request.user)

    context = {
        "page_title": "Property Document",
        "page_subtitle": property_obj.property_reference,
        "context_assembly": _get_current_assembly(request),
        "portal_access": portal_access,
        "property_obj": property_obj,
        "owner": property_obj.owner,
        "latest_bill": latest_bill,
        "rate_policy": property_obj.applied_rate_policy,
        "property_location": _property_location(property_obj),
        "property_type_label": _property_type_label(property_obj),
        "status_label": _property_status(property_obj)[0],
        "annual_rate": _money_full(getattr(latest_bill, "amount_due", 0)) if latest_bill else "GH₵ 0.00",
        "generated_at": timezone.now(),
    }

    return render(request, "properties/property_document.html", context)
