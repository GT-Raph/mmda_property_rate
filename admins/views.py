import base64
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.contrib.sessions.models import Session
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.translation import gettext_lazy as _
from django_otp.plugins.otp_totp.models import TOTPDevice
from openpyxl import Workbook
from openpyxl.styles import Font

from admins.decorators import module_required
from admins.forms import (
    AssemblyEditForm,
    NotificationSettingsForm,
    PRMSPasswordChangeForm,
    ProfileSettingsForm,
    TotpVerifyForm,
)
from admins.models import AdminPreference, Assembly, LoginAudit, ReportRun, UserProfile
from billing.models import Bill, BillDispute
from field_operations.models import FieldVisit
from payments.models import Payment
from properties.models import Property

from .access import get_allowed_modules, get_user_role, landing_url_for_user


MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)


def _portal_access(user):
    return get_allowed_modules(user)


def _settings_url(tab="profile"):
    return f"{reverse('admins:settings')}?tab={tab}"


class PortalLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = AuthenticationForm
    redirect_authenticated_user = True

    selected_assembly_session_key = "selected_assembly_id"
    active_assembly_session_key = "active_assembly_id"
    active_assembly_name_session_key = "active_assembly_name"

    def get_selected_assembly(self):
        assembly_id = self.request.session.get(self.selected_assembly_session_key)
        if not assembly_id:
            return None

        try:
            return Assembly.objects.get(id=assembly_id, is_active=True)
        except Assembly.DoesNotExist:
            self.request.session.pop(self.selected_assembly_session_key, None)
            return None

    def get_available_assemblies(self):
        return Assembly.objects.filter(is_active=True).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_assembly = self.get_selected_assembly()

        context.update(
            {
                "assemblies": self.get_available_assemblies(),
                "selected_assembly": selected_assembly,
                "selected_assembly_id": self.request.POST.get("assembly_id", "")
                or self.request.session.get(self.selected_assembly_session_key, ""),
                "assembly_error": getattr(self, "assembly_error", ""),
            }
        )
        return context

    def get(self, request, *args, **kwargs):
        if "change_assembly" in request.GET:
            request.session.pop(self.selected_assembly_session_key, None)
            request.session.pop(self.active_assembly_session_key, None)
            request.session.pop(self.active_assembly_name_session_key, None)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        stage = request.POST.get("stage")

        if stage == "assembly":
            return self.handle_assembly_selection()

        if stage == "login":
            return self.handle_login()

        self.assembly_error = "Please select an assembly first."
        return self.render_to_response(self.get_context_data(form=self.get_form()))

    def handle_assembly_selection(self):
        assembly_id = self.request.POST.get("assembly_id", "").strip()

        if not assembly_id:
            self.assembly_error = "Please select an assembly."
            return self.render_to_response(self.get_context_data(form=self.get_form()))

        try:
            assembly = Assembly.objects.get(id=assembly_id, is_active=True)
        except Assembly.DoesNotExist:
            self.assembly_error = "Please select a valid assembly."
            return self.render_to_response(self.get_context_data(form=self.get_form()))

        self.request.session[self.selected_assembly_session_key] = assembly.id
        self.request.session.modified = True
        return redirect("portal-login")

    def handle_login(self):
        selected_assembly = self.get_selected_assembly()

        if not selected_assembly:
            self.assembly_error = "Please select an assembly before signing in."
            return self.render_to_response(self.get_context_data(form=self.get_form()))

        form = self.get_form()
        if not form.is_valid():
            return self.form_invalid(form)

        user = form.get_user()

        allowed, reason = self.user_can_access_selected_assembly(user, selected_assembly)
        if not allowed:
            form.add_error(None, reason)
            return self.form_invalid(form)

        self.request.session[self.active_assembly_session_key] = selected_assembly.id
        self.request.session[self.active_assembly_name_session_key] = selected_assembly.name
        self.request.session.modified = True

        return self.form_valid(form)

    def user_can_access_selected_assembly(self, user, assembly):
        if not user.is_active:
            return False, _("This account is inactive.")

        if user.is_superuser:
            return True, ""

        profile = getattr(user, "profile", None)
        if not profile:
            return False, _("This account has no user profile. Contact the administrator.")

        role = get_user_role(user)

        if role in ["sys_admin", "revenue_admin"]:
            return True, ""

        if not profile.assembly_id:
            return False, _("This account is not assigned to any assembly.")

        if profile.assembly_id != assembly.id:
            return (
                False,
                _("You are not authorized to access the selected assembly. Please choose your assigned assembly."),
            )

        return True, ""

    def form_valid(self, form):
        remember_me = self.request.POST.get("remember_me")

        if remember_me:
            self.request.session.set_expiry(1209600)
        else:
            self.request.session.set_expiry(0)

        messages.success(self.request, "Login successful.")
        return super().form_valid(form)

    def get_success_url(self):
        return landing_url_for_user(self.request.user)


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


