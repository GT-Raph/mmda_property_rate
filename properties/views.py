from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from .models import Property


@login_required
def property_registry(request):
    search_query = request.GET.get("q", "").strip()

    queryset = (
        Property.objects.select_related("owner")
        .prefetch_related("bills")
        .order_by("-created_at")
    )

    if search_query:
        queryset = queryset.filter(
            Q(property_reference__icontains=search_query)
            | Q(owner__full_name__icontains=search_query)
            | Q(area_town__icontains=search_query)
            | Q(suburb__icontains=search_query)
            | Q(digital_address__icontains=search_query)
            | Q(address_line__icontains=search_query)
        )

    paginator = Paginator(queryset, 6)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    properties = []

    for prop in page_obj.object_list:
        location_parts = []
        if prop.suburb:
            location_parts.append(prop.suburb)
        if prop.area_town and prop.area_town not in location_parts:
            location_parts.append(prop.area_town)

        location = ", ".join(location_parts) or prop.address_line or "—"

        if not prop.is_active:
            status = "Inactive"
            status_class = "status-inactive"
        elif prop.verification_status == "verified":
            status = "Active"
            status_class = "status-active"
        else:
            status = "Pending"
            status_class = "status-pending"

        billing_history = []
        for bill in prop.bills.all().order_by("-billing_year")[:5]:
            if bill.status == "paid":
                bill_status = "Paid"
            elif bill.status == "part_paid":
                bill_status = "Partial"
            elif bill.status in ["pending", "overdue"]:
                bill_status = "Unpaid"
            else:
                bill_status = bill.status.replace("_", " ").title()

            billing_history.append(
                {
                    "title": f"{bill.billing_year} Annual Rate",
                    "due_date": bill.due_date.strftime("%b %d, %Y") if bill.due_date else "—",
                    "status": bill_status,
                }
            )

        properties.append(
            {
                "id": prop.id,
                "ref": prop.property_reference,
                "owner_name": prop.owner.full_name,
                "location": location,
                "property_type": prop.get_property_use_display(),
                "type_class": "type-blue",
                "rateable_value": f"GH₵ {prop.rateable_value:,.0f}",
                "status": status,
                "status_class": status_class,
                "registration_date": prop.created_at.strftime("%B %d, %Y"),
                "billing_history": billing_history,
            }
        )

    context = {
        "page_title": "Property Registry",
        "page_subtitle": f"Manage and view all registered properties ({paginator.count} total)",
        "properties": properties,
        "page_obj": page_obj,
        "search_query": search_query,
        "total_properties": paginator.count,
        "start_index": page_obj.start_index() if paginator.count else 0,
        "end_index": page_obj.end_index() if paginator.count else 0,
    }
    return render(request, "properties/property_registry.html", context)