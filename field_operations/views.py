from datetime import timedelta

from django.db.models import Count, Max, Q
from django.shortcuts import render, redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from django.contrib.auth.decorators import login_required

from admins.access import get_allowed_modules, get_user_role
from admins.decorators import module_required
from admins.models import Assembly, UserProfile
from field_operations.models import FieldVisit
from properties.models import Property

try:
    from properties.models import PropertyPhoto
except ImportError:
    PropertyPhoto = None


def _get_current_assembly(request):
    """
    Get the active assembly for the current request.

    Priority:
    1. Assembly selected in the current session.
    2. Assembly assigned to the logged-in user's profile.
    """

    assembly_id = request.session.get("active_assembly_id")

    if assembly_id:
        try:
            return Assembly.objects.get(
                id=assembly_id,
                is_active=True,
            )
        except Assembly.DoesNotExist:
            pass

    profile = getattr(request.user, "profile", None)

    if profile and getattr(profile, "assembly_id", None):
        try:
            return Assembly.objects.get(
                id=profile.assembly_id,
                is_active=True,
            )
        except Assembly.DoesNotExist:
            return None

    return None


def _safe_reverse(
    url_name,
    args=None,
    kwargs=None,
    fallback="#",
):
    """
    Reverse a URL without breaking the dashboard if an optional URL
    has not yet been registered.
    """

    try:
        return reverse(
            url_name,
            args=args or [],
            kwargs=kwargs or {},
        )
    except NoReverseMatch:
        return fallback


def _officer_name(user):
    full_name = user.get_full_name().strip()

    return full_name or user.username


def _format_datetime(value):
    if not value:
        return "No activity yet"

    try:
        value = timezone.localtime(value)
    except (ValueError, TypeError):
        pass

    return value.strftime("%Y-%m-%d at %H:%M")


def _visit_status(visit):
    """
    Return display information for a field visit.

    No emoji or text symbols are returned. The template uses SVG icons.
    """

    status_text = (
        f"{getattr(visit, 'outcome', '')} "
        f"{getattr(visit, 'notes', '')}"
    ).lower()

    if any(
        word in status_text
        for word in [
            "discrep",
            "mismatch",
            "issue",
            "failed",
            "fail",
            "duplicate",
            "rejected",
        ]
    ):
        return {
            "label": "Discrepancy",
            "status_class": "status-discrepancy",
            "icon_class": "activity-red",
            "icon_name": "warning",
        }

    if any(
        word in status_text
        for word in [
            "pending",
            "await",
            "review",
            "progress",
            "follow up",
            "follow-up",
        ]
    ):
        return {
            "label": "Pending",
            "status_class": "status-pending",
            "icon_class": "activity-yellow",
            "icon_name": "clock",
        }

    return {
        "label": "Verified",
        "status_class": "status-verified",
        "icon_class": "activity-green",
        "icon_name": "check",
    }


def _visit_title(visit):
    if hasattr(visit, "get_visit_type_display"):
        raw_title = visit.get_visit_type_display()
    else:
        raw_title = str(
            getattr(
                visit,
                "visit_type",
                "Verification",
            )
        ).replace("_", " ").title()

    title_mapping = {
        "Verification": "Property Verification",
        "Property Verification": "Property Verification",
        "Payment Verification": "Payment Verification",
        "Assessment": "Site Assessment",
        "Site Assessment": "Site Assessment",
        "Dispute": "Dispute Investigation",
        "Dispute Investigation": "Dispute Investigation",
        "Enumeration": "Property Enumeration",
        "Follow Up": "Follow-up Visit",
        "Follow-Up": "Follow-up Visit",
    }

    return title_mapping.get(
        raw_title,
        raw_title,
    )