def _display_report_date(dt):
    if not dt:
        return "Never"
    local_dt = timezone.localtime(dt)
    return f"{local_dt.strftime('%B')} {local_dt.day}, {local_dt.year}"


def _latest_report_run_map(assembly=None):
    runs = ReportRun.objects.order_by("report_key", "-created_at")
    if assembly:
        runs = runs.filter(generated_by__profile__assembly=assembly)

    latest_map = {}
    for run in runs:
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


def _monthly_revenue_report(assembly=None):
    rows_qs = Payment.objects.filter(status="successful", paid_at__isnull=False)

    if assembly:
        rows_qs = rows_qs.filter(assembly=assembly)

    rows_qs = (
        rows_qs.annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD)),
            transactions=Count("id"),
        )
        .order_by("month")
    )

    rows = []
    for row in rows_qs:
        rows.append(
            [
                row["month"].strftime("%B %Y") if row["month"] else "—",
                float(row["total"] or 0),
                row["transactions"],
            ]
        )

    return _build_workbook(
        "Monthly Revenue Report",
        ["Month", "Collected Amount (GHS)", "Transactions"],
        rows,
    ), len(rows)


def _property_registration_report(assembly=None):
    rows_qs = Property.objects.select_related("owner").order_by("-created_at")

    if assembly:
        rows_qs = rows_qs.filter(assembly=assembly)

    rows = []
    for prop in rows_qs:
        rows.append(
            [
                prop.property_reference,
                prop.owner.full_name,
                prop.get_property_use_display(),
                prop.get_building_type_display() if hasattr(prop, "get_building_type_display") else prop.building_type,
                prop.area_town or "",
                prop.suburb or "",
                float(prop.rateable_value or 0),
                getattr(prop, "verification_status", ""),
                timezone.localtime(prop.created_at).strftime("%Y-%m-%d %H:%M"),
            ]
        )

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


def _payment_trends_report(assembly=None):
    rows_qs = Payment.objects.select_related("property__owner").order_by("-paid_at", "-created_at")

    if assembly:
        rows_qs = rows_qs.filter(assembly=assembly)

    rows = []
    for payment in rows_qs:
        if payment.property_id:
            prop_ref = payment.property.property_reference
            owner = payment.property.owner.full_name
        else:
            prop_ref = payment.property_reference_entered or ""
            owner = payment.payer_name or ""

        rows.append(
            [
                payment.transaction_reference,
                prop_ref,
                owner,
                float(payment.amount or 0),
                payment.payment_method,
                payment.status,
                timezone.localtime(payment.paid_at).strftime("%Y-%m-%d %H:%M") if payment.paid_at else "",
            ]
        )

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


def _outstanding_bills_report(assembly=None):
    rows_qs = (
        Bill.objects.select_related("property_record__owner")
        .exclude(status__in=["paid", "cancelled"])
        .order_by("due_date", "-created_at")
    )

    if assembly:
        rows_qs = rows_qs.filter(assembly=assembly)

    rows = []
    for bill in rows_qs:
        balance = (bill.amount_due or Decimal("0.00")) - (bill.amount_paid or Decimal("0.00"))
        rows.append(
            [
                bill.bill_number,
                bill.property_record.property_reference,
                bill.property_record.owner.full_name,
                float(bill.amount_due or 0),
                float(bill.amount_paid or 0),
                float(balance or 0),
                bill.due_date.strftime("%Y-%m-%d") if bill.due_date else "",
                bill.status,
            ]
        )

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


