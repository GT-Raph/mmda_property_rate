from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from admins.decorators import module_required

from .models import Bill
from .services import generate_missing_bills


@module_required("billing")
@login_required
def billing_management(request):
    current_year = timezone.localdate().year

    if request.method == "POST":
        action = request.POST.get("action")
        year_text = request.POST.get("year", "").strip()
        billing_year = int(year_text) if year_text.isdigit() else current_year

        if action == "generate_bills":
            created_count = generate_missing_bills(billing_year=billing_year)

            if created_count > 0:
                messages.success(request, f"{created_count} bill(s) generated for {billing_year}.")
            else:
                messages.info(request, f"No new bills were generated for {billing_year}.")

            return redirect(f"{reverse('billing:billing-management')}?year={billing_year}")

    search_query = request.GET.get("q", "").strip()
    year_filter = request.GET.get("year", "").strip()
    selected_year = int(year_filter) if year_filter.isdigit() else current_year

    queryset = (
        Bill.objects.select_related("property_record__owner")
        .order_by("-billing_year", "-created_at")
    )

    if search_query:
        queryset = queryset.filter(
            Q(bill_number__icontains=search_query)
            | Q(property_record__property_reference__icontains=search_query)
            | Q(property_record__owner__full_name__icontains=search_query)
        )

    if year_filter.isdigit():
        queryset = queryset.filter(billing_year=selected_year)

    paginator = Paginator(queryset, 5)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    bills = []

    for bill in page_obj.object_list:
        if bill.status == "paid":
            status = "Paid"
            status_class = "status-paid"
        elif bill.status == "part_paid":
            status = "Partial"
            status_class = "status-partial"
        else:
            status = "Unpaid"
            status_class = "status-unpaid"

        bills.append(
            {
                "id": bill.id,
                "bill_no": bill.bill_number,
                "property_ref": bill.property_record.property_reference,
                "owner": bill.property_record.owner.full_name,
                "rateable_value": f"GH₵ {bill.rateable_value_snapshot:,.0f}",
                "computed_rate": f"GH₵ {bill.principal_amount:,.0f}",
                "year": bill.billing_year,
                "status": status,
                "status_class": status_class,
            }
        )

    context = {
        "page_title": "Billing Management",
        "page_subtitle": "Generate and manage property rate bills",
        "bills": bills,
        "page_obj": page_obj,
        "search_query": search_query,
        "selected_year": selected_year,
        "total_bills": paginator.count,
        "start_index": page_obj.start_index() if paginator.count else 0,
        "end_index": page_obj.end_index() if paginator.count else 0,
        "current_year": current_year,
    }
    return render(request, "billing/billing_management.html", context)