def _visit_location(property_record):
    location_parts = []

    address_line = (
        getattr(
            property_record,
            "address_line",
            "",
        )
        or ""
    ).strip()

    suburb = (
        getattr(
            property_record,
            "suburb",
            "",
        )
        or ""
    ).strip()

    area_town = (
        getattr(
            property_record,
            "area_town",
            "",
        )
        or ""
    ).strip()

    digital_address = (
        getattr(
            property_record,
            "digital_address",
            "",
        )
        or ""
    ).strip()

    for location_value in [
        address_line,
        suburb,
        area_town,
    ]:
        if (
            location_value
            and location_value not in location_parts
        ):
            location_parts.append(location_value)

    if location_parts:
        return ", ".join(location_parts)

    if digital_address:
        return digital_address

    community_area = getattr(
        property_record,
        "community_area",
        None,
    )

    if community_area:
        return getattr(
            community_area,
            "name",
            str(community_area),
        )

    return "Location not set"


def _visit_description(visit):
    notes = (
        getattr(
            visit,
            "notes",
            "",
        )
        or ""
    ).strip()

    if notes:
        return notes

    visit_status = _visit_status(visit)
    visit_title = _visit_title(visit)

    if visit_title == "Payment Verification":
        return (
            "The property owner's payment claim was checked "
            "during the field visit."
        )

    if visit_title == "Site Assessment":
        return (
            "A site assessment was conducted and the property's "
            "physical details were reviewed."
        )

    if visit_title == "Dispute Investigation":
        return (
            "A reported property or billing dispute was investigated "
            "and the findings were recorded."
        )

    if visit_title == "Property Enumeration":
        return (
            "The property was enumerated and its registration details "
            "were captured."
        )

    if visit_status["label"] == "Discrepancy":
        return (
            "A discrepancy was found during verification and the "
            "property record requires further review."
        )

    if visit_status["label"] == "Pending":
        return (
            "The field activity has been recorded and is awaiting "
            "completion or administrative review."
        )

    return (
        "The property was verified and the recorded details were "
        "confirmed."
    )


def _property_owner_name(property_record):
    owner = getattr(
        property_record,
        "owner",
        None,
    )

    if not owner:
        return "Owner not available"

    return (
        getattr(owner, "full_name", None)
        or getattr(owner, "name", None)
        or str(owner)
    )


def _property_location(property_record):
    return _visit_location(property_record)


def _location_capture_label(property_record):
    latitude = getattr(
        property_record,
        "latitude",
        None,
    )

    longitude = getattr(
        property_record,
        "longitude",
        None,
    )

    digital_address = (
        getattr(
            property_record,
            "digital_address",
            "",
        )
        or ""
    ).strip()

    if (
        latitude is not None
        and longitude is not None
    ):
        return "GPS captured"

    if digital_address:
        return "Digital address added"

    return "Location pending"


def _property_assignment_status(property_record):
    verification_status = (
        getattr(
            property_record,
            "verification_status",
            "",
        )
        or ""
    ).strip().lower()

    if verification_status in {
        "verified",
        "approved",
        "completed",
    }:
        return {
            "label": "Completed",
            "status_class": "status-completed",
            "action_label": "View Record",
            "task_label": "Verification",
            "icon_name": "check",
            "activity_class": "activity-green",
        }

    if verification_status in {
        "flagged",
        "possible_duplicate",
        "under_review",
        "in_progress",
        "disputed",
    }:
        return {
            "label": "In Progress",
            "status_class": "status-progress",
            "action_label": "Continue Review",
            "task_label": "Dispute Investigation",
            "icon_name": "progress",
            "activity_class": "activity-blue",
        }

    return {
        "label": "Pending",
        "status_class": "status-pending",
        "action_label": "Start Verification",
        "task_label": "Verification",
        "icon_name": "clock",
        "activity_class": "activity-yellow",
    }


def _property_priority(property_record):
    verification_status = (
        getattr(
            property_record,
            "verification_status",
            "",
        )
        or ""
    ).strip().lower()

    if verification_status in {
        "flagged",
        "possible_duplicate",
        "disputed",
        "rejected",
    }:
        return {
            "label": "High",
            "priority_class": "priority-high",
        }

    if verification_status in {
        "pending",
        "under_review",
        "in_progress",
        "unverified",
    }:
        return {
            "label": "Medium",
            "priority_class": "priority-medium",
        }

    return {
        "label": "Low",
        "priority_class": "priority-low",
    }