def _dispute_resolution_report(assembly=None):
    rows_qs = (
        BillDispute.objects.select_related(
            "bill__property_record__owner",
            "raised_by",
            "reviewed_by",
        ).order_by("-created_at")
    )

    if assembly:
        rows_qs = rows_qs.filter(bill__assembly=assembly)

    rows = []
    for dispute in rows_qs:
        rows.append(
            [
                dispute.bill.bill_number,
                dispute.bill.property_record.property_reference,
                dispute.bill.property_record.owner.full_name,
                dispute.issue_type,
                dispute.status,
                getattr(dispute.raised_by, "username", ""),
                getattr(dispute.reviewed_by, "username", "") if getattr(dispute, "reviewed_by", None) else "",
                timezone.localtime(dispute.created_at).strftime("%Y-%m-%d %H:%M"),
            ]
        )

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


def _field_operations_report(assembly=None):
    rows_qs = (
        FieldVisit.objects.select_related("property__owner", "officer")
        .order_by("-visited_at", "-created_at")
    )

    if assembly:
        rows_qs = rows_qs.filter(property__assembly=assembly)

    rows = []
    for visit in rows_qs:
        officer_name = visit.officer.get_full_name().strip() or visit.officer.username
        rows.append(
            [
                visit.property.property_reference,
                visit.property.owner.full_name,
                visit.get_visit_type_display() if hasattr(visit, "get_visit_type_display") else visit.visit_type,
                visit.outcome,
                officer_name,
                timezone.localtime(visit.visited_at).strftime("%Y-%m-%d %H:%M") if visit.visited_at else "",
                visit.notes or "",
            ]
        )

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


def _download_report(request, report_key, assembly=None):
    config = REPORT_BUILDERS.get(report_key)
    if not config:
        raise Http404("Unknown report type.")

    workbook, row_count = config["builder"](assembly=assembly)

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


