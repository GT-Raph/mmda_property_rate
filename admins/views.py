import base64
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import profile
from django import forms

import qrcode
from django import forms
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import (
    login_required,
)
from django.utils.http import (
    url_has_allowed_host_and_scheme,
)
from django.views.decorators.http import (
    require_POST,
)
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import (
    Coalesce,
    ExtractMonth,
    ExtractQuarter,
    ExtractYear,
    TruncMonth,
)
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
from admins.models import (
    AdminPreference,
    Assembly,
    LoginAudit,
    ReportRun,
    UserNotification,
    UserProfile,
)
from billing.models import Bill, BillDispute
from field_operations.models import FieldVisit
from payments.models import Payment
from properties.models import Owner, Property
from properties.utils import normalize_phone

from .access import get_allowed_modules, get_user_role, landing_url_for_user


MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)
User = get_user_model()


def _phone_lookup_values(phone_number):
    normalized_phone = normalize_phone(phone_number)

    if not normalized_phone:
        return []

    lookup_values = {normalized_phone}

    if normalized_phone.startswith("233") and len(normalized_phone) > 3:
        lookup_values.add(f"0{normalized_phone[3:]}")

    return list(lookup_values)


def _find_citizen_user_by_phone(phone_number):
    phone_lookup_values = _phone_lookup_values(phone_number)

    if not phone_lookup_values:
        return None

    matched_users = []

    profile_matches = (
        User.objects.filter(
            is_active=True,
            profile__role="citizen",
            profile__phone_number__in=phone_lookup_values,
        )
        .select_related("profile")
        .distinct()
    )

    matched_users.extend(profile_matches)

    owner_matches = (
        User.objects.filter(
            is_active=True,
            profile__role="citizen",
        )
        .filter(
            Q(owner_records__primary_phone__in=phone_lookup_values)
            | Q(owner_records__alternate_phone__in=phone_lookup_values)
        )
        .select_related("profile")
        .distinct()
    )

    matched_users.extend(owner_matches)

    unique_users = {
        user.id: user
        for user in matched_users
        if user and user.is_active
    }

    if len(unique_users) == 1:
        return list(unique_users.values())[0]

    return None

def _find_admin_user_by_identifier(identifier):
    identifier = (identifier or "").strip()

    if not identifier:
        return None

    user = User.objects.filter(username__iexact=identifier, is_active=True).first()
    if user:
        return user

    user = User.objects.filter(email__iexact=identifier, is_active=True).first()
    if user:
        return user

    return None


def _set_citizen_active_assembly(request, user):
    profile = getattr(user, "profile", None)

    if profile and profile.assembly_id:
        request.session["active_assembly_id"] = profile.assembly_id
        request.session["active_assembly_name"] = profile.assembly.name
        request.session.modified = True
        return

    owner = (
        Owner.objects
        .filter(linked_user=user, assembly__is_active=True)
        .select_related("assembly")
        .order_by("id")
        .first()
    )

    if owner and owner.assembly_id:
        request.session["active_assembly_id"] = owner.assembly_id
        request.session["active_assembly_name"] = owner.assembly.name
        request.session.modified = True


class AdminAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email Address or Username",
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "autocomplete": "username",
            }
        ),
    )

    def clean(self):
        identifier = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if identifier and password:
            user = _find_admin_user_by_identifier(identifier)

            if user is None:
                raise forms.ValidationError(
                    _("Please enter a correct username/email and password."),
                    code="invalid_login",
                )

            if get_user_role(user) == "citizen":
                raise forms.ValidationError(
                    _("Property owners must use the owner login page."),
                    code="invalid_login",
                )

            if not user.check_password(password):
                raise forms.ValidationError(
                    _("Please enter a correct username/email and password."),
                    code="invalid_login",
                )

            self.confirm_login_allowed(user)
            self.user_cache = user

        return self.cleaned_data


class CitizenPhoneAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Phone Number",
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "autocomplete": "tel",
                "inputmode": "tel",
            }
        ),
    )

    def clean(self):
        phone_number = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if phone_number and password:
            user = _find_citizen_user_by_phone(phone_number)

            if user is None:
                raise forms.ValidationError(
                    _("No active property owner account was found for this phone number."),
                    code="invalid_login",
                )

            if get_user_role(user) != "citizen":
                raise forms.ValidationError(
                    _("This login page is only for property owners."),
                    code="invalid_login",
                )

            if not user.check_password(password):
                raise forms.ValidationError(
                    _("Please enter the correct phone number and password."),
                    code="invalid_login",
                )

            self.confirm_login_allowed(user)
            self.user_cache = user

        return self.cleaned_data


class PortalAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label=_("Phone Number"),
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "autocomplete": "tel",
                "inputmode": "tel",
            }
        ),
    )

    error_messages = {
        "invalid_login": _(
            "Please enter a correct phone number and password. "
            "For citizen accounts, use the phone number linked to your owner record."
        ),
        "inactive": _("This account is inactive."),
        "citizen_phone_required": _(
            "Citizen accounts must sign in with their registered phone number and password."
        ),
    }

    def clean(self):
        identifier = (self.cleaned_data.get("username") or "").strip()
        password = self.cleaned_data.get("password")

        if identifier and password:
            self.user_cache, authenticated_with_phone = self._authenticate_identifier(
                identifier,
                password,
            )

            if self.user_cache is None:
                raise self.get_invalid_login_error()

            if get_user_role(self.user_cache) == "citizen" and not authenticated_with_phone:
                raise forms.ValidationError(
                    self.error_messages["citizen_phone_required"],
                    code="citizen_phone_required",
                )

            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data

    def _authenticate_identifier(self, identifier, password):
        normalized_phone = normalize_phone(identifier)

        if normalized_phone:
            citizen_user = _find_citizen_user_by_phone(identifier)

            if citizen_user:
                user = authenticate(
                    self.request,
                    username=citizen_user.get_username(),
                    password=password,
                )
                return user, bool(user)

        email_user = self._find_user_by_email(identifier)
        if email_user:
            user = authenticate(
                self.request,
                username=email_user.get_username(),
                password=password,
            )
            return user, False

        user = authenticate(
            self.request,
            username=identifier,
            password=password,
        )
        return user, False

    def _find_user_by_email(self, identifier):
        identifier = (identifier or "").strip()

        if "@" not in identifier:
            return None

        matches = User.objects.filter(
            email__iexact=identifier,
            is_active=True,
        )

        if matches.count() == 1:
            return matches.first()

        return None


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

        if role == "citizen":
            has_owner_record = Owner.objects.filter(
                linked_user=user,
                assembly=assembly,
            ).exists()

            has_default_assembly = profile.assembly_id == assembly.id

            allowed_manager = getattr(profile, "allowed_assemblies", None)
            has_allowed_assembly = False
            if allowed_manager is not None:
                has_allowed_assembly = allowed_manager.filter(id=assembly.id).exists()

            if has_owner_record or has_default_assembly or has_allowed_assembly:
                return True, ""

            return (
                False,
                _(
                    "This citizen account is not authorized to access the "
                    "selected assembly because it is not linked to a property "
                    "owner record, does not use the selected assembly as its "
                    "default assembly, and is not included in its allowed "
                    "assemblies."
                ),
            )

        if not profile.assembly_id:
            return False, _("This account is not assigned to any assembly.")

        if profile.assembly_id != assembly.id:
            return (
                False,
                _(
                    "You are not authorized to access the selected assembly. "
                    "Please choose your assigned assembly."
                ),
            )

        return True, ""

    def form_valid(self, form):
        remember_me = self.request.POST.get("remember_me")

        if remember_me:
            self.request.session.set_expiry(1209600)
        else:
            self.request.session.set_expiry(0)

        return super().form_valid(form)

    def get_success_url(self):
        return landing_url_for_user(self.request.user)


class AdminLoginView(PortalLoginView):
    """
    Dedicated staff/admin login.

    This keeps the existing assembly-selection login flow for admin users.
    Citizens are blocked from this page and redirected to the owner login.
    """
    authentication_form = AdminAuthenticationForm


class CitizenLoginView(LoginView):
    """
    Dedicated property owner login.

    Citizens sign in with phone number + password.
    No assembly-selection screen is shown here.
    """
    template_name = "registration/owner_login.html"
    authentication_form = CitizenPhoneAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        remember_me = self.request.POST.get("remember_me")

        if remember_me:
            self.request.session.set_expiry(1209600)
        else:
            self.request.session.set_expiry(0)

        response = super().form_valid(form)
        _set_citizen_active_assembly(self.request, self.request.user)
        return response

    def get_success_url(self):
        return reverse("citizens:dashboard")

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


REPORT_TYPE_CHOICES = (
    ("overview", "Overview"),
    ("properties", "Properties"),
    ("verification", "Verification"),
    ("billing_payments", "Billing & Payments"),
    ("citizens", "Citizens"),
)

REPORT_STATUS_CHOICES = {
    "overview": (),
    "properties": (
        ("active", "Active"),
        ("inactive", "Inactive"),
    ),
    "verification": (
        ("awaiting_review", "Pending / Under Review"),
        *Property.VERIFICATION_STATUS_CHOICES,
    ),
    "billing_payments": (
        ("outstanding", "Outstanding Balance"),
        *Bill.STATUS_CHOICES,
    ),
    "citizens": (
        ("linked", "Portal Account Linked"),
        ("unlinked", "No Portal Account"),
    ),
}


def _analytics_period_config(period, selected_year):
    if period == "yearly":
        first_year = selected_year - 4
        buckets = list(range(first_year, selected_year + 1))
        return {
            "labels": [str(year) for year in buckets],
            "buckets": buckets,
            "extractor": ExtractYear,
            "start": date(first_year, 1, 1),
            "end": date(selected_year + 1, 1, 1),
            "label": f"{first_year}–{selected_year}",
        }

    if period == "quarterly":
        return {
            "labels": ["Q1", "Q2", "Q3", "Q4"],
            "buckets": [1, 2, 3, 4],
            "extractor": ExtractQuarter,
            "start": date(selected_year, 1, 1),
            "end": date(selected_year + 1, 1, 1),
            "label": f"Q1–Q4 {selected_year}",
        }

    buckets = list(range(1, 13))
    return {
        "labels": [date(2000, month, 1).strftime("%b") for month in buckets],
        "buckets": buckets,
        "extractor": ExtractMonth,
        "start": date(selected_year, 1, 1),
        "end": date(selected_year + 1, 1, 1),
        "label": f"January–December {selected_year}",
    }


def _analytics_range(queryset, date_field, period_config):
    return queryset.filter(
        **{
            f"{date_field}__date__gte": period_config["start"],
            f"{date_field}__date__lt": period_config["end"],
        }
    )


def _analytics_series(queryset, date_field, period_config, aggregation):
    rows = (
        _analytics_range(queryset, date_field, period_config)
        .annotate(bucket=period_config["extractor"](date_field))
        .values("bucket")
        .annotate(value=aggregation)
        .order_by("bucket")
    )
    values = {
        int(row["bucket"]): row["value"]
        for row in rows
        if row["bucket"] is not None
    }
    return [values.get(bucket, 0) for bucket in period_config["buckets"]]