def _get_property_photo_count(
    request,
    properties_queryset,
    assembly,
):
    """
    Count property photos safely even if the local PropertyPhoto model
    uses a slightly different field structure.
    """

    if PropertyPhoto is None:
        return 0

    photo_field_names = {
        field.name
        for field in PropertyPhoto._meta.get_fields()
    }

    photos_queryset = PropertyPhoto.objects.all()

    if "uploaded_by" in photo_field_names:
        photos_queryset = photos_queryset.filter(
            uploaded_by=request.user
        )
    elif "property" in photo_field_names:
        photos_queryset = photos_queryset.filter(
            property__in=properties_queryset
        )

    if (
        assembly
        and "property" in photo_field_names
    ):
        photos_queryset = photos_queryset.filter(
            property__assembly=assembly
        )

    return photos_queryset.count()


def _build_field_officer_context(
    request,
    assembly,
    portal_access,
):
    """
    Build the personal dashboard shown to a field officer.
    """

    today = timezone.localdate()

    week_start = today - timedelta(
        days=today.weekday()
    )

    officer_visits = (
        FieldVisit.objects
        .select_related(
            "property",
            "property__owner",
            "property__assembly",
            "officer",
        )
        .filter(officer=request.user)
        .order_by(
            "-visited_at",
            "-created_at",
        )
    )

    if assembly:
        officer_visits = officer_visits.filter(
            property__assembly=assembly
        )

    visit_property_ids = officer_visits.values_list(
        "property_id",
        flat=True,
    )

    properties_queryset = (
        Property.objects
        .select_related(
            "owner",
            "assembly",
            "community_area",
            "registered_by",
            "applied_rate_policy",
        )
        .filter(
            Q(registered_by=request.user)
            | Q(id__in=visit_property_ids)
        )
        .distinct()
        .order_by("-created_at")
    )

    if assembly:
        properties_queryset = (
            properties_queryset.filter(
                assembly=assembly
            )
        )

    total_properties = properties_queryset.count()

    today_visit_count = officer_visits.filter(
        visited_at__date=today
    ).count()

    week_visit_count = officer_visits.filter(
        visited_at__date__gte=week_start
    ).count()

    month_visit_count = officer_visits.filter(
        visited_at__year=today.year,
        visited_at__month=today.month,
    ).count()

    verified_properties = (
        properties_queryset.filter(
            verification_status="verified"
        )
    )

    verified_count = verified_properties.count()

    today_completed_count = (
        verified_properties.filter(
            last_verified_at__date=today
        ).count()
    )

    location_complete_count = (
        properties_queryset
        .exclude(latitude__isnull=True)
        .exclude(longitude__isnull=True)
        .count()
    )

    photos_count = _get_property_photo_count(
        request=request,
        properties_queryset=properties_queryset,
        assembly=assembly,
    )

    completion_rate = (
        round(
            (
                verified_count
                / total_properties
            )
            * 100
        )
        if total_properties
        else 0
    )

    accuracy_rate = (
        round(
            (
                location_complete_count
                / total_properties
            )
            * 100
        )
        if total_properties
        else 0
    )

    if completion_rate >= 85:
        response_label = "Excellent"
        response_width = 95
    elif completion_rate >= 60:
        response_label = "Good"
        response_width = 75
    elif total_properties:
        response_label = "Needs Attention"
        response_width = 50
    else:
        response_label = "No Data"
        response_width = 0

    property_registry_url = _safe_reverse(
        "properties:property-registry",
        fallback="#",
    )

    add_property_url = _safe_reverse(
        "properties:add-property",
        fallback=property_registry_url,
    )

    summary_cards = [
        {
            "label": "Today",
            "value": today_visit_count,
            "note": f"{today_completed_count} done",
            "icon_name": "pin",
            "accent_class": "accent-blue",
            "value_class": "",
        },
        {
            "label": "This Week",
            "value": week_visit_count,
            "note": "field activities",
            "icon_name": "check",
            "accent_class": "accent-green",
            "value_class": "value-green",
        },
        {
            "label": "This Month",
            "value": month_visit_count,
            "note": "field activities",
            "icon_name": "trend",
            "accent_class": "accent-purple",
            "value_class": "",
        },
        {
            "label": "Photos",
            "value": photos_count,
            "note": "uploaded",
            "icon_name": "camera",
            "accent_class": "accent-gold",
            "value_class": "",
        },
    ]

    quick_actions = [
        {
            "label": "Submit Verification",
            "url": property_registry_url,
            "icon_name": "check",
        },
        {
            "label": "Upload Photos",
            "url": property_registry_url,
            "icon_name": "camera",
        },
        {
            "label": "Register Property",
            "url": add_property_url,
            "icon_name": "route",
        },
        {
            "label": "View All",
            "url": property_registry_url,
            "icon_name": "pin",
        },
    ]

    pending_properties = (
        properties_queryset.filter(
            verification_status__in=[
                "pending",
                "unverified",
                "under_review",
                "in_progress",
                "flagged",
                "possible_duplicate",
                "disputed",
            ]
        )
        .order_by("-created_at")
    )

    if pending_properties.exists():
        assignment_queryset = pending_properties
    else:
        assignment_queryset = properties_queryset

    assignment_items = []

    for property_record in assignment_queryset[:6]:
        status_data = _property_assignment_status(
            property_record
        )

        priority_data = _property_priority(
            property_record
        )

        detail_url = _safe_reverse(
            "properties:property-detail",
            args=[property_record.id],
            fallback=property_registry_url,
        )

        assignment_items.append(
            {
                "id": property_record.id,
                "reference": (
                    property_record.property_reference
                ),
                "owner_name": _property_owner_name(
                    property_record
                ),
                "location": _property_location(
                    property_record
                ),
                "status_label": status_data["label"],
                "status_class": (
                    status_data["status_class"]
                ),
                "status_icon": (
                    status_data["icon_name"]
                ),
                "priority_label": (
                    priority_data["label"]
                ),
                "priority_class": (
                    priority_data["priority_class"]
                ),
                "task_label": (
                    status_data["task_label"]
                ),
                "location_label": (
                    _location_capture_label(
                        property_record
                    )
                ),
                "action_label": (
                    status_data["action_label"]
                ),
                "detail_url": detail_url,
            }
        )

    recent_activity = []

    for visit in officer_visits[:5]:
        visit_status = _visit_status(visit)
        property_record = visit.property

        visit_datetime = (
            visit.visited_at
            or visit.created_at
        )

        detail_url = _safe_reverse(
            "properties:property-detail",
            args=[property_record.id],
            fallback=property_registry_url,
        )

        recent_activity.append(
            {
                "reference": getattr(
                    property_record,
                    "property_reference",
                    "N/A",
                ),
                "location": _visit_location(
                    property_record
                ),
                "datetime": _format_datetime(
                    visit_datetime
                ),
                "icon_name": (
                    visit_status["icon_name"]
                ),
                "icon_class": (
                    visit_status["icon_class"]
                ),
                "detail_url": detail_url,
            }
        )

    if not recent_activity:
        for property_record in properties_queryset[:5]:
            status_data = _property_assignment_status(
                property_record
            )

            activity_datetime = (
                getattr(
                    property_record,
                    "updated_at",
                    None,
                )
                or property_record.created_at
            )

            detail_url = _safe_reverse(
                "properties:property-detail",
                args=[property_record.id],
                fallback=property_registry_url,
            )

            recent_activity.append(
                {
                    "reference": (
                        property_record.property_reference
                    ),
                    "location": _property_location(
                        property_record
                    ),
                    "datetime": _format_datetime(
                        activity_datetime
                    ),
                    "icon_name": (
                        status_data["icon_name"]
                    ),
                    "icon_class": (
                        status_data["activity_class"]
                    ),
                    "detail_url": detail_url,
                }
            )

    performance_rows = [
        {
            "label": "Completion Rate",
            "value": f"{completion_rate}%",
            "width": completion_rate,
            "bar_class": "bar-green",
        },
        {
            "label": "Accuracy Rate",
            "value": f"{accuracy_rate}%",
            "width": accuracy_rate,
            "bar_class": "bar-blue",
        },
        {
            "label": "Response Time",
            "value": response_label,
            "width": response_width,
            "bar_class": "bar-purple",
        },
    ]

    officer_name = _officer_name(
        request.user
    )

    officer_initial = (
        officer_name[0].upper()
        if officer_name
        else "F"
    )

    assembly_name = (
        assembly.name
        if assembly
        else "Assigned Assembly"
    )

    return {
        "is_field_officer": True,
        "page_title": "Field Dashboard",
        "page_subtitle": assembly_name,
        "context_assembly": assembly,
        "portal_access": portal_access,
        "officer_name": officer_name,
        "officer_initial": officer_initial,
        "officer_email": (
            request.user.email
            or "No email added"
        ),
        "officer_zone": assembly_name,
        "summary_cards": summary_cards,
        "quick_actions": quick_actions,
        "assignment_items": assignment_items,
        "recent_activity": recent_activity,
        "performance_rows": performance_rows,
        "total_properties": total_properties,
        "verified_count": verified_count,
        "view_all_assignments_url": (
            property_registry_url
        ),
    }


