from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from django.contrib.auth.views import LoginView
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.timesince import timesince
from openpyxl import Workbook
from openpyxl.styles import Font

from admins.decorators import module_required
from admins.models import ReportRun
from billing.models import Bill, BillDispute
from field_operations.models import FieldVisit
from payments.models import Payment
from properties.models import Property

from .access import get_allowed_modules, get_user_role, landing_url_for_user


MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)


class PortalLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        remember_me = self.request.POST.get("remember_me")

        if remember_me:
            self.request.session.set_expiry(1209600)  # 2 weeks
        else:
            self.request.session.set_expiry(0)  # browser session only

        return super().form_valid(form)

    def get_success_url(self):
        return landing_url_for_user(self.request.user)
    

def _money(value):
    value = value or Decimal("0.00")
    return f"GH₵ {Decimal(value):,.0f}"


def _number(value):
    return f"{int(value or 0):,}"


def _percent(numerator, denominator):
    numerator = Decimal(numerator or 0)
    denominator = Decimal(denominator or 0)

    if denominator <= 0:
        return Decimal("0.0")

    return round((numerator / denominator) * 100, 1)
    

def _pct_change(current, previous):
    current = float(current or 0)
    previous = float(previous or 0)

    if previous == 0:
        return 100.0 if current > 0 else 0.0

    return round(((current - previous) / previous) * 100, 1)


def _time_ago(dt):
    if not dt:
        return "just now"
    return f"{timesince(dt, timezone.now()).split(',')[0]} ago"