def _report_cell(text, *, css_class="", url=""):
    return {
        "text": str(text if text not in (None, "") else "—"),
        "class": css_class,
        "url": url,
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

    context_assembly = _get_current_assembly(request)
    user_role = get_user_role(request.user)

    finance_all_roles = {
        "sys_admin",
        "revenue_admin",
        "billing_officer",
        "payment_officer",
        "report_officer",
        "field_officer",
    }

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

    work_properties_qs = properties_qs
    work_field_visits_qs = field_visits_qs
    work_disputes_qs = disputes_qs

    if user_role == "field_officer":
        work_properties_qs = work_properties_qs.filter(registered_by=request.user)
        work_field_visits_qs = work_field_visits_qs.filter(officer=request.user)
        work_disputes_qs = work_disputes_qs.filter(
            bill__property_record__registered_by=request.user
        )

    finance_bills_qs = bills_qs
    finance_payments_qs = payments_qs

    if user_role not in finance_all_roles:
        finance_bills_qs = finance_bills_qs.filter(
            property_record__registered_by=request.user
        )
        finance_payments_qs = finance_payments_qs.filter(
            Q(property__registered_by=request.user)
            | Q(bill__property_record__registered_by=request.user)
        )

    balance_expr = ExpressionWrapper(
        F("amount_due") - F("amount_paid"),
        output_field=MONEY_FIELD,
    )

    total_properties = work_properties_qs.count()
    properties_this_month = work_properties_qs.filter(
        created_at__date__gte=current_month_start
    ).count()
    properties_previous_month = work_properties_qs.filter(
        created_at__date__gte=previous_month_start,
        created_at__date__lte=previous_month_end,
    ).count()

    property_change = _pct_change(properties_this_month, properties_previous_month)

    revenue_this_month = finance_payments_qs.filter(
        status="successful",
        paid_at__date__gte=current_month_start,
    ).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    revenue_previous_month = finance_payments_qs.filter(
        status="successful",
        paid_at__date__gte=previous_month_start,
        paid_at__date__lte=previous_month_end,
    ).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    open_bills = finance_bills_qs.exclude(status__in=["paid", "cancelled"])

    outstanding_total = open_bills.aggregate(
        total=Coalesce(Sum(balance_expr), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    outstanding_previous = open_bills.filter(
        created_at__date__lt=current_month_start
    ).aggregate(
        total=Coalesce(Sum(balance_expr), Value(Decimal("0.00"), output_field=MONEY_FIELD))
    )["total"]

    revenue_change = _pct_change(revenue_this_month, revenue_previous_month)
    outstanding_change = _pct_change(outstanding_total, outstanding_previous)

    pending_properties = work_properties_qs.filter(
        is_active=True,
        verification_status__in=["pending", "under_review"],
    ).count()

    summary_cards = [
        {
            "title": "Total Properties",
            "value": _number(total_properties),
            "meta": "new registrations vs last month",
            "change": abs(property_change),
            "change_prefix": "+" if property_change >= 0 else "-",
            "change_class": "green" if property_change >= 0 else "red",
            "icon_key": "property",
            "url": reverse("properties:property-registry"),
        },
        {
            "title": "Pending Verification",
            "value": _number(pending_properties),
            "meta": "pending or under review",
            "badge": "Needs review",
            "icon_key": "alert",
            "url": f'{reverse("properties:property-registry")}?verification=awaiting_review',
        },
        {
            "title": "Revenue Collected",
            "value": _money(revenue_this_month),
            "meta": "successful payments this month",
            "change": abs(revenue_change),
            "change_prefix": "+" if revenue_change >= 0 else "-",
            "change_class": "green" if revenue_change >= 0 else "red",
            "icon_key": "money",
            "url": reverse("billing:billing-management"),
        },
        {
            "title": "Outstanding Amount",
            "value": _money(outstanding_total),
            "meta": "total open bill balance",
            "change": abs(outstanding_change),
            "change_prefix": "-" if outstanding_total <= outstanding_previous else "+",
            "change_class": "green" if outstanding_total <= outstanding_previous else "red",
            "icon_key": "alert",
            "url": f'{reverse("billing:billing-management")}?status=outstanding',
        },
    ]

    month_starts = [date(today.year, month, 1) for month in range(1, 13)]

    revenue_rows = (
        finance_payments_qs.filter(
            status="successful",
            paid_at__year=today.year,
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

    recent_items = []

    for payment in finance_payments_qs.filter(status="successful").order_by("-paid_at", "-created_at")[:5]:
        dt = payment.paid_at or payment.created_at

        prop = getattr(payment, "property", None)
        if not prop and getattr(payment, "bill", None):
            prop = getattr(payment.bill, "property_record", None)

        prop_ref = getattr(prop, "property_reference", None) or getattr(payment, "property_reference_entered", None) or "Unknown Ref"
        owner_name = getattr(getattr(prop, "owner", None), "full_name", None) or getattr(payment, "payer_name", None) or "Unknown payer"

        recent_items.append(
            {
                "sort_at": dt,
                "icon_key": "paid",
                "icon_class": "soft-green",
                "title": f"Payment received: {_money(getattr(payment, 'amount', 0))}",
                "subtitle": f"{prop_ref} • {owner_name}",
                "time": _time_ago(dt),
                "highlight": True,
            }
        )

    for prop in work_properties_qs.order_by("-created_at")[:2]:
        owner_name = getattr(prop.owner, "full_name", "Unknown owner") if getattr(prop, "owner", None) else "Unknown owner"
        recent_items.append(
            {
                "sort_at": prop.created_at,
                "icon_key": "property",
                "icon_class": "soft-blue",
                "title": f"New property registered in {prop.area_town}",
                "subtitle": f"{prop.property_reference} • {owner_name}",
                "time": _time_ago(prop.created_at),
                "highlight": False,
            }
        )

    for dispute in work_disputes_qs.order_by("-created_at")[:2]:
        prop = getattr(dispute.bill, "property_record", None)
        prop_ref = getattr(prop, "property_reference", "Unknown Ref")
        owner_name = getattr(getattr(prop, "owner", None), "full_name", "Unknown owner")
        recent_items.append(
            {
                "sort_at": dispute.created_at,
                "icon_key": "alert",
                "icon_class": "soft-yellow",
                "title": "Rate calculation dispute",
                "subtitle": f"{prop_ref} • {owner_name}",
                "time": _time_ago(dispute.created_at),
                "highlight": False,
            }
        )

    for visit in work_field_visits_qs.order_by("-visited_at", "-created_at")[:2]:
        dt = visit.visited_at or visit.created_at
        prop = getattr(visit, "property", None)
        prop_ref = getattr(prop, "property_reference", "Unknown Ref")
        owner_name = getattr(getattr(prop, "owner", None), "full_name", "Unknown owner")
        recent_items.append(
            {
                "sort_at": dt,
                "icon_key": "field",
                "icon_class": "soft-blue",
                "title": visit.get_visit_type_display() if hasattr(visit, "get_visit_type_display") else "Field Visit",
                "subtitle": f"{prop_ref} • {owner_name}",
                "time": _time_ago(dt),
                "highlight": False,
            }
        )

    recent_items = sorted(
        recent_items,
        key=lambda item: item["sort_at"] or timezone.now(),
        reverse=True,
    )[:6]

    overdue_90_count = finance_bills_qs.filter(
        due_date__lt=today - timedelta(days=90)
    ).exclude(status__in=["paid", "cancelled"]).count()

    next_month_start = (current_month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_until_next_cycle = (next_month_start - today).days

    weekly_field_visits = work_field_visits_qs.filter(
        Q(visited_at__date__gte=week_start) | Q(created_at__date__gte=week_start)
    ).count()

    if user_role == "field_officer":
        alerts = [
            {
                "message": f"{_number(overdue_90_count)} overdue payment record(s) in the assembly",
                "action": "View properties",
                "url": reverse("properties:property-registry"),
                "alert_class": "alert-danger",
            },
            {
                "message": f"You completed {_number(weekly_field_visits)} field visit(s) this week",
                "action": "Review",
                "url": reverse("field_operations:field-officer-stats"),
                "alert_class": "alert-success",
            },
            {
                "message": f"{_number(properties_this_month)} property record(s) added by you this month",
                "action": "Open",
                "url": reverse("properties:property-registry"),
                "alert_class": "alert-info",
            },
        ]
    else:
        alerts = [
            {
                "message": f"{_number(pending_properties)} properties are pending verification",
                "action": "Review Queue",
                "url": f'{reverse("properties:property-registry")}?verification=awaiting_review',
                "alert_class": "alert-warning",
            },
            {
                "message": f"{_number(overdue_90_count)} properties have overdue payments (>90 days)",
                "action": "View List",
                "url": f'{reverse("billing:billing-management")}?status=overdue',
                "alert_class": "alert-danger",
            },
            {
                "message": f"Monthly billing cycle starts in {days_until_next_cycle} day{'s' if days_until_next_cycle != 1 else ''}",
                "action": "Prepare",
                "url": reverse("billing:billing-management"),
                "alert_class": "alert-info",
            },
        ]

    portal_access = _portal_access(request.user)
    context = {
        "page_title": "Dashboard",
        "page_subtitle": (
            "Your field activity and assembly payment overview"
            if user_role == "field_officer"
            else "Property Rate Management System Overview"
        ),
        "context_assembly": context_assembly,
        "current_year": today.year,
        "summary_cards": summary_cards,
        "revenue_points": revenue_points,
        "revenue_max": float(revenue_max),
        "recent_activities": recent_items,
        "alerts": alerts,
        "user_role": user_role,
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
    report_type = (request.GET.get("report_type") or "overview").strip()
    period = (request.GET.get("period") or "monthly").strip()
    property_use = (request.GET.get("property_use") or "").strip()
    location = (request.GET.get("location") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    valid_report_types = {value for value, _label in REPORT_TYPE_CHOICES}
    if report_type not in valid_report_types:
        report_type = "overview"
    if period not in {"monthly", "quarterly", "yearly"}:
        period = "monthly"

    try:
        selected_year = int(request.GET.get("year") or today.year)
    except (TypeError, ValueError):
        selected_year = today.year
    if selected_year < 2000 or selected_year > today.year + 1:
        selected_year = today.year

    year_options = list(range(today.year + 1, today.year - 6, -1))
    if selected_year not in year_options:
        year_options.append(selected_year)
        year_options.sort(reverse=True)

    status_choices = list(REPORT_STATUS_CHOICES[report_type])
    valid_statuses = {value for value, _label in status_choices}
    if status_filter not in valid_statuses:
        status_filter = ""

    properties_qs = Property.objects.select_related(
        "owner",
        "community_area",
    )
    owners_qs = Owner.objects.select_related("linked_user")
    bills_qs = Bill.objects.select_related(
        "property_record__owner",
        "assembly",
    )
    payments_qs = Payment.objects.filter(
        status="successful",
        paid_at__isnull=False,
    ).select_related(
        "property__owner",
        "bill__property_record__owner",
    )

    if context_assembly:
        properties_qs = properties_qs.filter(assembly=context_assembly)
        owners_qs = owners_qs.filter(assembly=context_assembly)
        bills_qs = bills_qs.filter(assembly=context_assembly)
        payments_qs = payments_qs.filter(assembly=context_assembly)

    if property_use:
        properties_qs = properties_qs.filter(property_use=property_use)
        owners_qs = owners_qs.filter(properties__property_use=property_use).distinct()
        bills_qs = bills_qs.filter(property_record__property_use=property_use)
        payments_qs = payments_qs.filter(
            Q(property__property_use=property_use)
            | Q(bill__property_record__property_use=property_use)
        )

    if location:
        property_location_q = (
            Q(area_town__icontains=location)
            | Q(suburb__icontains=location)
            | Q(address_line__icontains=location)
            | Q(digital_address__icontains=location)
            | Q(community_area__name__icontains=location)
        )
        properties_qs = properties_qs.filter(property_location_q)
        owners_qs = owners_qs.filter(
            Q(properties__area_town__icontains=location)
            | Q(properties__suburb__icontains=location)
            | Q(properties__address_line__icontains=location)
            | Q(properties__digital_address__icontains=location)
            | Q(properties__community_area__name__icontains=location)
        ).distinct()
        bills_qs = bills_qs.filter(
            Q(property_record__area_town__icontains=location)
            | Q(property_record__suburb__icontains=location)
            | Q(property_record__address_line__icontains=location)
            | Q(property_record__digital_address__icontains=location)
            | Q(property_record__community_area__name__icontains=location)
        )
        payments_qs = payments_qs.filter(
            Q(property__area_town__icontains=location)
            | Q(property__suburb__icontains=location)
            | Q(property__address_line__icontains=location)
            | Q(property__digital_address__icontains=location)
            | Q(property__community_area__name__icontains=location)
            | Q(bill__property_record__area_town__icontains=location)
            | Q(bill__property_record__suburb__icontains=location)
            | Q(bill__property_record__address_line__icontains=location)
            | Q(bill__property_record__digital_address__icontains=location)
            | Q(bill__property_record__community_area__name__icontains=location)
        ).distinct()

    if report_type == "properties" and status_filter:
        properties_qs = properties_qs.filter(is_active=status_filter == "active")
    elif report_type == "verification" and status_filter:
        if status_filter == "awaiting_review":
            properties_qs = properties_qs.filter(
                verification_status__in=["pending", "under_review"]
            )
        else:
            properties_qs = properties_qs.filter(verification_status=status_filter)
    elif report_type == "billing_payments" and status_filter:
        if status_filter == "outstanding":
            bills_qs = bills_qs.exclude(status="cancelled").filter(
                amount_due__gt=F("amount_paid")
            )
            payments_qs = payments_qs.exclude(
                bill__status="cancelled"
            ).filter(
                bill__amount_due__gt=F("bill__amount_paid")
            )
        else:
            bills_qs = bills_qs.filter(status=status_filter)
            payments_qs = payments_qs.filter(bill__status=status_filter)
    elif report_type == "citizens" and status_filter:
        owners_qs = owners_qs.filter(
            linked_user__isnull=status_filter == "unlinked"
        )

    if report_type == "citizens":
        owner_ids = owners_qs.values("id")
        properties_qs = properties_qs.filter(owner_id__in=owner_ids)
        bills_qs = bills_qs.filter(property_record__owner_id__in=owner_ids)
        payments_qs = payments_qs.filter(
            Q(property__owner_id__in=owner_ids)
            | Q(bill__property_record__owner_id__in=owner_ids)
        ).distinct()

    period_config = _analytics_period_config(period, selected_year)
    period_properties_qs = _analytics_range(properties_qs, "created_at", period_config)
    period_owners_qs = _analytics_range(owners_qs, "created_at", period_config)
    period_bills_qs = _analytics_range(bills_qs, "issued_at", period_config)
    period_payments_qs = _analytics_range(payments_qs, "paid_at", period_config)
    financial_bills_qs = period_bills_qs.exclude(status="cancelled")
    balance_expr = ExpressionWrapper(
        F("amount_due") - F("amount_paid"),
        output_field=MONEY_FIELD,
    )
    outstanding_bills_qs = financial_bills_qs.filter(
        amount_due__gt=F("amount_paid")
    )

    def money_total(queryset, expression):
        return queryset.aggregate(
            total=Coalesce(
                Sum(expression),
                Value(Decimal("0.00"), output_field=MONEY_FIELD),
            )
        )["total"]

    billed_total = money_total(financial_bills_qs, "amount_due")
    revenue_total = money_total(period_payments_qs, "amount")
    outstanding_total = money_total(outstanding_bills_qs, balance_expr)
    rateable_total = money_total(properties_qs, "rateable_value")
    verified_qs = properties_qs.filter(
        is_active=True,
        verification_status="verified",
    )
    awaiting_qs = properties_qs.filter(
        is_active=True,
        verification_status__in=["pending", "under_review"],
    )
    range_label = period_config["label"]

    def stat(icon_key, icon_class, title, value, meta):
        return {
            "icon_key": icon_key,
            "icon_class": icon_class,
            "title": title,
            "value": value,
            "meta": meta,
        }

    if report_type == "properties":
        stats = [
            stat("property", "icon-blue", "Properties in Registry", _number(properties_qs.count()), "matching current filters"),
            stat("property", "icon-gold", "Properties Registered", _number(period_properties_qs.count()), range_label),
            stat("mark", "icon-green", "Active Properties", _number(properties_qs.filter(is_active=True).count()), "currently active"),
            stat("money", "icon-gold", "Rateable Value", _money(rateable_total), "matching properties"),
        ]
    elif report_type == "verification":
        total_for_rate = max(properties_qs.count(), 1)
        verification_rate = (verified_qs.count() / total_for_rate) * 100
        stats = [
            stat("mark", "icon-green", "Verified Properties", _number(verified_qs.count()), "active and verified"),
            stat("alert", "icon-gold", "Pending Verification", _number(awaiting_qs.count()), "pending or under review"),
            stat("alert", "icon-blue", "Flagged", _number(properties_qs.filter(verification_status__in=["flagged", "possible_duplicate"]).count()), "requires investigation"),
            stat("alert", "icon-gold", "Rejected", _number(properties_qs.filter(verification_status="rejected").count()), "verification rejected"),
            stat("collection", "icon-green", "Verification Rate", f"{verification_rate:.1f}%", "of matching properties"),
        ]
    elif report_type == "billing_payments":
        stats = [
            stat("bill", "icon-blue", "Bills Generated", _number(period_bills_qs.count()), range_label),
            stat("money", "icon-blue", "Amount Billed", _money(billed_total), range_label),
            stat("paid", "icon-green", "Payments Recorded", _number(period_payments_qs.count()), "successful payments"),
            stat("collection", "icon-green", "Revenue Collected", _money(revenue_total), range_label),
            stat("reciept", "icon-gold", "Outstanding Bills", _number(outstanding_bills_qs.count()), "open balances"),
            stat("alert", "icon-gold", "Outstanding Amount", _money(outstanding_total), "balance due"),
        ]
    elif report_type == "citizens":
        stats = [
            stat("assembly", "icon-blue", "Citizens / Owners", _number(owners_qs.count()), "matching current filters"),
            stat("assembly", "icon-gold", "Citizens Added", _number(period_owners_qs.count()), range_label),
            stat("mark", "icon-green", "Portal Accounts", _number(owners_qs.filter(linked_user__isnull=False).count()), "linked citizen accounts"),
            stat("property", "icon-blue", "Properties Owned", _number(properties_qs.count()), "matching citizens"),
            stat("alert", "icon-gold", "Outstanding Amount", _money(outstanding_total), "balance due"),
        ]
    else:
        stats = [
            stat("property", "icon-blue", "Total Properties", _number(properties_qs.count()), "matching current filters"),
            stat("mark", "icon-green", "Verified Properties", _number(verified_qs.count()), "active and verified"),
            stat("alert", "icon-gold", "Pending Verification", _number(awaiting_qs.count()), "pending or under review"),
            stat("assembly", "icon-blue", "Citizens / Owners", _number(owners_qs.count()), "registered owners"),
            stat("bill", "icon-blue", "Bills Generated", _number(period_bills_qs.count()), range_label),
            stat("paid", "icon-green", "Payments Recorded", _number(period_payments_qs.count()), "successful payments"),
            stat("collection", "icon-green", "Revenue Collected", _money(revenue_total), range_label),
            stat("alert", "icon-gold", "Outstanding Amount", _money(outstanding_total), "balance due"),
        ]

    count_aggregation = Count("id")
    billed_aggregation = Sum("amount_due")
    collected_aggregation = Sum("amount")
    outstanding_aggregation = Sum(balance_expr)

    def dataset(label, values, color):
        return {
            "label": label,
            "data": [float(value or 0) for value in values],
            "backgroundColor": color,
            "borderColor": color,
        }

    if report_type == "properties":
        chart_title = "Property Registration Trend"
        chart_subtitle = f"Properties registered by {period[:-2] if period.endswith('ly') else period} period"
        chart_is_money = False
        chart_datasets = [
            dataset(
                "Properties Registered",
                _analytics_series(properties_qs, "created_at", period_config, count_aggregation),
                "#c9a031",
            )
        ]
    elif report_type == "verification":
        chart_title = "Verification Status Trend"
        chart_subtitle = "Registration cohorts grouped by their current verification status"
        chart_is_money = False
        other_verification_qs = properties_qs.exclude(
            verification_status__in=["verified", "pending", "under_review"]
        )
        chart_datasets = [
            dataset("Verified", _analytics_series(verified_qs, "created_at", period_config, count_aggregation), "#16a34a"),
            dataset("Pending / Review", _analytics_series(awaiting_qs, "created_at", period_config, count_aggregation), "#d9a92c"),
            dataset("Flagged / Rejected", _analytics_series(other_verification_qs, "created_at", period_config, count_aggregation), "#dc3545"),
        ]
    elif report_type == "citizens":
        chart_title = "Citizen and Property Registration Trend"
        chart_subtitle = "New property owners and their registered properties"
        chart_is_money = False
        chart_datasets = [
            dataset("Citizens / Owners", _analytics_series(owners_qs, "created_at", period_config, count_aggregation), "#1f1f1f"),
            dataset("Properties", _analytics_series(properties_qs, "created_at", period_config, count_aggregation), "#c7a541"),
        ]
    else:
        chart_title = "Billing & Revenue Trend" if report_type == "billing_payments" else "Financial Overview"
        chart_subtitle = "Amount billed, collected and still outstanding"
        chart_is_money = True
        chart_datasets = [
            dataset("Amount Billed", _analytics_series(financial_bills_qs, "issued_at", period_config, billed_aggregation), "#1f1f1f"),
            dataset("Revenue Collected", _analytics_series(payments_qs, "paid_at", period_config, collected_aggregation), "#16a34a"),
            dataset("Outstanding", _analytics_series(outstanding_bills_qs, "issued_at", period_config, outstanding_aggregation), "#d9a92c"),
        ]

    chart_config = {
        "labels": period_config["labels"],
        "datasets": chart_datasets,
        "isMoney": chart_is_money,
    }

    def record_date(value):
        if not value:
            return "—"
        if hasattr(value, "hour"):
            value = timezone.localtime(value)
        return value.strftime("%d %b %Y")

    def property_location(property_record):
        return ", ".join(
            part
            for part in [property_record.area_town, property_record.suburb]
            if part
        ) or property_record.address_line

    page_number = request.GET.get("page", 1)

    if report_type == "properties":
        record_title = "Property Records"
        record_subtitle = "Properties matching the selected filters and reporting range"
        record_columns = ["Registered", "Reference", "Owner", "Location", "Use", "Verification", "Record Status"]
        record_paginator = Paginator(period_properties_qs.order_by("-created_at"), 10)
        record_page_obj = record_paginator.get_page(page_number)
        record_rows = []
        for property_record in record_page_obj:
            detail_url = reverse("properties:property-detail", args=[property_record.pk])
            verification_class = "status-success" if property_record.verification_status == "verified" else "status-warning"
            record_rows.append({
                "cells": [
                    _report_cell(record_date(property_record.created_at)),
                    _report_cell(property_record.property_reference, url=detail_url),
                    _report_cell(property_record.owner.full_name),
                    _report_cell(property_location(property_record)),
                    _report_cell(property_record.get_property_use_display()),
                    _report_cell(property_record.get_verification_status_display(), css_class=verification_class),
                    _report_cell("Active" if property_record.is_active else "Inactive", css_class="status-success" if property_record.is_active else "status-neutral"),
                ]
            })
    elif report_type == "verification":
        record_title = "Verification Records"
        record_subtitle = "Current verification state of properties registered in the reporting range"
        record_columns = ["Registered", "Reference", "Owner", "Location", "Status", "Last Verified"]
        record_paginator = Paginator(period_properties_qs.order_by("-created_at"), 10)
        record_page_obj = record_paginator.get_page(page_number)
        record_rows = []
        for property_record in record_page_obj:
            detail_url = reverse("properties:property-detail", args=[property_record.pk])
            if property_record.verification_status == "verified":
                status_class = "status-success"
            elif property_record.verification_status in {"pending", "under_review"}:
                status_class = "status-warning"
            else:
                status_class = "status-danger"
            record_rows.append({
                "cells": [
                    _report_cell(record_date(property_record.created_at)),
                    _report_cell(property_record.property_reference, url=detail_url),
                    _report_cell(property_record.owner.full_name),
                    _report_cell(property_location(property_record)),
                    _report_cell(property_record.get_verification_status_display(), css_class=status_class),
                    _report_cell(record_date(property_record.last_verified_at)),
                ]
            })
    elif report_type == "billing_payments":
        record_title = "Billing Records"
        record_subtitle = "Bills issued in the reporting range; payment totals are reflected above"
        record_columns = ["Issued", "Bill Number", "Property", "Owner", "Amount Due", "Paid", "Balance", "Status"]
        record_paginator = Paginator(period_bills_qs.order_by("-issued_at"), 10)
        record_page_obj = record_paginator.get_page(page_number)
        record_rows = []
        for bill in record_page_obj:
            detail_url = reverse("properties:property-detail", args=[bill.property_record_id])
            if bill.status == "paid":
                status_class = "status-success"
            elif bill.status == "cancelled":
                status_class = "status-neutral"
            else:
                status_class = "status-warning"
            record_rows.append({
                "cells": [
                    _report_cell(record_date(bill.issued_at)),
                    _report_cell(bill.bill_number, url=detail_url),
                    _report_cell(bill.property_record.property_reference, url=detail_url),
                    _report_cell(bill.property_record.owner.full_name),
                    _report_cell(_money(bill.amount_due)),
                    _report_cell(_money(bill.amount_paid)),
                    _report_cell(_money(max(bill.balance, Decimal("0.00")))),
                    _report_cell(bill.get_status_display(), css_class=status_class),
                ]
            })
    elif report_type == "citizens":
        record_title = "Citizen / Owner Records"
        record_subtitle = "Property owners registered in the selected reporting range"
        record_columns = ["Registered", "Citizen / Owner", "Phone", "Email", "Properties", "Portal Access"]
        citizen_records_qs = period_owners_qs.annotate(
            property_count=Count("properties", distinct=True)
        ).order_by("-created_at")
        record_paginator = Paginator(citizen_records_qs, 10)
        record_page_obj = record_paginator.get_page(page_number)
        record_rows = []
        for owner in record_page_obj:
            owner_url = f'{reverse("properties:property-registry")}?q={owner.primary_phone}'
            record_rows.append({
                "cells": [
                    _report_cell(record_date(owner.created_at)),
                    _report_cell(owner.full_name, url=owner_url),
                    _report_cell(owner.primary_phone),
                    _report_cell(owner.email or "Not provided"),
                    _report_cell(owner.property_count),
                    _report_cell("Linked" if owner.linked_user_id else "Not linked", css_class="status-success" if owner.linked_user_id else "status-neutral"),
                ]
            })
    else:
        record_title = "Recent Records"
        record_subtitle = "Latest properties, citizens, bills and successful payments in the reporting range"
        record_columns = ["Date", "Type", "Reference", "Details", "Status"]
        combined_records = []
        for property_record in period_properties_qs.order_by("-created_at")[:30]:
            combined_records.append({
                "sort_at": property_record.created_at,
                "cells": [
                    _report_cell(record_date(property_record.created_at)),
                    _report_cell("Property", css_class="type-property"),
                    _report_cell(property_record.property_reference, url=reverse("properties:property-detail", args=[property_record.pk])),
                    _report_cell(f"{property_record.owner.full_name} · {property_location(property_record)}"),
                    _report_cell(property_record.get_verification_status_display(), css_class="status-success" if property_record.verification_status == "verified" else "status-warning"),
                ],
            })
        for bill in period_bills_qs.order_by("-issued_at")[:30]:
            combined_records.append({
                "sort_at": bill.issued_at,
                "cells": [
                    _report_cell(record_date(bill.issued_at)),
                    _report_cell("Bill", css_class="type-bill"),
                    _report_cell(bill.bill_number, url=reverse("properties:property-detail", args=[bill.property_record_id])),
                    _report_cell(f"{bill.property_record.property_reference} · {_money(bill.amount_due)}"),
                    _report_cell(bill.get_status_display(), css_class="status-success" if bill.status == "paid" else "status-warning"),
                ],
            })
        for payment in period_payments_qs.order_by("-paid_at")[:30]:
            payment_property = payment.property or getattr(payment.bill, "property_record", None)
            payment_url = reverse("properties:property-detail", args=[payment_property.pk]) if payment_property else ""
            combined_records.append({
                "sort_at": payment.paid_at,
                "cells": [
                    _report_cell(record_date(payment.paid_at)),
                    _report_cell("Payment", css_class="type-payment"),
                    _report_cell(payment.transaction_reference, url=payment_url),
                    _report_cell(f"{getattr(payment_property, 'property_reference', 'Unmatched')} · {_money(payment.amount)}"),
                    _report_cell("Completed", css_class="status-success"),
                ],
            })
        for owner in period_owners_qs.order_by("-created_at")[:20]:
            combined_records.append({
                "sort_at": owner.created_at,
                "cells": [
                    _report_cell(record_date(owner.created_at)),
                    _report_cell("Citizen", css_class="type-citizen"),
                    _report_cell(owner.primary_phone),
                    _report_cell(owner.full_name),
                    _report_cell("Portal linked" if owner.linked_user_id else "Registered", css_class="status-success" if owner.linked_user_id else "status-neutral"),
                ],
            })
        combined_records.sort(key=lambda item: item["sort_at"] or timezone.now(), reverse=True)
        record_paginator = Paginator(combined_records, 10)
        record_page_obj = record_paginator.get_page(page_number)
        record_rows = list(record_page_obj.object_list)

    filter_query_params = request.GET.copy()
    filter_query_params.pop("page", None)
    filter_query_params["report_type"] = report_type
    filter_query_params["period"] = period
    filter_query_params["year"] = selected_year
    for key, value in {
        "property_use": property_use,
        "location": location,
        "status": status_filter,
    }.items():
        if value:
            filter_query_params[key] = value
        else:
            filter_query_params.pop(key, None)

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
    status_choices_by_report = {
        key: [
            {"value": value, "label": label}
            for value, label in choices
        ]
        for key, choices in REPORT_STATUS_CHOICES.items()
    }

    context = {
        "page_title": "Reports & Analytics",
        "page_subtitle": "Review operational trends and export system reports",
        "context_assembly": context_assembly,
        "stats": stats,
        "report_type_choices": REPORT_TYPE_CHOICES,
        "selected_report_type": report_type,
        "selected_report_type_label": dict(REPORT_TYPE_CHOICES)[report_type],
        "selected_period": period,
        "selected_year": selected_year,
        "year_options": year_options,
        "property_use_choices": Property.PROPERTY_USE_CHOICES,
        "selected_property_use": property_use,
        "location": location,
        "selected_status": status_filter,
        "status_choices": status_choices,
        "status_choices_by_report": status_choices_by_report,
        "range_label": range_label,
        "chart_title": chart_title,
        "chart_subtitle": chart_subtitle,
        "chart_config": chart_config,
        "record_title": record_title,
        "record_subtitle": record_subtitle,
        "record_columns": record_columns,
        "record_rows": record_rows,
        "record_page_obj": record_page_obj,
        "record_paginator": record_paginator,
        "record_start_index": record_page_obj.start_index() if record_paginator.count else 0,
        "record_end_index": record_page_obj.end_index() if record_paginator.count else 0,
        "filter_query": filter_query_params.urlencode(),
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

            profile = getattr(
                user,
                "profile",
                None,
            )

            if profile:
                profile.must_change_password = False

                profile.save(
                    update_fields=[
                        "must_change_password",
                        "updated_at",
                    ]
                )

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


@login_required
def notifications_center(request):
    notifications = (
        UserNotification.objects
        .filter(
            user=request.user,
        )
        .order_by(
            "-created_at",
        )
    )

    role = get_user_role(
        request.user
    )

    context = {
        "page_title": "Notifications",
        "notifications": notifications,
        "unread_count": (
            notifications.filter(
                is_read=False,
            ).count()
        ),
        "portal_access": (
            get_allowed_modules(
                request.user
            )
        ),
        "portal_role": role,
        "is_field_officer": (
            role == "field_officer"
        ),
        "is_citizen": (
            role == "citizen"
        ),
        "back_url": (
            landing_url_for_user(
                request.user
            )
        ),
    }

    return render(
        request,
        "shared/notifications.html",
        context,
    )


@login_required
@require_POST
def mark_notification_read(
    request,
    notification_id,
):
    notification = get_object_or_404(
        UserNotification,
        id=notification_id,
        user=request.user,
    )

    notification.mark_read()

    next_url = (
        request.POST.get("next")
        or ""
    ).strip()

    if not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={
            request.get_host()
        },
        require_https=(
            request.is_secure()
        ),
    ):
        next_url = reverse(
            "notifications"
        )

    return redirect(
        next_url
    )


@login_required
@require_POST
def mark_all_notifications_read(
    request,
):
    UserNotification.objects.filter(
        user=request.user,
        is_read=False,
    ).update(
        is_read=True,
        read_at=timezone.now(),
    )

    return redirect(
        "notifications"
    )
