from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect
from django.utils import timezone

from admins.decorators import module_required
from admins.models import Assembly
from billing.models import Bill, RatePolicy
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


def _policy_title(policy):
    for attr in ["name", "policy_name", "title"]:
        value = getattr(policy, attr, None)
        if value:
            return value
    return str(policy)


def _policy_code(policy):
    for attr in ["policy_code", "code", "reference", "short_code"]:
        value = getattr(policy, attr, None)
        if value:
            return value
    return f"POL-{policy.year}-{policy.pk}"


def _bill_status_data(bill):
    status = (getattr(bill, "status", "") or "").lower()

    if status == "paid":
        return "Paid", "status-paid"
    if status in ["part_paid", "partial"]:
        return "Partial", "status-partial"
    if status in ["cancelled", "void"]:
        return "Cancelled", "status-cancelled"

    return "Unpaid", "status-unpaid"


def _money(value):
    value = value or Decimal("0.00")
    return f"GH₵ {Decimal(value):,.0f}"


def _get_rateable_value(bill):
    snapshot = getattr(bill, "rateable_value_snapshot", None)
    if snapshot is not None:
        return snapshot

    property_record = getattr(bill, "property_record", None)
    if property_record and getattr(property_record, "rateable_value", None) is not None:
        return property_record.rateable_value

    return Decimal("0.00")


def _get_computed_rate(bill):
    for attr in ["amount_due", "current_charge", "computed_amount", "bill_amount"]:
        value = getattr(bill, attr, None)
        if value is not None:
            return value
    return Decimal("0.00")


@module_required("billing")
def billing_management(request):
    context_assembly = _get_current_assembly(request)

    default_year = (
        context_assembly.active_billing_year
        if context_assembly and context_assembly.active_billing_year
        else timezone.localdate().year
    )

    selected_year_raw = (request.GET.get("year") or request.POST.get("year") or str(default_year)).strip()
    search = (request.GET.get("q") or "").strip()
    page_number = request.GET.get("page", 1)

    try:
        selected_year = int(selected_year_raw)
    except ValueError:
        selected_year = default_year

    if request.method == "POST" and request.POST.get("action") == "generate_bills":
        properties_qs = Property.objects.filter(is_active=True)

        if context_assembly:
            properties_qs = properties_qs.filter(assembly=context_assembly)

        try:
            from billing.services import generate_missing_bills

            created_count, skipped = generate_missing_bills(
                billing_year=selected_year,
                queryset=properties_qs,
            )

            if created_count > 0:
                messages.success(
                    request,
                    f"{created_count} bill(s) generated successfully for {selected_year}.",
                )
            else:
                messages.info(
                    request,
                    f"No new bills were generated for {selected_year}.",
                )

            if skipped:
                messages.warning(
                    request,
                    f"{len(skipped)} propert{'ies' if len(skipped) != 1 else 'y'} were skipped during generation.",
                )

        except Exception as exc:
            messages.error(request, f"Bill generation failed: {exc}")

        return redirect(f"{request.path}?year={selected_year}")

    bills_qs = Bill.objects.select_related(
        "assembly",
        "property_record__owner",
        "rate_policy",
    ).order_by("-created_at")

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    bills_qs = bills_qs.filter(billing_year=selected_year)

    if search:
        bills_qs = bills_qs.filter(
            Q(bill_number__icontains=search)
            | Q(property_record__property_reference__icontains=search)
            | Q(property_record__owner__full_name__icontains=search)
        )

    active_policy_qs = RatePolicy.objects.filter(year=selected_year, is_active=True)
    if context_assembly:
        active_policy_qs = active_policy_qs.filter(assembly=context_assembly)
    active_policy = active_policy_qs.first()

    paginator = Paginator(bills_qs, 5)
    page_obj = paginator.get_page(page_number)

    bill_rows = []
    for bill in page_obj:
        status_label, status_class = _bill_status_data(bill)
        property_record = getattr(bill, "property_record", None)
        owner = getattr(property_record, "owner", None)

        bill_rows.append(
            {
                "id": bill.id,
                "bill_no": bill.bill_number,
                "property_ref": getattr(property_record, "property_reference", "—"),
                "owner_name": getattr(owner, "full_name", "—"),
                "rateable_value": _money(_get_rateable_value(bill)),
                "computed_rate": _money(_get_computed_rate(bill)),
                "year": bill.billing_year,
                "status_label": status_label,
                "status_class": status_class,
            }
        )

    start_index = page_obj.start_index() if paginator.count else 0
    end_index = page_obj.end_index() if paginator.count else 0

    context = {
        "page_title": "Billing Management",
        "page_subtitle": "Generate and manage property rate bills",
        "context_assembly": context_assembly,
        "selected_year": selected_year,
        "active_policy": active_policy,
        "active_policy_title": _policy_title(active_policy) if active_policy else "No active policy",
        "active_policy_code": _policy_code(active_policy) if active_policy else f"Create a policy for {selected_year}",
        "bills": bill_rows,
        "page_obj": page_obj,
        "paginator": paginator,
        "start_index": start_index,
        "end_index": end_index,
        "search": search,
        "messages": messages.get_messages(request),
    }
    return render(request, "billing/billing_management.html", context)