def _build_admin_context(
    request,
    assembly,
    portal_access,
):
    """
    Build the existing administrator Field Operations page.
    """

    officer_profiles = (
        UserProfile.objects
        .filter(role="field_officer")
        .select_related(
            "user",
            "assembly",
        )
    )

    visits_queryset = (
        FieldVisit.objects
        .select_related(
            "property",
            "property__owner",
            "property__assembly",
            "officer",
        )
        .order_by(
            "-visited_at",
            "-created_at",
        )
    )

    if assembly:
        officer_profiles = officer_profiles.filter(
            Q(assembly=assembly)
            | Q(assembly__isnull=True)
        )

        visits_queryset = visits_queryset.filter(
            property__assembly=assembly
        )

    assigned_properties_queryset = (
        Property.objects
        .select_related(
            "owner",
            "assembly",
            "registered_by",
        )
        .filter(
            registration_source="field",
            registered_by__isnull=False,
        )
    )

    if assembly:
        assigned_properties_queryset = (
            assigned_properties_queryset.filter(
                assembly=assembly
            )
        )

    assigned_statistics = (
        assigned_properties_queryset
        .values("registered_by_id")
        .annotate(
            assigned_count=Count(
                "id",
                distinct=True,
            ),
            completed_count=Count(
                "id",
                filter=Q(
                    verification_status="verified"
                ),
                distinct=True,
            ),
            last_verified_at=Max(
                "last_verified_at"
            ),
        )
    )

    assigned_statistics_map = {
        row["registered_by_id"]: row
        for row in assigned_statistics
    }

    officer_cards = []

    for profile in officer_profiles:
        statistics = assigned_statistics_map.get(
            profile.user_id,
            {},
        )

        assigned_count = (
            statistics.get(
                "assigned_count",
                0,
            )
            or 0
        )

        completed_count = (
            statistics.get(
                "completed_count",
                0,
            )
            or 0
        )

        last_verified_at = statistics.get(
            "last_verified_at"
        )

        last_visit_activity = (
            visits_queryset
            .filter(officer=profile.user)
            .aggregate(
                last_activity=Max("visited_at")
            )
            .get("last_activity")
        )

        available_activity_dates = [
            value
            for value in [
                last_verified_at,
                last_visit_activity,
            ]
            if value is not None
        ]

        last_activity = (
            max(available_activity_dates)
            if available_activity_dates
            else None
        )

        progress = 0

        if assigned_count > 0:
            progress = min(
                100,
                round(
                    (
                        completed_count
                        / assigned_count
                    )
                    * 100
                ),
            )

        officer_cards.append(
            {
                "name": _officer_name(
                    profile.user
                ),
                "code": (
                    profile.employee_id
                    or f"FO-{profile.user_id:03d}"
                ),
                "assembly_name": (
                    profile.assembly.name
                    if profile.assembly
                    else "Unassigned assembly"
                ),
                "assigned": assigned_count,
                "completed": completed_count,
                "progress": progress,
                "last_activity": (
                    _format_datetime(
                        last_activity
                    )
                ),
            }
        )

    officer_cards.sort(
        key=lambda card: (
            card["assigned"] > 0,
            card["progress"],
            card["completed"],
            card["name"],
        ),
        reverse=True,
    )

    recent_activities = []

    for visit in visits_queryset[:6]:
        visit_status = _visit_status(visit)
        property_record = visit.property

        visit_datetime = (
            visit.visited_at
            or visit.created_at
        )

        recent_activities.append(
            {
                "title": _visit_title(visit),
                "property_ref": getattr(
                    property_record,
                    "property_reference",
                    "N/A",
                ),
                "location": _visit_location(
                    property_record
                ),
                "description": (
                    _visit_description(visit)
                ),
                "officer": _officer_name(
                    visit.officer
                ),
                "datetime": _format_datetime(
                    visit_datetime
                ),
                "status": (
                    visit_status["label"]
                ),
                "status_class": (
                    visit_status["status_class"]
                ),
                "icon_name": (
                    visit_status["icon_name"]
                ),
                "icon_class": (
                    visit_status["icon_class"]
                ),
            }
        )

    return {
        "is_field_officer": False,
        "page_title": "Field Operations",
        "page_subtitle": (
            "Monitor field officer activities "
            "and verifications"
        ),
        "officer_cards": officer_cards,
        "recent_activities": recent_activities,
        "context_assembly": assembly,
        "portal_access": portal_access,
    }


