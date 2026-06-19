from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from admins.access import get_allowed_modules, get_user_role
from admins.decorators import module_required
from admins.models import Assembly
from billing.models import CommunityArea, RatePolicy
from properties.forms import PropertyCreateForm
from properties.models import Property
from properties.utils import link_or_create_citizen_for_owner


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
            "property_class": policy.property_class.name,
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
def property_registry(request):
    context_assembly = _get_current_assembly(request)
    portal_access = get_allowed_modules(request.user)
    user_role = get_user_role(request.user)

    search = (request.GET.get("q") or "").strip()
    property_type = (request.GET.get("type") or "").strip()
    status = (request.GET.get("status") or "").strip()
    page_number = request.GET.get("page", 1)

    properties_qs = Property.objects.select_related(
        "owner",
        "assembly",
        "community_area",
        "applied_rate_policy",
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
            | Q(property_class__name__icontains=search)
            | Q(community_area__name__icontains=search)
        )

    if property_type:
        properties_qs = properties_qs.filter(property_use=property_type)

    if status == "active":
        properties_qs = properties_qs.filter(is_active=True).exclude(
            verification_status__in=["pending", "under_review", "unverified"]
        )
    elif status == "pending":
        properties_qs = properties_qs.filter(Q(verification_status__in=["pending", "under_review", "unverified"]))
    elif status == "inactive":
        properties_qs = properties_qs.filter(is_active=False)

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
                "property_class": getattr(getattr(prop, "property_class", None), "name", "—"),
                "community_area": getattr(getattr(prop, "community_area", None), "name", "—"),
                "rateable_value": f"GH₵ {prop.rateable_value:,.0f}" if getattr(prop, "rateable_value", None) else "GH₵ 0",
                "status_label": status_label,
                "status_class": status_class,
            }
        )

    type_choices = list(Property.PROPERTY_USE_CHOICES)

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
        "selected_type": property_type,
        "selected_status": status,
        "type_choices": type_choices,
        "portal_access": portal_access,
    }
    return render(request, "properties/property_registry.html", context)


@module_required("properties")
def add_property(request):
    context_assembly = _get_current_assembly(request)
    portal_access = get_allowed_modules(request.user)

    if not context_assembly:
        messages.error(request, "No active assembly was found for your account.")
        return redirect("properties:property-registry")

    if request.method == "POST":
        form = PropertyCreateForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    property_instance = form.save(assembly=context_assembly)

                    update_fields = []

                    if hasattr(property_instance, "registered_by_id") and not property_instance.registered_by_id:
                        property_instance.registered_by = request.user
                        update_fields.append("registered_by")

                    if hasattr(property_instance, "registration_source"):
                        role = get_user_role(request.user)
                        property_instance.registration_source = "field" if role == "field_officer" else "admin"
                        update_fields.append("registration_source")

                    if update_fields:
                        property_instance.save(update_fields=update_fields)

                    owner = getattr(property_instance, "owner", None)
                    account_result = link_or_create_citizen_for_owner(owner, default_password="1234")

                messages.success(request, f"Property {property_instance.property_reference} was added successfully.")

                if account_result.get("created"):
                    messages.info(
                        request,
                        f"Citizen account created for {owner.full_name}. Username: {account_result['username']} | Temporary password: 1234"
                    )
                elif account_result.get("linked"):
                    messages.info(
                        request,
                        f"Property owner {owner.full_name} was linked to citizen account: {account_result['username']}."
                    )

                return redirect("properties:property-registry")

            except ValidationError as exc:
                form.add_error(None, exc)
                messages.error(request, "Please resolve the rate policy validation error and try again.")
            except Exception as exc:
                messages.error(request, f"Could not save the property. {exc}")
        else:
            messages.error(request, "Please correct the highlighted errors and try again.")
    else:
        form = PropertyCreateForm()

    context = {
        "page_title": "Add Property",
        "page_subtitle": "Register a new property into the system",
        "context_assembly": context_assembly,
        "form": form,
        "property_fields": [form[name] for name in form.property_field_names],
        "owner_selector_fields": [form[name] for name in form.owner_selector_field_names],
        "owner_fields": [form[name] for name in form.owner_field_names],
        "portal_access": portal_access,
    }
    return render(request, "properties/property_form.html", context)
