from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render

from admins.access import get_allowed_modules
from admins.decorators import module_required
from admins.models import Assembly
from properties.forms import PropertyCreateForm
from properties.models import Property


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
    suburb = getattr(prop, "suburb", "") or ""
    area = getattr(prop, "area_town", "") or ""

    if suburb:
        parts.append(suburb)
    if area and area not in parts:
        parts.append(area)

    return ", ".join(parts) if parts else "—"


@module_required("properties")
def property_registry(request):
    context_assembly = _get_current_assembly(request)
    portal_access = get_allowed_modules(request.user)

    search = (request.GET.get("q") or "").strip()
    property_type = (request.GET.get("type") or "").strip()
    status = (request.GET.get("status") or "").strip()
    page_number = request.GET.get("page", 1)

    properties_qs = Property.objects.select_related("owner", "assembly").order_by("-created_at")

    if context_assembly:
        properties_qs = properties_qs.filter(assembly=context_assembly)

    if search:
        properties_qs = properties_qs.filter(
            Q(property_reference__icontains=search)
            | Q(owner__full_name__icontains=search)
            | Q(area_town__icontains=search)
            | Q(suburb__icontains=search)
        )

    if property_type:
        properties_qs = properties_qs.filter(property_use=property_type)

    if status == "active":
        properties_qs = properties_qs.filter(is_active=True).exclude(
            verification_status__in=["pending", "under_review", "unverified"]
        )
    elif status == "pending":
        properties_qs = properties_qs.filter(
            Q(verification_status__in=["pending", "under_review", "unverified"])
        )
    elif status == "inactive":
        properties_qs = properties_qs.filter(is_active=False)

    paginator = Paginator(properties_qs, 6)
    page_obj = paginator.get_page(page_number)

    property_rows = []
    for prop in page_obj:
        status_label, status_class = _property_status(prop)

        property_rows.append(
            {
                "id": prop.id,
                "reference": prop.property_reference,
                "owner_name": getattr(prop.owner, "full_name", "—"),
                "location": _property_location(prop),
                "type_label": _property_type_label(prop),
                "type_class": _property_type_class(prop),
                "rateable_value": f"GH₵ {prop.rateable_value:,.0f}"
                if getattr(prop, "rateable_value", None)
                else "GH₵ 0",
                "status_label": status_label,
                "status_class": status_class,
            }
        )

    type_choices = []
    if hasattr(Property, "PROPERTY_USE_CHOICES"):
        type_choices = list(Property.PROPERTY_USE_CHOICES)
    elif hasattr(Property, "_meta"):
        field = Property._meta.get_field("property_use")
        if getattr(field, "choices", None):
            type_choices = list(field.choices)

    start_index = page_obj.start_index() if paginator.count else 0
    end_index = page_obj.end_index() if paginator.count else 0

    context = {
        "page_title": "Property Registry",
        "page_subtitle": f"Manage and view all registered properties ({paginator.count} total)",
        "context_assembly": context_assembly,
        "properties": property_rows,
        "page_obj": page_obj,
        "paginator": paginator,
        "start_index": start_index,
        "end_index": end_index,
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

                messages.success(
                    request,
                    f"Property {property_instance.property_reference} was added successfully.",
                )
                return redirect("properties:property-registry")
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
        "portal_access": portal_access,
    }
    return render(request, "properties/property_form.html", context)