@module_required("dashboard")
def dashboard(request):
    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    current_year = today.year
    context_assembly = _get_current_assembly(request)

    properties_qs = Property.objects.select_related("owner")
    bills_qs = Bill.objects.select_related("assembly", "property_record", "rate_policy")
    payments_qs = Payment.objects.select_related("property__owner", "bill")
    field_visits_qs = FieldVisit.objects.select_related("property__owner", "officer")
    disputes_qs = BillDispute.objects.select_related(
        "bill__property_record__owner",
        "bill__assembly",
    )

    if context_assembly:
        properties_qs = properties_qs.filter(assembly=context_assembly)
        bills_qs = bills_qs.filter(assembly=context_assembly)
        payments_qs = payments_qs.filter(assembly=context_assembly)
        field_visits_qs = field_visits_qs.filter(property__assembly=context_assembly)
        disputes_qs = disputes_qs.filter(bill__assembly=context_assembly)

    balance_expr = ExpressionWrapper(
        F("amount_due") - F("amount_paid"),
        output_field=MONEY_FIELD,
    )

    total_properties = properties_qs.count()
    properties_this_month = properties_qs.filter(created_at__date__gte=current_month_start).count()
    properties_previous_month = properties_qs.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    ).count()

    bills_this_month = bills_qs.filter(created_at__date__gte=current_month_start).count()
    bills_previous_month = bills_qs.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    ).count()

    revenue_this_month = payments_qs.filter(
        status="successful",
        paid_at__date__gte=current_month_start,
    ).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    revenue_previous_month = payments_qs.filter(
        status="successful",
        paid_at__date__gte=previous_month_start,
        paid_at__date__lte=previous_month_end,
    ).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    open_bills = bills_qs.exclude(status__in=["paid", "cancelled"])

    outstanding_total = open_bills.aggregate(
        total=Coalesce(Sum(balance_expr), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    outstanding_previous = open_bills.filter(created_at__date__lt=current_month_start).aggregate(
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
            "meta": "vs last month",
            "change": abs(property_change),
            "change_prefix": "+" if property_change >= 0 else "-",
            "change_class": "green" if property_change >= 0 else "red",
            "icon_key": "property",
        },
        {
            "title": "Bills Generated",
            "value": _number(bills_this_month),
            "meta": "this month",
            "change": abs(bills_change),
            "change_prefix": "+" if bills_change >= 0 else "-",
            "change_class": "green" if bills_change >= 0 else "red",
            "icon_key": "bill",
        },
        {
            "title": "Revenue Collected",
            "value": _money(revenue_this_month),
            "meta": "this month",
            "change": abs(revenue_change),
            "change_prefix": "+" if revenue_change >= 0 else "-",
            "change_class": "green" if revenue_change >= 0 else "red",
            "icon_key": "paid",
        },
        {
            "title": "Outstanding",
            "value": _money(outstanding_total),
            "meta": "vs last month",
            "change": abs(outstanding_change),
            "change_prefix": "-" if outstanding_total <= outstanding_previous else "+",
            "change_class": "green" if outstanding_total <= outstanding_previous else "red",
            "icon_key": "alert",
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

    revenue_rows = (
        payments_qs.filter(
            status="successful",
            paid_at__date__gte=month_starts[0],
        )
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
        )
        .order_by("month")
    )

    month_totals = {}
    for row in revenue_rows:
        if row["month"]:
            month_totals[row["month"].date().replace(day=1)] = row["total"]

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

    current_year_bills = bills_qs.filter(billing_year=current_year)
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

    for payment in payments_qs.filter(status="successful").order_by("-paid_at", "-created_at")[:3]:
        dt = payment.paid_at or payment.created_at
        prop_ref = payment.property.property_reference if payment.property_id else payment.property_reference_entered or "Unknown Ref"
        owner_name = payment.property.owner.full_name if payment.property_id else payment.payer_name or "Unknown payer"

        recent_items.append(
            {
                "sort_at": dt,
                "icon_key": "paid",
                "icon_class": "soft-green",
                "title": f"Payment received: {_money(payment.amount)}",
                "subtitle": f"{prop_ref} • {owner_name}",
                "time": _time_ago(dt),
                "highlight": True,
            }
        )

    for prop in properties_qs.order_by("-created_at")[:2]:
        recent_items.append(
            {
                "sort_at": prop.created_at,
                "icon_key": "property",
                "icon_class": "soft-blue",
                "title": f"New property registered in {prop.area_town}",
                "subtitle": f"{prop.property_reference} • {prop.owner.full_name}",
                "time": _time_ago(prop.created_at),
                "highlight": False,
            }
        )

    for dispute in disputes_qs.order_by("-created_at")[:2]:
        recent_items.append(
            {
                "sort_at": dispute.created_at,
                "icon_key": "alert",
                "icon_class": "soft-yellow",
                "title": "Rate calculation dispute",
                "subtitle": (
                    f"{dispute.bill.property_record.property_reference} • "
                    f"{dispute.bill.property_record.owner.full_name}"
                ),
                "time": _time_ago(dispute.created_at),
                "highlight": False,
            }
        )

    for visit in field_visits_qs.order_by("-visited_at", "-created_at")[:2]:
        dt = visit.visited_at or visit.created_at
        recent_items.append(
            {
                "sort_at": dt,
                "icon_key": "field",
                "icon_class": "soft-blue",
                "title": visit.get_visit_type_display() if hasattr(visit, "get_visit_type_display") else "Field Visit",
                "subtitle": f"{visit.property.property_reference} • {visit.property.owner.full_name}",
                "time": _time_ago(dt),
                "highlight": False,
            }
        )

    recent_items = sorted(recent_items, key=lambda item: item["sort_at"], reverse=True)[:6]

    overdue_90_count = bills_qs.filter(
        due_date__lt=today - timedelta(days=90)
    ).exclude(status__in=["paid", "cancelled"]).count()

    next_month_start = (current_month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_until_next_cycle = (next_month_start - today).days

    weekly_field_visits = field_visits_qs.filter(visited_at__date__gte=week_start).count()

    alerts = [
        {
            "message": f"{_number(overdue_90_count)} properties have overdue payments (>90 days)",
            "action": "View List",
            "alert_class": "alert-warning",
        },
        {
            "message": f"Monthly billing cycle starts in {days_until_next_cycle} day{'s' if days_until_next_cycle != 1 else ''}",
            "action": "Prepare",
            "alert_class": "alert-info",
        },
        {
            "message": f"Field verification completed for {_number(weekly_field_visits)} properties",
            "action": "Review",
            "alert_class": "alert-success",
        },
    ]

    portal_access = _portal_access(request.user)

    context = {
        "page_title": "Dashboard",
        "page_subtitle": "Property Rate Management System Overview",
        "context_assembly": context_assembly,
        "summary_cards": summary_cards,
        "revenue_points": revenue_points,
        "revenue_max": float(revenue_max),
        "payment_distribution": payment_distribution,
        "distribution_total": distribution_total,
        "recent_activities": recent_items,
        "alerts": alerts,
        "user_role": get_user_role(request.user),
        "allowed_modules": portal_access,
        "portal_access": portal_access,
    }
    return render(request, "admins/dashboard.html", context)


@module_required("reports")
def reports_analytics(request):
    context_assembly = _get_current_assembly(request)

    if request.method == "POST":
        report_key = (request.POST.get("report_key") or "").strip()
        if not report_key:
            messages.error(request, "Please choose a report to generate.")
        else:
            return _download_report(request, report_key, assembly=context_assembly)

    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    week_start = today - timedelta(days=today.weekday())

    bills_qs = Bill.objects.select_related("assembly", "property_record", "rate_policy")
    payments_qs = Payment.objects.filter(status="successful", paid_at__isnull=False)

    if context_assembly:
        bills_qs = bills_qs.filter(assembly=context_assembly)
        payments_qs = payments_qs.filter(assembly=context_assembly)

    current_month_bills = bills_qs.filter(created_at__date__gte=current_month_start)
    previous_month_bills = bills_qs.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    )

    current_due = current_month_bills.aggregate(
        total=Coalesce(Sum("amount_due"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"] or Decimal("0.00")

    current_paid = current_month_bills.aggregate(
        total=Coalesce(Sum("amount_paid"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"] or Decimal("0.00")

    previous_due = previous_month_bills.aggregate(
        total=Coalesce(Sum("amount_due"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"] or Decimal("0.00")

    previous_paid = previous_month_bills.aggregate(
        total=Coalesce(Sum("amount_paid"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"] or Decimal("0.00")

    collection_rate = _percent(current_paid, current_due)
    previous_collection_rate = _percent(previous_paid, previous_due)

    bills_generated_this_month = current_month_bills.count()

    reports_run_qs = ReportRun.objects.all()
    if context_assembly:
        reports_run_qs = reports_run_qs.filter(generated_by__profile__assembly=context_assembly)

    reports_generated_this_week = reports_run_qs.filter(created_at__date__gte=week_start).count()

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
            "value": f"{bills_generated_this_month:,}",
            "meta": "this month",
        },
        {
            "icon": "⭳",
            "icon_class": "icon-gold",
            "title": "Reports Generated",
            "value": f"{reports_generated_this_week:,}",
            "meta": "this week",
        },
    ]

    month_starts = _month_range(6)

    collected_rows = (
        payments_qs.filter(paid_at__date__gte=month_starts[0])
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD)))
        .order_by("month")
    )

    target_rows = (
        bills_qs.filter(created_at__date__gte=month_starts[0])
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Coalesce(Sum("amount_due"), Value(Decimal("0.00"), output_field=MONEY_FIELD)))
        .order_by("month")
    )

    collected_map = {}
    for row in collected_rows:
        month_value = row["month"]
        if month_value:
            collected_map[month_value.date().replace(day=1)] = row["total"]

    target_map = {}
    for row in target_rows:
        month_value = row["month"]
        if month_value:
            target_map[month_value.date().replace(day=1)] = row["total"]

    max_value = Decimal("1.00")
    for month_start in month_starts:
        max_value = max(max_value, collected_map.get(month_start, Decimal("0.00")))
        max_value = max(max_value, target_map.get(month_start, Decimal("0.00")))

    chart_months = []
    for month_start in month_starts:
        collected = collected_map.get(month_start, Decimal("0.00"))
        target = target_map.get(month_start, Decimal("0.00"))

        collected_height = max(8, int((collected / max_value) * 240)) if collected > 0 else 8
        target_height = max(8, int((target / max_value) * 240)) if target > 0 else 8

        chart_months.append(
            {
                "label": month_start.strftime("%b"),
                "collected_display": f"GH₵ {collected:,.0f}",
                "target_display": f"GH₵ {target:,.0f}",
                "collected_height": collected_height,
                "target_height": target_height,
            }
        )

    latest_runs = _latest_report_run_map(context_assembly)
    reports = []
    for key, config in REPORT_BUILDERS.items():
        latest_run = latest_runs.get(key)
        reports.append(
            {
                "key": key,
                "title": config["title"],
                "description": config["description"],
                "generated": _display_report_date(latest_run.created_at) if latest_run else "Never",
                "format": config["format"],
            }
        )

    portal_access = _portal_access(request.user)

    context = {
        "page_title": "Reports & Analytics",
        "page_subtitle": "Generate and export system reports",
        "context_assembly": context_assembly,
        "stats": stats,
        "chart_months": chart_months,
        "reports": reports,
        "portal_access": portal_access,
        "allowed_modules": portal_access,
    }
    return render(request, "admins/reports_analytics.html", context)


@module_required("assembly")
def assembly_management(request):
    assembly = _get_current_assembly(request)

    if not assembly:
        return redirect("portal-login")

    show_edit_modal = request.GET.get("edit") == "1"

    if request.method == "POST" and request.POST.get("action") == "update_assembly":
        form = AssemblyEditForm(request.POST, instance=assembly)
        show_edit_modal = True

        if form.is_valid():
            form.save()
            messages.success(request, "Assembly information updated successfully.")
            return redirect("admins:assembly-management")
        else:
            messages.error(request, "Please correct the errors below and try again.")
    else:
        form = AssemblyEditForm(instance=assembly)

    total_properties = Property.objects.filter(assembly=assembly).count()
    total_bills = Bill.objects.filter(assembly=assembly).count()
    field_officers = UserProfile.objects.filter(assembly=assembly, role="field_officer").count()
    total_users = UserProfile.objects.filter(assembly=assembly).count()

    portal_access = _portal_access(request.user)

    context = {
        "page_title": "Assembly Management",
        "page_subtitle": "Manage your assembly information and settings",
        "assembly": assembly,
        "assembly_status": "Active" if assembly.is_active else "Inactive",
        "assembly_status_class": "status-active" if assembly.is_active else "status-inactive",
        "registration_date": assembly.created_at.strftime("%Y-%m-%d") if getattr(assembly, "created_at", None) else "—",
        "stats": [
            {"label": "Total Properties", "value": f"{total_properties:,}"},
            {"label": "Total Bills", "value": f"{total_bills:,}"},
            {"label": "Field Officers", "value": f"{field_officers:,}"},
            {"label": "Total Users", "value": f"{total_users:,}"},
        ],
        "form": form,
        "show_edit_modal": show_edit_modal,
        "portal_access": portal_access,
        "allowed_modules": portal_access,
    }
    return render(request, "admins/assembly_management.html", context)


def _settings_base_context(request, active_tab="profile", show_2fa_setup=False, verify_form=None):
    profile = getattr(request.user, "profile", None)
    preferences, _ = AdminPreference.objects.get_or_create(user=request.user)

    profile_form = ProfileSettingsForm(user=request.user, profile=profile)
    notification_form = NotificationSettingsForm(instance=preferences)
    password_form = PRMSPasswordChangeForm(request.user)

    totp_device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    pending_device = TOTPDevice.objects.filter(user=request.user, confirmed=False, name="prms").first()

    active_sessions = LoginAudit.objects.filter(
        user=request.user,
        is_active=True,
    ).order_by("-last_seen")[:10]

    portal_access = _portal_access(request.user)

    return {
        "page_title": "Settings",
        "page_subtitle": "Manage your account settings and preferences",
        "active_tab": active_tab,
        "profile_form": profile_form,
        "notification_form": notification_form,
        "password_form": password_form,
        "verify_form": verify_form or TotpVerifyForm(),
        "preferences": preferences,
        "profile_data": {
            "full_name": request.user.get_full_name().strip() or request.user.username,
            "email": request.user.email or "",
            "phone": profile.phone_number if profile else "",
            "role": profile.get_role_display() if profile else "User",
        },
        "two_factor_enabled": bool(totp_device),
        "pending_device": pending_device,
        "show_2fa_setup": show_2fa_setup,
        "active_sessions": active_sessions,
        "portal_access": portal_access,
        "allowed_modules": portal_access,
    }


def _make_qr_data_uri(text):
    qr = qrcode.make(text)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


@module_required("settings")
def settings_view(request):
    active_tab = request.GET.get("tab", "profile")
    profile = getattr(request.user, "profile", None)
    preferences, _ = AdminPreference.objects.get_or_create(user=request.user)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "save_profile":
            form = ProfileSettingsForm(request.POST, user=request.user, profile=profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect(_settings_url("profile"))

            context = _settings_base_context(request, active_tab="profile")
            context["profile_form"] = form
            return render(request, "admins/settings.html", context)

        if action == "change_password":
            form = PRMSPasswordChangeForm(request.user, request.POST)
            if form.is_valid():
                user = form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated successfully.")
                return redirect(_settings_url("password"))

            context = _settings_base_context(request, active_tab="password")
            context["password_form"] = form
            return render(request, "admins/settings.html", context)

        if action == "save_notifications":
            form = NotificationSettingsForm(request.POST, instance=preferences)
            if form.is_valid():
                form.save()
                messages.success(request, "Notification preferences saved.")
                return redirect(_settings_url("notifications"))

            context = _settings_base_context(request, active_tab="notifications")
            context["notification_form"] = form
            return render(request, "admins/settings.html", context)

    context = _settings_base_context(request, active_tab=active_tab)
    return render(request, "admins/settings.html", context)


@module_required("settings")
def begin_2fa_setup(request):
    if request.method != "POST":
        return redirect(_settings_url("security"))

    TOTPDevice.objects.filter(user=request.user, confirmed=False, name="prms").delete()
    device = TOTPDevice.objects.create(user=request.user, name="prms", confirmed=False)

    context = _settings_base_context(
        request,
        active_tab="security",
        show_2fa_setup=True,
        verify_form=TotpVerifyForm(),
    )
    context["pending_device"] = device
    context["qr_code_data_uri"] = _make_qr_data_uri(device.config_url)
    context["manual_key"] = device.bin_key

    messages.info(
        request,
        "Scan the QR code with your authenticator app, then enter the 6-digit code.",
    )
    return render(request, "admins/settings.html", context)


@module_required("settings")
def confirm_2fa_setup(request):
    if request.method != "POST":
        return redirect(_settings_url("security"))

    device = TOTPDevice.objects.filter(
        user=request.user,
        confirmed=False,
        name="prms",
    ).first()

    if not device:
        messages.error(request, "No pending 2FA setup found.")
        return redirect(_settings_url("security"))

    form = TotpVerifyForm(request.POST)
    if form.is_valid():
        token = form.cleaned_data["token"]
        if device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            messages.success(request, "Two-factor authentication enabled successfully.")
            return redirect(_settings_url("security"))

    context = _settings_base_context(
        request,
        active_tab="security",
        show_2fa_setup=True,
        verify_form=form,
    )
    context["pending_device"] = device
    context["qr_code_data_uri"] = _make_qr_data_uri(device.config_url)
    context["manual_key"] = device.bin_key
    messages.error(request, "Invalid verification code. Please try again.")
    return render(request, "admins/settings.html", context)


@module_required("settings")
def disable_2fa(request):
    if request.method == "POST":
        TOTPDevice.objects.filter(user=request.user, name="prms").delete()
        messages.success(request, "Two-factor authentication disabled.")
    return redirect(_settings_url("security"))


@module_required("settings")
def revoke_session(request, audit_id):
    audit = get_object_or_404(LoginAudit, id=audit_id, user=request.user)

    if request.method == "POST":
        Session.objects.filter(session_key=audit.session_key).delete()
        audit.is_active = False
        audit.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Session revoked successfully.")

    return redirect(_settings_url("security"))