@module_required("dashboard")
def dashboard(request):
    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    current_year = today.year

    balance_expr = ExpressionWrapper(
        F("amount_due") - F("amount_paid"),
        output_field=MONEY_FIELD,
    )

    total_properties = Property.objects.count()
    properties_this_month = Property.objects.filter(
        created_at__date__gte=current_month_start
    ).count()
    properties_previous_month = Property.objects.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    ).count()

    bills_this_month = Bill.objects.filter(
        created_at__date__gte=current_month_start
    ).count()
    bills_previous_month = Bill.objects.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    ).count()

    revenue_this_month = Payment.objects.filter(
        status="successful",
        paid_at__date__gte=current_month_start,
    ).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    revenue_previous_month = Payment.objects.filter(
        status="successful",
        paid_at__date__gte=previous_month_start,
        paid_at__date__lte=previous_month_end,
    ).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    open_bills = Bill.objects.exclude(status__in=["paid", "cancelled"])

    outstanding_total = open_bills.aggregate(
        total=Coalesce(Sum(balance_expr), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    outstanding_previous = open_bills.filter(
        created_at__date__lt=current_month_start
    ).aggregate(
        total=Coalesce(Sum(balance_expr), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    property_change = _pct_change(properties_this_month, properties_previous_month)
    bills_change = _pct_change(bills_this_month, bills_previous_month)
    revenue_change = _pct_change(revenue_this_month, revenue_previous_month)
    outstanding_change = _pct_change(outstanding_total, outstanding_previous)

    summary_cards = [
        {
            "title": "Total Properties",
            "value": _number(total_properties),
            "meta": f"{_number(properties_this_month)} added this month",
            "change": abs(property_change),
            "change_symbol": "↗" if property_change >= 0 else "↘",
            "change_class": "green" if property_change >= 0 else "red",
            "icon": "🏢",
            "icon_class": "soft-green",
        },
        {
            "title": "Bills Generated",
            "value": _number(bills_this_month),
            "meta": "this month",
            "change": abs(bills_change),
            "change_symbol": "↗" if bills_change >= 0 else "↘",
            "change_class": "green" if bills_change >= 0 else "red",
            "icon": "📄",
            "icon_class": "soft-blue",
        },
        {
            "title": "Revenue Collected",
            "value": _money(revenue_this_month),
            "meta": "this month",
            "change": abs(revenue_change),
            "change_symbol": "↗" if revenue_change >= 0 else "↘",
            "change_class": "green" if revenue_change >= 0 else "red",
            "icon": "💲",
            "icon_class": "soft-green",
        },
        {
            "title": "Outstanding",
            "value": _money(outstanding_total),
            "meta": f"{_number(open_bills.count())} open bills",
            "change": abs(outstanding_change),
            "change_symbol": "↗" if outstanding_total > outstanding_previous else "↘",
            "change_class": "red" if outstanding_total > outstanding_previous else "green",
            "icon": "⚠️",
            "icon_class": "soft-yellow",
        },
    ]

    month_starts = []
    for offset in range(5, -1, -1):
        month = current_month_start.month - offset
        year = current_month_start.year
        while month <= 0:
            month += 12
            year -= 1
        month_starts.append(date(year, month, 1))

    revenue_rows = Payment.objects.filter(
        status="successful",
        paid_at__date__gte=month_starts[0],
    ).annotate(
        month=TruncMonth("paid_at")
    ).values("month").annotate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    ).order_by("month")

    month_totals = {}
    for row in revenue_rows:
        month_key = row["month"].date().replace(day=1)
        month_totals[month_key] = row["total"]

    revenue_points = []
    revenue_max = Decimal("1.00")

    for month_start in month_starts:
        total = month_totals.get(month_start, Decimal("0.00"))
        revenue_points.append(
            {
                "label": month_start.strftime("%b"),
                "value": float(total),
                "display": _money(total),
            }
        )
        if total > revenue_max:
            revenue_max = total

    current_year_bills = Bill.objects.filter(billing_year=current_year)
    paid_count = current_year_bills.filter(status="paid").count()
    partial_count = current_year_bills.filter(status="part_paid").count()
    unpaid_count = current_year_bills.filter(status__in=["pending", "overdue"]).count()
    distribution_total = max(paid_count + partial_count + unpaid_count, 1)

    payment_distribution = [
        {"label": "Paid", "count": paid_count, "display": _number(paid_count), "class": "green"},
        {"label": "Partial", "count": partial_count, "display": _number(partial_count), "class": "yellow"},
        {"label": "Unpaid", "count": unpaid_count, "display": _number(unpaid_count), "class": "red"},
    ]

    recent_items = []

    for payment in Payment.objects.filter(status="successful").select_related(
        "property__owner"
    ).order_by("-paid_at", "-created_at")[:3]:
        dt = payment.paid_at or payment.created_at
        prop_ref = (
            payment.property.property_reference
            if payment.property_id
            else payment.property_reference_entered or "Unknown Ref"
        )
        owner_name = (
            payment.property.owner.full_name
            if payment.property_id
            else payment.payer_name or "Unknown payer"
        )
        recent_items.append(
            {
                "sort_at": dt,
                "icon": "💲",
                "icon_class": "soft-green",
                "title": f"Payment received: {_money(payment.amount)}",
                "subtitle": f"{prop_ref} • {owner_name}",
                "time": _time_ago(dt),
                "highlight": True,
            }
        )

    for prop in Property.objects.select_related("owner").order_by("-created_at")[:2]:
        recent_items.append(
            {
                "sort_at": prop.created_at,
                "icon": "🏢",
                "icon_class": "soft-blue",
                "title": f"New property registered in {prop.area_town}",
                "subtitle": f"{prop.property_reference} • {prop.owner.full_name}",
                "time": _time_ago(prop.created_at),
                "highlight": False,
            }
        )

    for dispute in BillDispute.objects.select_related(
        "bill__property_record__owner"
    ).order_by("-created_at")[:2]:
        recent_items.append(
            {
                "sort_at": dispute.created_at,
                "icon": "⚠️",
                "icon_class": "soft-yellow",
                "title": "Rate dispute submitted",
                "subtitle": (
                    f"{dispute.bill.property_record.property_reference} • "
                    f"{dispute.bill.property_record.owner.full_name}"
                ),
                "time": _time_ago(dispute.created_at),
                "highlight": False,
            }
        )

    for visit in FieldVisit.objects.select_related(
        "property__owner"
    ).order_by("-visited_at")[:2]:
        recent_items.append(
            {
                "sort_at": visit.visited_at,
                "icon": "📍",
                "icon_class": "soft-blue",
                "title": visit.get_visit_type_display(),
                "subtitle": (
                    f"{visit.property.property_reference} • "
                    f"{visit.property.owner.full_name}"
                ),
                "time": _time_ago(visit.visited_at),
                "highlight": False,
            }
        )

    recent_items = sorted(recent_items, key=lambda item: item["sort_at"], reverse=True)[:6]

    overdue_90_count = Bill.objects.filter(
        due_date__lt=today - timedelta(days=90)
    ).exclude(status__in=["paid", "cancelled"]).count()

    next_month_start = (current_month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_until_next_cycle = (next_month_start - today).days

    weekly_field_visits = FieldVisit.objects.filter(
        visited_at__date__gte=week_start
    ).count()

    alerts = [
        {
            "message": f"{_number(overdue_90_count)} properties have overdue payments (>90 days)",
            "action": "View overdue list",
            "alert_class": "alert-warning",
        },
        {
            "message": f"Monthly billing cycle starts in {days_until_next_cycle} day{'s' if days_until_next_cycle != 1 else ''}",
            "action": "Prepare billing",
            "alert_class": "alert-info",
        },
        {
            "message": f"Field verification completed for {_number(weekly_field_visits)} properties this week",
            "action": "Review field activity",
            "alert_class": "alert-success",
        },
    ]

    context = {
        "page_title": "Dashboard",
    "page_subtitle": "Property Rate Management System Overview",
    "summary_cards": summary_cards,
    "revenue_points": revenue_points,
    "revenue_max": float(revenue_max),
    "payment_distribution": payment_distribution,
    "distribution_total": distribution_total,
    "recent_activities": recent_items,
    "alerts": alerts,
    "user_role": get_user_role(request.user),
    "allowed_modules": get_allowed_modules(request.user),
    }
    return render(request, "admins/dashboard.html", context)


def _month_range(month_count=6):
    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    months = []

    for offset in range(month_count - 1, -1, -1):
        month = current_month_start.month - offset
        year = current_month_start.year
        while month <= 0:
            month += 12
            year -= 1
        months.append(date(year, month, 1))

    return months


def _latest_report_run_map():
    latest_map = {}
    for run in ReportRun.objects.order_by("report_key", "-created_at"):
        if run.report_key not in latest_map:
            latest_map[run.report_key] = run
    return latest_map


def _auto_size_worksheet(ws):
    for column_cells in ws.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            if len(value) > max_length:
                max_length = len(value)
        ws.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 40)


def _build_workbook(title, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"

    ws.append([title])
    ws.append([])
    ws.append(headers)

    for cell in ws[1]:
        cell.font = Font(bold=True, size=14)

    for cell in ws[3]:
        cell.font = Font(bold=True)

    for row in rows:
        ws.append(row)

    _auto_size_worksheet(ws)
    return wb


def _monthly_revenue_report():
    rows_qs = (
        Payment.objects.filter(status="successful", paid_at__isnull=False)
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD)),
            transactions=Count("id"),
        )
        .order_by("month")
    )

    rows = []
    for row in rows_qs:
        rows.append([
            row["month"].strftime("%B %Y") if row["month"] else "—",
            float(row["total"] or 0),
            row["transactions"],
        ])

    return _build_workbook(
        "Monthly Revenue Report",
        ["Month", "Collected Amount (GHS)", "Transactions"],
        rows,
    ), len(rows)


def _property_registration_report():
    rows_qs = Property.objects.select_related("owner").order_by("-created_at")

    rows = []
    for prop in rows_qs:
        rows.append([
            prop.property_reference,
            prop.owner.full_name,
            prop.get_property_use_display(),
            prop.get_building_type_display() if hasattr(prop, "get_building_type_display") else prop.building_type,
            prop.area_town or "",
            prop.suburb or "",
            float(prop.rateable_value or 0),
            prop.verification_status,
            timezone.localtime(prop.created_at).strftime("%Y-%m-%d %H:%M"),
        ])

    return _build_workbook(
        "Property Registration Summary",
        [
            "Property Ref",
            "Owner",
            "Property Use",
            "Building Type",
            "Area/Town",
            "Suburb",
            "Rateable Value (GHS)",
            "Verification Status",
            "Registered At",
        ],
        rows,
    ), len(rows)


def _payment_trends_report():
    rows_qs = Payment.objects.select_related("property__owner").order_by("-paid_at", "-created_at")

    rows = []
    for payment in rows_qs:
        if payment.property_id:
            prop_ref = payment.property.property_reference
            owner = payment.property.owner.full_name
        else:
            prop_ref = payment.property_reference_entered or ""
            owner = payment.payer_name or ""

        rows.append([
            payment.transaction_reference,
            prop_ref,
            owner,
            float(payment.amount or 0),
            payment.payment_method,
            payment.status,
            timezone.localtime(payment.paid_at).strftime("%Y-%m-%d %H:%M") if payment.paid_at else "",
        ])

    return _build_workbook(
        "Payment Collection Trends",
        [
            "Transaction Ref",
            "Property Ref",
            "Owner/Payer",
            "Amount (GHS)",
            "Method",
            "Status",
            "Paid At",
        ],
        rows,
    ), len(rows)


def _outstanding_bills_report():
    rows_qs = (
        Bill.objects.select_related("property_record__owner")
        .exclude(status__in=["paid", "cancelled"])
        .order_by("due_date", "-created_at")
    )

    rows = []
    for bill in rows_qs:
        balance = (bill.amount_due or Decimal("0.00")) - (bill.amount_paid or Decimal("0.00"))
        rows.append([
            bill.bill_number,
            bill.property_record.property_reference,
            bill.property_record.owner.full_name,
            float(bill.amount_due or 0),
            float(bill.amount_paid or 0),
            float(balance or 0),
            bill.due_date.strftime("%Y-%m-%d") if bill.due_date else "",
            bill.status,
        ])

    return _build_workbook(
        "Outstanding Bills Report",
        [
            "Bill No",
            "Property Ref",
            "Owner",
            "Amount Due (GHS)",
            "Amount Paid (GHS)",
            "Balance (GHS)",
            "Due Date",
            "Status",
        ],
        rows,
    ), len(rows)


def _dispute_resolution_report():
    rows_qs = (
        BillDispute.objects.select_related("bill__property_record__owner", "raised_by", "reviewed_by")
        .order_by("-created_at")
    )

    rows = []
    for dispute in rows_qs:
        rows.append([
            dispute.bill.bill_number,
            dispute.bill.property_record.property_reference,
            dispute.bill.property_record.owner.full_name,
            dispute.issue_type,
            dispute.status,
            getattr(dispute.raised_by, "username", ""),
            getattr(dispute.reviewed_by, "username", "") if dispute.reviewed_by else "",
            timezone.localtime(dispute.created_at).strftime("%Y-%m-%d %H:%M"),
        ])

    return _build_workbook(
        "Dispute Resolution Summary",
        [
            "Bill No",
            "Property Ref",
            "Owner",
            "Issue Type",
            "Status",
            "Raised By",
            "Reviewed By",
            "Created At",
        ],
        rows,
    ), len(rows)


def _field_operations_report():
    rows_qs = (
        FieldVisit.objects.select_related("property__owner", "officer")
        .order_by("-visited_at", "-created_at")
    )

    rows = []
    for visit in rows_qs:
        officer_name = visit.officer.get_full_name().strip() or visit.officer.username
        rows.append([
            visit.property.property_reference,
            visit.property.owner.full_name,
            visit.get_visit_type_display() if hasattr(visit, "get_visit_type_display") else visit.visit_type,
            visit.outcome,
            officer_name,
            timezone.localtime(visit.visited_at).strftime("%Y-%m-%d %H:%M") if visit.visited_at else "",
            visit.notes or "",
        ])

    return _build_workbook(
        "Field Operations Report",
        [
            "Property Ref",
            "Owner",
            "Visit Type",
            "Outcome",
            "Officer",
            "Visited At",
            "Notes",
        ],
        rows,
    ), len(rows)


REPORT_BUILDERS = {
    "monthly_revenue": {
        "title": "Monthly Revenue Report",
        "description": "Comprehensive revenue collection summary for the month",
        "format": "Excel (.xlsx)",
        "builder": _monthly_revenue_report,
    },
    "property_registration": {
        "title": "Property Registration Summary",
        "description": "New properties registered and verification status",
        "format": "Excel (.xlsx)",
        "builder": _property_registration_report,
    },
    "payment_trends": {
        "title": "Payment Collection Trends",
        "description": "Analysis of payment patterns and collection efficiency",
        "format": "Excel (.xlsx)",
        "builder": _payment_trends_report,
    },
    "outstanding_bills": {
        "title": "Outstanding Bills Report",
        "description": "Properties with overdue payments and follow-up actions",
        "format": "Excel (.xlsx)",
        "builder": _outstanding_bills_report,
    },
    "dispute_resolution": {
        "title": "Dispute Resolution Summary",
        "description": "Status of disputes, resolution rate, and common issues",
        "format": "Excel (.xlsx)",
        "builder": _dispute_resolution_report,
    },
    "field_operations": {
        "title": "Field Operations Report",
        "description": "Field officer activities, verifications, and productivity",
        "format": "Excel (.xlsx)",
        "builder": _field_operations_report,
    },
}


def _download_report(request, report_key):
    config = REPORT_BUILDERS.get(report_key)
    if not config:
        raise Http404("Unknown report type.")

    workbook, row_count = config["builder"]()

    ReportRun.objects.create(
        report_key=report_key,
        generated_by=request.user,
        file_format="xlsx",
        rows_count=row_count,
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    filename = f"{report_key}_{timezone.localdate().isoformat()}.xlsx"
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@module_required("reports")
def reports_analytics(request):
    if request.method == "POST":
        report_key = request.POST.get("report_key", "").strip()
        return _download_report(request, report_key)

    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    week_start = today - timedelta(days=today.weekday())

    current_month_bills = Bill.objects.filter(
        created_at__date__gte=current_month_start
    )
    previous_month_bills = Bill.objects.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    )

    current_due = current_month_bills.aggregate(
        total=Coalesce(Sum("amount_due"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]
    current_paid = current_month_bills.aggregate(
        total=Coalesce(Sum("amount_paid"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    previous_due = previous_month_bills.aggregate(
        total=Coalesce(Sum("amount_due"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]
    previous_paid = previous_month_bills.aggregate(
        total=Coalesce(Sum("amount_paid"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    collection_rate = _percent(current_paid, current_due)
    previous_collection_rate = _percent(previous_paid, previous_due)

    bills_generated_this_month = current_month_bills.count()
    reports_generated_this_week = ReportRun.objects.filter(
        created_at__date__gte=week_start
    ).count()

    stats = [
        {
            "icon": "↗",
            "icon_class": "icon-green",
            "title": "Collection Rate",
            "value": f"{collection_rate}%",
            "meta": f"vs {previous_collection_rate}% last month",
        },
        {
            "icon": "📄",
            "icon_class": "icon-blue",
            "title": "Bills Generated",
            "value": _number(bills_generated_this_month),
            "meta": "this month",
        },
        {
            "icon": "⭳",
            "icon_class": "icon-green",
            "title": "Reports Generated",
            "value": _number(reports_generated_this_week),
            "meta": "this week",
        },
    ]

    month_starts = _month_range(6)

    collected_rows = (
        Payment.objects.filter(
            status="successful",
            paid_at__date__gte=month_starts[0],
        )
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD)))
        .order_by("month")
    )

    target_rows = (
        Bill.objects.filter(
            created_at__date__gte=month_starts[0],
        )
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Coalesce(Sum("amount_due"), Value(Decimal("0.00"), output_field=MONEY_FIELD)))
        .order_by("month")
    )

    collected_map = {}
    for row in collected_rows:
        collected_map[row["month"].date().replace(day=1)] = row["total"]

    target_map = {}
    for row in target_rows:
        target_map[row["month"].date().replace(day=1)] = row["total"]

    max_value = Decimal("1.00")
    for month_start in month_starts:
        max_value = max(max_value, collected_map.get(month_start, Decimal("0.00")))
        max_value = max(max_value, target_map.get(month_start, Decimal("0.00")))

    chart_months = []
    for month_start in month_starts:
        collected = collected_map.get(month_start, Decimal("0.00"))
        target = target_map.get(month_start, Decimal("0.00"))

        collected_height = max(8, int((collected / max_value) * 180)) if collected > 0 else 8
        target_height = max(8, int((target / max_value) * 180)) if target > 0 else 8

        chart_months.append(
            {
                "label": month_start.strftime("%b"),
                "collected_display": _money(collected),
                "target_display": _money(target),
                "collected_height": collected_height,
                "target_height": target_height,
            }
        )

    latest_runs = _latest_report_run_map()

    reports = []
    for key, config in REPORT_BUILDERS.items():
        latest_run = latest_runs.get(key)
        generated = (
            timezone.localtime(latest_run.created_at).strftime("%B %d, %Y")
            if latest_run
            else "Never"
        )

        reports.append(
            {
                "key": key,
                "title": config["title"],
                "description": config["description"],
                "generated": generated,
                "format": config["format"],
            }
        )

    context = {
        "page_title": "Reports & Analytics",
        "page_subtitle": "Generate and export system reports",
        "stats": stats,
        "chart_months": chart_months,
        "reports": reports,
    }
    return render(request, "admins/reports_analytics.html", context)


@module_required("settings")
def settings_view(request):
    active_tab = request.GET.get("tab", "profile")

    context = {
        "page_title": "Settings",
        "page_subtitle": "Manage your account settings and preferences",
        "active_tab": active_tab,
        "profile_data": {
            "full_name": request.user.get_full_name() or "Super Admin",
            "email": request.user.email or "admin@mmda.gov.gh",
            "phone": "0244123456",
            "role": "Super Admin",
        },
        "notifications": [
            {
                "title": "Email Notifications",
                "description": "Receive email updates about system activity",
                "enabled": True,
            },
            {
                "title": "Payment Alerts",
                "description": "Get notified when payments are received",
                "enabled": True,
            },
            {
                "title": "Dispute Alerts",
                "description": "Notifications for new disputes and resolutions",
                "enabled": True,
            },
            {
                "title": "System Updates",
                "description": "Updates about new features and maintenance",
                "enabled": False,
            },
        ],
        "sessions": [
            {
                "device": "Windows PC - Chrome",
                "meta": "Current session • Accra, Ghana",
                "status": "Active",
            }
        ],
    }
    return render(request, "admins/settings.html", context)