@module_required("field_operations")
def field_operations_dashboard(request):
    assembly = _get_current_assembly(
        request
    )

    portal_access = get_allowed_modules(
        request.user
    )

    user_role = get_user_role(
        request.user
    )

    if user_role == "field_officer":
        context = _build_field_officer_context(
            request=request,
            assembly=assembly,
            portal_access=portal_access,
        )
    else:
        context = _build_admin_context(
            request=request,
            assembly=assembly,
            portal_access=portal_access,
        )

    return render(
        request,
        "field_operations/field_operations.html",
        context,
    )


@login_required
def field_officer_stats(request):
    if get_user_role(request.user) != "field_officer":
        return redirect("portal-login")

    assembly = _get_current_assembly(request)
    portal_access = get_allowed_modules(request.user)
    today = timezone.localdate()

    completed_statuses = [
        "verified",
        "approved",
        "completed",
    ]

    reviewed_statuses = completed_statuses + [
        "flagged",
        "possible_duplicate",
        "rejected",
        "disputed",
    ]

    def percent(part, total):
        if not total:
            return 0

        return min(
            100,
            round((part / total) * 100),
        )

    def month_bounds(months_back=0):
        month = today.month - months_back
        year = today.year

        while month <= 0:
            month += 12
            year -= 1

        start = today.replace(
            year=year,
            month=month,
            day=1,
        )

        if month == 12:
            end = start.replace(
                year=year + 1,
                month=1,
                day=1,
            )

        else:
            end = start.replace(
                month=month + 1,
            )

        return start, end

    def average_response_label(durations):
        if not durations:
            return "—"

        average_duration = (
            sum(durations, timedelta())
            / len(durations)
        )

        total_seconds = max(
            0,
            int(average_duration.total_seconds()),
        )

        if total_seconds < 60:
            return f"{total_seconds}s"

        if total_seconds < 3600:
            return f"{round(total_seconds / 60)}m"

        return f"{total_seconds / 3600:.1f}h"

    officer_visits = (
        FieldVisit.objects
        .select_related(
            "property",
            "property__owner",
            "property__assembly",
            "officer",
        )
        .filter(officer=request.user)
        .order_by(
            "-visited_at",
            "-created_at",
        )
    )

    if assembly:
        officer_visits = officer_visits.filter(
            property__assembly=assembly
        )

    visit_property_ids = officer_visits.values_list(
        "property_id",
        flat=True,
    )

    properties_queryset = (
        Property.objects
        .select_related(
            "owner",
            "assembly",
            "community_area",
            "registered_by",
            "applied_rate_policy",
        )
        .filter(
            Q(registered_by=request.user)
            | Q(id__in=visit_property_ids)
        )
        .distinct()
        .order_by("-created_at")
    )

    if assembly:
        properties_queryset = properties_queryset.filter(
            assembly=assembly
        )

    completed_properties = properties_queryset.filter(
        verification_status__in=completed_statuses
    )

    reviewed_properties = properties_queryset.filter(
        verification_status__in=reviewed_statuses
    )

    month_start, next_month_start = month_bounds(0)

    current_month_properties = properties_queryset.filter(
        Q(created_at__date__gte=month_start)
        & Q(created_at__date__lt=next_month_start)
    )

    current_month_completed = completed_properties.filter(
        Q(last_verified_at__date__gte=month_start)
        & Q(last_verified_at__date__lt=next_month_start)
    ).count()

    current_month_target = current_month_properties.count()

    if current_month_target == 0:
        current_month_target = current_month_completed

    month_progress_percent = percent(
        current_month_completed,
        current_month_target,
    )

    total_completed = completed_properties.count()
    total_reviewed = reviewed_properties.count()

    accuracy = percent(
        completed_properties.count(),
        total_reviewed,
    )

    response_durations = []

    for property_obj in completed_properties.filter(
        last_verified_at__isnull=False
    ):
        if property_obj.created_at:
            response_durations.append(
                property_obj.last_verified_at
                - property_obj.created_at
            )

    avg_response = average_response_label(
        response_durations
    )

    monthly_breakdown = []

    for months_back in [3, 2, 1, 0]:
        start, end = month_bounds(months_back)

        month_assigned = properties_queryset.filter(
            Q(created_at__date__gte=start)
            & Q(created_at__date__lt=end)
        ).count()

        month_completed = completed_properties.filter(
            Q(last_verified_at__date__gte=start)
            & Q(last_verified_at__date__lt=end)
        ).count()

        month_target = month_assigned or month_completed

        monthly_breakdown.append(
            {
                "month": start.strftime("%b %Y"),
                "completed": month_completed,
                "target": month_target,
                "percent": percent(
                    month_completed,
                    month_target,
                ),
            }
        )

    achievements = []

    for month_item in monthly_breakdown:
        if (
            month_item["target"] > 0
            and month_item["percent"] >= 100
        ):
            achievements.append(
                {
                    "title": "Perfect Month",
                    "description": (
                        "100% completion rate in "
                        f"{month_item['month']}"
                    ),
                    "date": month_item["month"],
                }
            )
            break

    if response_durations:
        average_duration = (
            sum(response_durations, timedelta())
            / len(response_durations)
        )

        if average_duration <= timedelta(hours=2):
            achievements.append(
                {
                    "title": "Fast Responder",
                    "description": (
                        "Average response time under "
                        "2 hours"
                    ),
                    "date": today.strftime("%b %Y"),
                }
            )

    if total_reviewed and accuracy >= 98:
        achievements.append(
            {
                "title": "Accuracy Expert",
                "description": (
                    f"{accuracy}% verification accuracy"
                ),
                "date": today.strftime("%b %Y"),
            }
        )

    recent_activity_map = {}

    for visit in officer_visits[:80]:
        property_record = getattr(
            visit,
            "property",
            None,
        )

        if not property_record:
            continue

        visit_status = _visit_status(visit)

        if visit_status["label"] == "Pending":
            continue

        activity_datetime = (
            visit.visited_at
            or visit.created_at
        )

        if not activity_datetime:
            continue

        activity_date = timezone.localtime(
            activity_datetime
        ).date()

        recent_activity_map.setdefault(
            activity_date,
            [],
        ).append(
            property_record.property_reference
        )

    if not recent_activity_map:
        for property_record in completed_properties.order_by(
            "-last_verified_at",
            "-updated_at",
            "-created_at",
        )[:80]:
            activity_datetime = (
                getattr(
                    property_record,
                    "last_verified_at",
                    None,
                )
                or getattr(
                    property_record,
                    "updated_at",
                    None,
                )
                or property_record.created_at
            )

            if not activity_datetime:
                continue

            activity_date = timezone.localtime(
                activity_datetime
            ).date()

            recent_activity_map.setdefault(
                activity_date,
                [],
            ).append(
                property_record.property_reference
            )

    recent_activity = []

    for activity_date in sorted(
        recent_activity_map.keys(),
        reverse=True,
    )[:5]:
        references = recent_activity_map[
            activity_date
        ]

        recent_activity.append(
            {
                "date": activity_date.strftime(
                    "%Y-%m-%d"
                ),
                "completed_count": len(references),
                "references": references[:8],
            }
        )

    officer_profiles = (
        UserProfile.objects
        .filter(
            role="field_officer",
            user__is_active=True,
        )
        .select_related(
            "user",
            "assembly",
        )
    )

    if assembly:
        officer_profiles = officer_profiles.filter(
            Q(assembly=assembly)
            | Q(assembly__isnull=True)
        )

    ranking_rows = []

    for profile in officer_profiles:
        profile_visits = FieldVisit.objects.filter(
            officer=profile.user
        )

        if assembly:
            profile_visits = profile_visits.filter(
                property__assembly=assembly
            )

        profile_visit_property_ids = (
            profile_visits.values_list(
                "property_id",
                flat=True,
            )
        )

        profile_properties = Property.objects.filter(
            Q(registered_by=profile.user)
            | Q(id__in=profile_visit_property_ids)
        )

        if assembly:
            profile_properties = profile_properties.filter(
                assembly=assembly
            )

        profile_completed = (
            profile_properties
            .filter(
                verification_status__in=completed_statuses
            )
            .distinct()
            .count()
        )

        ranking_rows.append(
            {
                "user_id": profile.user_id,
                "completed": profile_completed,
                "name": _officer_name(profile.user),
            }
        )

    ranking_rows.sort(
        key=lambda row: (
            row["completed"],
            row["name"],
        ),
        reverse=True,
    )

    rank = 1

    for index, row in enumerate(
        ranking_rows,
        start=1,
    ):
        if row["user_id"] == request.user.id:
            rank = index
            break

    rank_total = len(ranking_rows)

    officer_name = _officer_name(request.user)

    context = {
        "is_field_officer": True,
        "page_title": "My Performance",
        "page_subtitle": (
            "Track your verification stats "
            "and achievements"
        ),
        "portal_access": portal_access,
        "context_assembly": assembly,
        "officer_name": officer_name,
        "officer_initial": (
            officer_name[0].upper()
            if officer_name
            else "F"
        ),
        "officer_email": (
            request.user.email
            or "No email added"
        ),
        "officer_zone": (
            assembly.name
            if assembly
            else "Assigned Assembly"
        ),

        "month_progress_percent": month_progress_percent,
        "month_completed": current_month_completed,
        "month_target": current_month_target,
        "total_completed": total_completed,
        "accuracy": accuracy,
        "avg_response": avg_response,
        "achievements_count": len(achievements),

        "monthly_breakdown": monthly_breakdown,
        "achievements": achievements,
        "recent_activity": recent_activity,

        "rank": rank,
        "rank_total": rank_total,
        "district_name": (
            assembly.name
            if assembly
            else "Assigned Assembly"
        ),
    }

    return render(
        request,
        "field_operations/field_officer_stats.html",
        context,
    )
