from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Exists, F, Max, OuterRef, Q
from django.shortcuts import render, redirect
from django.utils import timezone

from admins.decorators import module_required
from admins.models import Assembly
from billing.models import Bill, RatePolicy
from payments.models import Payment
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


def _get_user_role(request):
    if getattr(request.user, "is_superuser", False):
        return "super_admin"

    profile = getattr(request.user, "profile", None)
    if profile and getattr(profile, "role", None):
        return str(profile.role).strip().lower()

    if getattr(request.user, "role", None):
        return str(request.user.role).strip().lower()

    return ""


def _has_full_bill_access(request):
    role = _get_user_role(request)
    return getattr(request.user, "is_superuser", False) or role in {
        "admin",
        "super_admin",
        "billing_officer",
    }


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
    for attr in ["amount_due", "current_charge", "computed_amount", "bill_amount", "principal_amount"]:
        value = getattr(bill, attr, None)
        if value is not None:
            return value
    return Decimal("0.00")


def _apply_bill_visibility_filter(bills_qs, request):
    if _has_full_bill_access(request):
        return bills_qs

    return bills_qs.filter(property_record__registered_by=request.user)


def _apply_property_visibility_filter(properties_qs, request):
    if _has_full_bill_access(request):
        return properties_qs

    return properties_qs.filter(registered_by=request.user)


def _get_latest_bill_year(context_assembly, request):
    bills_qs = Bill.objects.all()

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    bills_qs = _apply_bill_visibility_filter(bills_qs, request)

    latest = bills_qs.aggregate(latest_year=Max("billing_year"))["latest_year"]
    return latest


def _get_chart_data(bills_qs):
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    collected_values = [0, 0, 0, 0, 0, 0]
    target_values = [0, 0, 0, 0, 0, 0]

    first_half_bills = bills_qs.filter(created_at__month__lte=6)

    for bill in first_half_bills:
        month_index = min(max(bill.created_at.month, 1), 6) - 1
        collected_values[month_index] += float(bill.amount_paid or 0)
        target_values[month_index] += float(bill.amount_due or 0)

    return month_labels, collected_values, target_values


def _get_kpis(bills_qs):
    total_bills = bills_qs.count()
    total_due = Decimal("0.00")
    total_paid = Decimal("0.00")

    for bill in bills_qs:
        total_due += bill.amount_due or Decimal("0.00")
        total_paid += bill.amount_paid or Decimal("0.00")

    collection_rate = Decimal("0.00")
    if total_due > 0:
        collection_rate = (total_paid / total_due) * Decimal("100")

    return {
        "collection_rate": f"{collection_rate.quantize(Decimal('0.1'))}%",
        "collection_rate_note": f"{_money(total_paid)} collected out of {_money(total_due)}",
        "bills_generated_count": f"{total_bills:,}",
        "bills_generated_note": "for selected year",
        "reports_generated_count": "24",
        "reports_generated_note": "this week",
    }


@module_required("billing")
def billing_management(request):
    context_assembly = _get_current_assembly(request)

    latest_bill_year = _get_latest_bill_year(context_assembly, request)
    default_year = (
        latest_bill_year
        or (context_assembly.active_billing_year if context_assembly and context_assembly.active_billing_year else None)
        or timezone.localdate().year
    )

    selected_year_raw = (request.GET.get("year") or request.POST.get("year") or str(default_year)).strip()
    search = (request.GET.get("q") or "").strip()
    bill_status = (request.GET.get("status") or "").strip()
    property_type = (request.GET.get("type") or "").strip()
    location = (request.GET.get("location") or "").strip()
    payment_filter = (request.GET.get("payment") or "").strip()
    page_number = request.GET.get("page", 1)

    try:
        selected_year = int(selected_year_raw)
    except ValueError:
        selected_year = default_year

    if request.method == "POST" and request.POST.get("action") == "generate_bills":
        properties_qs = Property.objects.filter(is_active=True)

        if context_assembly:
            properties_qs = properties_qs.filter(assembly=context_assembly)

        properties_qs = _apply_property_visibility_filter(properties_qs, request)

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
    ).annotate(
        has_successful_payment=Exists(
            Payment.objects.filter(
                bill_id=OuterRef("pk"),
                status="successful",
            )
        )
    ).order_by("-created_at")

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)

    bills_qs = _apply_bill_visibility_filter(bills_qs, request)
    bills_qs = bills_qs.filter(billing_year=selected_year)

    if search:
        bills_qs = bills_qs.filter(
            Q(bill_number__icontains=search)
            | Q(property_record__property_reference__icontains=search)
            | Q(property_record__owner__full_name__icontains=search)
        )

    if bill_status == "outstanding":
        bills_qs = bills_qs.exclude(
            status="cancelled"
        ).filter(
            amount_due__gt=F("amount_paid")
        )
    elif bill_status:
        bills_qs = bills_qs.filter(status=bill_status)

    if property_type:
        bills_qs = bills_qs.filter(
            property_record__property_use=property_type
        )

    if location:
        bills_qs = bills_qs.filter(
            Q(property_record__area_town__icontains=location)
            | Q(property_record__suburb__icontains=location)
            | Q(property_record__address_line__icontains=location)
            | Q(property_record__digital_address__icontains=location)
            | Q(property_record__community_area__name__icontains=location)
        )

    if payment_filter == "recorded":
        bills_qs = bills_qs.filter(has_successful_payment=True)
    elif payment_filter == "none":
        bills_qs = bills_qs.filter(has_successful_payment=False)

    active_policy_qs = RatePolicy.objects.filter(year=selected_year, is_active=True)
    if context_assembly:
        active_policy_qs = active_policy_qs.filter(assembly=context_assembly)
    active_policy = active_policy_qs.first()

    month_labels, collected_values, target_values = _get_chart_data(bills_qs)
    kpis = _get_kpis(bills_qs)

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
                "property_id": getattr(property_record, "id", None),
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
    filter_query_params = request.GET.copy()
    filter_query_params.pop("page", None)

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
        "location": location,
        "selected_status": bill_status,
        "selected_type": property_type,
        "selected_payment": payment_filter,
        "status_choices": list(Bill.STATUS_CHOICES),
        "type_choices": list(Property.PROPERTY_USE_CHOICES),
        "filter_query": filter_query_params.urlencode(),
        "messages": messages.get_messages(request),
        "chart_labels": month_labels,
        "collected_values": collected_values,
        "target_values": target_values,
        "collection_rate": kpis["collection_rate"],
        "collection_rate_note": kpis["collection_rate_note"],
        "bills_generated_count": kpis["bills_generated_count"],
        "bills_generated_note": kpis["bills_generated_note"],
        "reports_generated_count": kpis["reports_generated_count"],
        "reports_generated_note": kpis["reports_generated_note"],
        "available_reports": [
            {
                "name": "Monthly Revenue Report",
                "description": "Comprehensive revenue collection summary for the month",
                "meta_1": "Format: PDF, Excel",
                "meta_2": f"Year: {selected_year}",
            },
            {
                "name": "Outstanding Bills Report",
                "description": "Properties with overdue payments and follow-up actions",
                "meta_1": "Format: PDF, Excel",
                "meta_2": f"Assembly: {context_assembly.name if context_assembly else 'All'}",
            },
        ],
    }
    return render(request, "billing/billing_management.html", context)
