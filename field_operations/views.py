from datetime import timedelta
from io import BytesIO
import logging

from django.core.files.base import ContentFile
from django.db.models import Case, Count, IntegerField, Max, Q, Value, When
from django.http import request
from django.shortcuts import render, redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.contrib import messages
from PIL import Image, UnidentifiedImageError

from django.contrib.auth.decorators import login_required

from admins.access import get_allowed_modules, get_user_role, landing_url_for_user
from admins.decorators import module_required
from admins.models import Assembly, UserProfile
from field_operations.models import FieldAssignment, FieldVisit
from properties.models import Property

try:
    from properties.models import PropertyPhoto
except ImportError:
    PropertyPhoto = None

logger = logging.getLogger(__name__)

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
    """
    Return a safe display name for current, deleted,
    or unassigned field officers.
    """

    if user is None:
        return "Unassigned officer"

    get_full_name = getattr(
        user,
        "get_full_name",
        None,
    )

    full_name = ""

    if callable(get_full_name):
        full_name = (
            get_full_name()
            or ""
        ).strip()

    username = (
        getattr(user, "username", "")
        or ""
    ).strip()

    email = (
        getattr(user, "email", "")
        or ""
    ).strip()

    return (
        full_name
        or username
        or email
        or "Unassigned officer"
    )


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

    outcome = (
        getattr(visit, "outcome", "")
        or ""
    ).strip().lower()

    outcome_mapping = {
        "compliant": {
            "label": "Verified",
            "status_class": "status-verified",
            "icon_class": "activity-green",
            "icon_name": "check",
        },
        "notice_served": {
            "label": "Discrepancy",
            "status_class": "status-discrepancy",
            "icon_class": "activity-red",
            "icon_name": "warning",
        },
        "follow_up_required": {
            "label": "Pending",
            "status_class": "status-pending",
            "icon_class": "activity-yellow",
            "icon_name": "clock",
        },
        "property_not_found": {
            "label": "Discrepancy",
            "status_class": "status-discrepancy",
            "icon_class": "activity-red",
            "icon_name": "warning",
        },
    }

    if outcome in outcome_mapping:
        return outcome_mapping[outcome]

    status_text = (
        f"{outcome} "
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


def _active_field_assignments(request, assembly):
    queryset = (
        FieldAssignment.objects
        .select_related(
            "property",
            "property__owner",
            "property__assembly",
            "assembly",
            "officer",
            "assigned_by",
        )
        .filter(
            officer=request.user,
            status__in=[
                "assigned",
                "in_progress",
            ],
        )
        .order_by(
            "-assigned_at",
            "-created_at",
        )
    )

    if assembly:
        queryset = queryset.filter(
            assembly=assembly,
        )

    return queryset


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

    verify_property_url = _safe_reverse(
        "field_operations:field-officer-verify",
        fallback=property_registry_url,
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

    assignments_url = _safe_reverse(
        "field_operations:field-officer-assignments",
        fallback=verify_property_url,
    )

    stats_url = _safe_reverse(
        "field_operations:field-officer-stats",
        fallback=verify_property_url,
    )

    quick_actions = [
        {
            "label": "Assignments",
            "url": assignments_url,
            "icon_name": "assignment",
        },
        {
            "label": "Submit Verification",
            "url": verify_property_url,
            "icon_name": "verify",
        },
        {
            "label": "Register Property",
            "url": add_property_url,
            "icon_name": "property",
        },
        {
            "label": "My Statistics",
            "url": stats_url,
            "icon_name": "stats",
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
            assignments_url
        ),
    }


def _build_admin_context(
    request,
    assembly,
    portal_access,
):
    """
    Administrator Field Officers dashboard.

    Assignment statistics come from FieldAssignment,
    not from Property.registered_by.
    """

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

    assignments_queryset = (
        FieldAssignment.objects
        .select_related(
            "property",
            "property__owner",
            "property__assembly",
            "officer",
            "assigned_by",
            "assembly",
        )
        .order_by(
            "-assigned_at",
            "-created_at",
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

        assignments_queryset = (
            assignments_queryset.filter(
                assembly=assembly,
            )
        )

        visits_queryset = visits_queryset.filter(
            property__assembly=assembly,
        )

    assignment_statistics = (
        assignments_queryset
        .values("officer_id")
        .annotate(
            active_count=Count(
                "id",
                filter=Q(
                    status__in=[
                        "assigned",
                        "in_progress",
                    ],
                ),
            ),
            completed_count=Count(
                "id",
                filter=Q(
                    status="completed",
                ),
            ),
            last_assigned_at=Max(
                "assigned_at",
            ),
            last_completed_at=Max(
                "completed_at",
            ),
        )
    )

    statistics_map = {
        row["officer_id"]: row
        for row in assignment_statistics
    }

    officer_cards = []

    for profile in officer_profiles:
        statistics = statistics_map.get(
            profile.user_id,
            {},
        )

        assigned_count = (
            statistics.get(
                "active_count",
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

        last_assigned_at = statistics.get(
            "last_assigned_at",
        )

        last_completed_at = statistics.get(
            "last_completed_at",
        )

        last_visit_activity = (
            visits_queryset
            .filter(
                officer=profile.user,
            )
            .aggregate(
                last_activity=Max(
                    "visited_at",
                )
            )
            .get(
                "last_activity",
            )
        )

        activity_dates = [
            value
            for value in [
                last_assigned_at,
                last_completed_at,
                last_visit_activity,
            ]
            if value is not None
        ]

        last_activity = (
            max(activity_dates)
            if activity_dates
            else None
        )

        total_work = (
            assigned_count
            + completed_count
        )

        progress = 0

        if total_work:
            progress = round(
                (
                    completed_count
                    / total_work
                )
                * 100
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
                "progress": min(
                    progress,
                    100,
                ),
                "last_activity": (
                    _format_datetime(
                        last_activity
                    )
                ),
            }
        )

    officer_cards.sort(
        key=lambda card: (
            card["assigned"],
            card["completed"],
            card["name"],
        ),
        reverse=True,
    )

    recent_activities = []

    for visit in visits_queryset[:6]:
        visit_status = _visit_status(
            visit
        )

        property_record = (
            visit.property
        )

        visit_datetime = (
            visit.visited_at
            or visit.created_at
        )

        recent_activities.append(
            {
                "title": _visit_title(
                    visit
                ),
                "property_ref": getattr(
                    property_record,
                    "property_reference",
                    "N/A",
                ),
                "location": _visit_location(
                    property_record
                ),
                "description": (
                    _visit_description(
                        visit
                    )
                ),
                "officer": _officer_name(
                    visit.officer
                ),
                "datetime": _format_datetime(
                    visit_datetime
                ),
                "status": (
                    visit_status[
                        "label"
                    ]
                ),
                "status_class": (
                    visit_status[
                        "status_class"
                    ]
                ),
                "icon_name": (
                    visit_status[
                        "icon_name"
                    ]
                ),
                "icon_class": (
                    visit_status[
                        "icon_class"
                    ]
                ),
            }
        )

    return {
        "is_field_officer": False,
        "page_title": "Field Operations",
        "page_subtitle": (
            "Assign properties and monitor "
            "field officer verification work"
        ),
        "officer_cards": officer_cards,
        "recent_activities": recent_activities,
        "context_assembly": assembly,
        "portal_access": portal_access,

        "assign_property_url": reverse(
            (
                "field_operations:"
                "assign-field-officer-property"
            )
        ),
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
    user_role = get_user_role(request.user)

    if user_role != "field_officer":
        return redirect(landing_url_for_user(request.user))

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

    def in_date_range(field_name, start, end):
        return Q(**{
            f"{field_name}__date__gte": start,
            f"{field_name}__date__lt": end,
        })

    def completed_in_range(queryset, start, end):
        """
        Count completed work inside a month.

        Prefer last_verified_at when it exists. If older records are already
        marked verified but last_verified_at was never saved, fall back to
        updated_at, then created_at. This prevents a verified property from
        showing as 0% just because last_verified_at is blank.
        """

        return queryset.filter(
            in_date_range("last_verified_at", start, end)
            | (
                Q(last_verified_at__isnull=True)
                & in_date_range("updated_at", start, end)
            )
            | (
                Q(last_verified_at__isnull=True)
                & Q(updated_at__isnull=True)
                & in_date_range("created_at", start, end)
            )
        ).distinct()

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

    officer_assignments = (
        FieldAssignment.objects
        .filter(
            officer=request.user,
        )
    )

    if assembly:
        officer_assignments = (
            officer_assignments.filter(
                assembly=assembly,
            )
        )

    assigned_property_ids = (
        officer_assignments.values_list(
            "property_id",
            flat=True,
        )
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
            id__in=assigned_property_ids,
        )
        .distinct()
        .order_by(
            "-created_at"
        )
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
        in_date_range("created_at", month_start, next_month_start)
    )

    current_month_assigned = current_month_properties.count()

    current_month_completed = completed_in_range(
        completed_properties,
        month_start,
        next_month_start,
    ).count()

    current_month_target = current_month_assigned or current_month_completed

    month_progress_percent = percent(
        current_month_completed,
        current_month_target,
    )

    total_completed = completed_properties.count()
    total_reviewed = reviewed_properties.count()

    accuracy = percent(
        total_completed,
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
            in_date_range("created_at", start, end)
        ).count()

        month_completed = completed_in_range(
            completed_properties,
            start,
            end,
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

    perfect_month = next(
        (
            month_item
            for month_item in reversed(monthly_breakdown)
            if (
                month_item["target"] > 0
                and month_item["percent"] >= 100
            )
        ),
        None,
    )

    if perfect_month:
        achievements.append(
            {
                "title": "Perfect Month",
                "description": (
                    "100% completion rate in "
                    f"{perfect_month['month']}"
                ),
                "date": perfect_month["month"],
            }
        )

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

    all_completed_properties = Property.objects.filter(
        verification_status__in=completed_statuses
    )

    if assembly:
        all_completed_properties = all_completed_properties.filter(
            assembly=assembly
        )

    all_completed_visit_property_ids = FieldVisit.objects.filter(
        property__verification_status__in=completed_statuses
    )

    if assembly:
        all_completed_visit_property_ids = all_completed_visit_property_ids.filter(
            property__assembly=assembly
        )

    completed_totals_by_user = {}

    for property_id, registered_by_id in all_completed_properties.values_list(
        "id",
        "registered_by_id",
    ):
        if registered_by_id:
            completed_totals_by_user.setdefault(
                registered_by_id,
                set(),
            ).add(property_id)

    for property_id, officer_id in all_completed_visit_property_ids.values_list(
        "property_id",
        "officer_id",
    ).distinct():
        if officer_id:
            completed_totals_by_user.setdefault(
                officer_id,
                set(),
            ).add(property_id)

    ranking_rows = [
        {
            "user_id": profile.user_id,
            "completed": len(
                completed_totals_by_user.get(
                    profile.user_id,
                    set(),
                )
            ),
            "name": _officer_name(profile.user),
        }
        for profile in officer_profiles
    ]

    ranking_rows.sort(
        key=lambda row: (
            row["completed"],
            row["name"],
        ),
        reverse=True,
    )

    rank_total = len(ranking_rows)
    rank = rank_total + 1

    for index, row in enumerate(
        ranking_rows,
        start=1,
    ):
        if row["user_id"] == request.user.id:
            rank = index
            break

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


@login_required
def field_officer_assignments(request):
    if (
        get_user_role(request.user)
        != "field_officer"
    ):
        messages.error(
            request,
            "Only field officers can view assignments.",
        )

        return redirect(
            landing_url_for_user(
                request.user
            )
        )

    assembly = _get_current_assembly(
        request
    )

    assignments = (
        FieldAssignment.objects
        .select_related(
            "property",
            "property__owner",
            "property__assembly",
            "assembly",
            "assigned_by",
        )
        .filter(
            officer=request.user,
        )
        .order_by(
            Case(
                When(
                    status="assigned",
                    then=Value(0),
                ),
                When(
                    status="in_progress",
                    then=Value(1),
                ),
                When(
                    status="completed",
                    then=Value(2),
                ),
                default=Value(3),
                output_field=IntegerField(),
            ),
            "due_date",
            "-assigned_at",
        )
    )

    if assembly:
        assignments = assignments.filter(
            assembly=assembly,
        )

    portal_access = get_allowed_modules(
        request.user
    )

    officer_name = _officer_name(
        request.user
    )

    return render(
        request,
        (
            "field_operations/"
            "field_officer_assignments.html"
        ),
        {
            "page_title": "My Assignments",
            "page_subtitle": (
                "Properties assigned to you "
                "for field verification."
            ),
            "assignments": assignments,

            "active_count": (
                assignments.filter(
                    status__in=[
                        "assigned",
                        "in_progress",
                    ]
                ).count()
            ),

            "completed_count": (
                assignments.filter(
                    status="completed",
                ).count()
            ),

            "officer_name": officer_name,

            "officer_initial": (
                officer_name[:1].upper()
                or "F"
            ),

            "officer_zone": (
                assembly.name
                if assembly
                else "Assigned Assembly"
            ),

            "context_assembly": assembly,
            "portal_access": portal_access,
            "is_field_officer": True,
        },
    )


# def _model_has_field(model, field_name):
#     return field_name in {
#         field.name
#         for field in model._meta.get_fields()
#     }


# def _get_field_officer_property_queryset(request, assembly):
#     officer_visits = FieldVisit.objects.filter(
#         officer=request.user,
#     )

#     if assembly:
#         officer_visits = officer_visits.filter(
#             property__assembly=assembly,
#         )

#     visit_property_ids = officer_visits.values_list(
#         "property_id",
#         flat=True,
#     )

#     properties_queryset = (
#         Property.objects
#         .select_related(
#             "owner",
#             "assembly",
#             "community_area",
#             "registered_by",
#         )
#         .filter(
#             Q(registered_by=request.user)
#             | Q(id__in=visit_property_ids)
#         )
#         .distinct()
#     )

#     if assembly:
#         properties_queryset = properties_queryset.filter(
#             assembly=assembly,
#         )

#     return properties_queryset


# def _save_property_photos(request, property_obj):
#     if PropertyPhoto is None:
#         return 0

#     photos = request.FILES.getlist("photos")

#     if not photos:
#         return 0

#     field_names = {
#         field.name
#         for field in PropertyPhoto._meta.get_fields()
#     }

#     file_field_name = None

#     for candidate in [
#         "image",
#         "photo",
#         "file",
#         "photo_file",
#         "property_photo",
#     ]:
#         if candidate in field_names:
#             file_field_name = candidate
#             break

#     if not file_field_name:
#         return 0

#     saved_count = 0

#     for uploaded_file in photos:
#         photo_kwargs = {
#             file_field_name: uploaded_file,
#         }

#         if "property" in field_names:
#             photo_kwargs["property"] = property_obj

#         if "uploaded_by" in field_names:
#             photo_kwargs["uploaded_by"] = request.user

#         if "caption" in field_names:
#             photo_kwargs["caption"] = "Field verification photo"

#         if "description" in field_names:
#             photo_kwargs["description"] = "Uploaded during field verification"

#         try:
#             PropertyPhoto.objects.create(**photo_kwargs)
#             saved_count += 1
#         except Exception:
#             continue

#     return saved_count


# def _create_field_visit_record(
#     request,
#     property_obj,
#     verification_type,
#     verification_status,
#     owner_present,
#     notes,
#     latitude,
#     longitude,
# ):
#     field_names = {
#         field.name
#         for field in FieldVisit._meta.get_fields()
#     }

#     visit_kwargs = {}

#     if "property" in field_names:
#         visit_kwargs["property"] = property_obj

#     if "officer" in field_names:
#         visit_kwargs["officer"] = request.user

#     if "visited_at" in field_names:
#         visit_kwargs["visited_at"] = timezone.now()

#     if "visit_type" in field_names:
#         visit_kwargs["visit_type"] = verification_type

#     if "outcome" in field_names:
#         visit_kwargs["outcome"] = verification_status

#     if "notes" in field_names:
#         owner_label = "Yes" if owner_present == "yes" else "No"
#         visit_kwargs["notes"] = (
#             f"Owner present: {owner_label}\n\n"
#             f"{notes}"
#         ).strip()

#     if latitude and "latitude" in field_names:
#         visit_kwargs["latitude"] = latitude

#     if longitude and "longitude" in field_names:
#         visit_kwargs["longitude"] = longitude

#     if "gps_latitude" in field_names and latitude:
#         visit_kwargs["gps_latitude"] = latitude

#     if "gps_longitude" in field_names and longitude:
#         visit_kwargs["gps_longitude"] = longitude

#     if visit_kwargs:
#         try:
#             return FieldVisit.objects.create(
#                 **visit_kwargs,
#             )
#         except Exception:
#             return None

#     return None


# @login_required
# def field_officer_verify_property(request, property_id=None):
#     user_role = get_user_role(request.user)

#     if user_role != "field_officer":
#         return redirect(landing_url_for_user(request.user))

#     assembly = _get_current_assembly(request)
#     portal_access = get_allowed_modules(request.user)

#     officer_name = _officer_name(request.user)
#     officer_initial = officer_name[0].upper() if officer_name else "F"
#     officer_zone = assembly.name if assembly else "Assigned Assembly"

#     property_queryset = _get_field_officer_property_queryset(
#         request=request,
#         assembly=assembly,
#     )

#     property_obj = None

#     if property_id:
#         property_obj = property_queryset.filter(
#             pk=property_id,
#         ).first()

#         if not property_obj:
#             messages.error(
#                 request,
#                 "You do not have access to verify this property.",
#             )
#             return redirect("field_operations:field-operations")

#     verification_type_choices = [
#         ("property_verification", "Property Verification"),
#         ("site_assessment", "Site Assessment"),
#         ("payment_verification", "Payment Verification"),
#         ("dispute_investigation", "Dispute Investigation"),
#         ("follow_up", "Follow-up Visit"),
#     ]

#     verification_status_choices = [
#         ("verified", "Verified"),
#         ("pending", "Pending"),
#         ("under_review", "Under Review"),
#         ("flagged", "Flagged"),
#         ("possible_duplicate", "Possible Duplicate"),
#         ("rejected", "Rejected"),
#     ]

#     form_error = ""

#     form_values = {
#         "property_reference": (
#             property_obj.property_reference
#             if property_obj
#             else ""
#         ),
#         "verification_type": "property_verification",
#         "verification_status": (
#             property_obj.verification_status
#             if property_obj
#             else ""
#         ),
#         "owner_present": "yes",
#         "notes": "",
#         "latitude": (
#             str(property_obj.latitude)
#             if property_obj and property_obj.latitude is not None
#             else ""
#         ),
#         "longitude": (
#             str(property_obj.longitude)
#             if property_obj and property_obj.longitude is not None
#             else ""
#         ),
#     }

#     if request.method == "POST":
#         form_values.update(
#             {
#                 "property_reference": request.POST.get(
#                     "property_reference",
#                     "",
#                 ).strip(),
#                 "verification_type": request.POST.get(
#                     "verification_type",
#                     "",
#                 ).strip(),
#                 "verification_status": request.POST.get(
#                     "verification_status",
#                     "",
#                 ).strip(),
#                 "owner_present": request.POST.get(
#                     "owner_present",
#                     "yes",
#                 ).strip(),
#                 "notes": request.POST.get(
#                     "notes",
#                     "",
#                 ).strip(),
#                 "latitude": request.POST.get(
#                     "latitude",
#                     "",
#                 ).strip(),
#                 "longitude": request.POST.get(
#                     "longitude",
#                     "",
#                 ).strip(),
#             }
#         )

#         if not property_obj:
#             property_obj = property_queryset.filter(
#                 property_reference__iexact=form_values["property_reference"],
#             ).first()

#         if not property_obj:
#             form_error = "Property ID not found or not assigned to you."

#         elif not form_values["verification_type"]:
#             form_error = "Select a verification type."

#         elif not form_values["verification_status"]:
#             form_error = "Select a verification status."

#         elif not form_values["notes"]:
#             form_error = "Enter verification notes."

#         else:
#             property_obj.verification_status = form_values[
#                 "verification_status"
#             ]

#             update_fields = [
#                 "verification_status",
#             ]

#             completed_statuses = {
#                 "verified",
#                 "approved",
#                 "completed",
#             }

#             if (
#                 form_values["verification_status"]
#                 in completed_statuses
#             ):
#                 property_obj.last_verified_at = timezone.now()
#                 update_fields.append("last_verified_at")

#             if form_values["latitude"]:
#                 property_obj.latitude = form_values["latitude"]
#                 update_fields.append("latitude")

#             if form_values["longitude"]:
#                 property_obj.longitude = form_values["longitude"]
#                 update_fields.append("longitude")

#             property_obj.save(
#                 update_fields=list(set(update_fields)),
#             )

#             _create_field_visit_record(
#                 request=request,
#                 property_obj=property_obj,
#                 verification_type=form_values["verification_type"],
#                 verification_status=form_values["verification_status"],
#                 owner_present=form_values["owner_present"],
#                 notes=form_values["notes"],
#                 latitude=form_values["latitude"],
#                 longitude=form_values["longitude"],
#             )

#             photo_count = _save_property_photos(
#                 request=request,
#                 property_obj=property_obj,
#             )

#             if photo_count:
#                 messages.success(
#                     request,
#                     f"Verification submitted successfully. {photo_count} photo(s) uploaded.",
#                 )
#             else:
#                 messages.success(
#                     request,
#                     "Verification submitted successfully.",
#                 )

#             return redirect(
#                 "field_operations:field-officer-stats"
#             )

#     dashboard_url = _safe_reverse(
#         "field_operations:field-operations",
#     )

#     verify_url = _safe_reverse(
#         "field_operations:field-officer-verify",
#         fallback=dashboard_url,
#     )

#     stats_url = _safe_reverse(
#         "field_operations:field-officer-stats",
#         fallback=dashboard_url,
#     )

#     profile_url = _safe_reverse(
#         "admins:settings",
#         fallback=dashboard_url,
#     )

#     context = {
#         "is_field_officer": True,
#         "page_title": "Submit Verification",
#         "page_subtitle": "Complete field verification report",
#         "portal_access": portal_access,
#         "context_assembly": assembly,
#         "officer_name": officer_name,
#         "officer_initial": officer_initial,
#         "officer_zone": officer_zone,
#         "property_obj": property_obj,
#         "verification_type_choices": verification_type_choices,
#         "verification_status_choices": verification_status_choices,
#         "form_error": form_error,
#         "cancel_url": dashboard_url,
#         "dashboard_url": dashboard_url,
#         "tasks_url": dashboard_url,
#         "verify_url": verify_url,
#         "stats_url": stats_url,
#         "profile_url": profile_url,
#         **form_values,
#     }

#     return render(
#         request,
#         "field_operations/field_officer_verify.html",
#         context,
#     )

# def assign_field_officer_property(request):
#     from django.contrib import messages
#     from django.db.models import Q
#     from django.shortcuts import get_object_or_404, redirect, render
#     from django.utils import timezone

#     from admins.access import get_allowed_modules, get_user_role, landing_url_for_user
#     from admins.models import Assembly, UserProfile
#     from properties.models import Property
#     from .models import FieldAssignment

#     if not request.user.is_authenticated:
#         return redirect("portal-login")

#     user_role = get_user_role(request.user)

#     allowed_roles = {
#         "sys_admin",
#         "revenue_admin",
#         "report_officer",
#     }

#     if user_role not in allowed_roles:
#         messages.error(
#             request,
#             "You are not authorized to assign properties to field officers.",
#         )
#         return redirect(landing_url_for_user(request.user))

#     assembly = None
#     assembly_id = request.session.get("active_assembly_id")

#     if assembly_id:
#         assembly = Assembly.objects.filter(
#             id=assembly_id,
#             is_active=True,
#         ).first()

#     if not assembly:
#         profile = getattr(request.user, "profile", None)

#         if profile and profile.assembly_id:
#             assembly = Assembly.objects.filter(
#                 id=profile.assembly_id,
#                 is_active=True,
#             ).first()

#     properties_queryset = (
#         Property.objects
#         .select_related("owner", "assembly")
#         .order_by("-created_at")
#     )

#     officers_queryset = (
#         UserProfile.objects
#         .select_related("user", "assembly")
#         .filter(
#             role="field_officer",
#             user__is_active=True,
#         )
#         .order_by("user__first_name", "user__last_name", "user__username")
#     )

#     assignments_queryset = (
#         FieldAssignment.objects
#         .select_related(
#             "property",
#             "property__owner",
#             "officer",
#             "assembly",
#             "assigned_by",
#         )
#         .order_by("-assigned_at", "-created_at")
#     )

#     if assembly:
#         properties_queryset = properties_queryset.filter(
#             assembly=assembly,
#         )

#         officers_queryset = officers_queryset.filter(
#             Q(assembly=assembly)
#             | Q(allowed_assemblies=assembly)
#         ).distinct()

#         assignments_queryset = assignments_queryset.filter(
#             assembly=assembly,
#         )

#     if request.method == "POST":
#         property_id = request.POST.get("property_id")
#         officer_id = request.POST.get("officer_id")
#         priority = request.POST.get("priority") or "medium"
#         due_date = request.POST.get("due_date") or None
#         notes = request.POST.get("notes") or ""

#         if not property_id or not officer_id:
#             messages.error(
#                 request,
#                 "Please select both a property and a field officer.",
#             )
#             return redirect("field_operations:assign-field-officer-property")

#         property_obj = get_object_or_404(
#             properties_queryset,
#             id=property_id,
#         )

#         officer_profile = get_object_or_404(
#             officers_queryset,
#             user_id=officer_id,
#         )

#         existing_assignment = (
#             FieldAssignment.objects
#             .filter(
#                 property=property_obj,
#                 officer=officer_profile.user,
#                 status__in=["assigned", "in_progress"],
#             )
#             .first()
#         )

#         if existing_assignment:
#             existing_assignment.priority = priority
#             existing_assignment.due_date = due_date
#             existing_assignment.notes = notes
#             existing_assignment.assigned_by = request.user
#             existing_assignment.save(
#                 update_fields=[
#                     "priority",
#                     "due_date",
#                     "notes",
#                     "assigned_by",
#                     "updated_at",
#                 ]
#             )

#             messages.success(
#                 request,
#                 "Existing field assignment updated successfully.",
#             )
#         else:
#             FieldAssignment.objects.create(
#                 assembly=property_obj.assembly,
#                 property=property_obj,
#                 officer=officer_profile.user,
#                 assigned_by=request.user,
#                 status="assigned",
#                 priority=priority,
#                 due_date=due_date,
#                 notes=notes,
#                 assigned_at=timezone.now(),
#             )

#             messages.success(
#                 request,
#                 "Property assigned to field officer successfully.",
#             )

#         return redirect("field_operations:assign-field-officer-property")

#     portal_access = get_allowed_modules(request.user)

#     context = {
#         "page_title": "Assign Field Officer",
#         "page_subtitle": "Assign properties to field officers for verification",
#         "context_assembly": assembly,
#         "properties": properties_queryset[:200],
#         "officers": officers_queryset,
#         "assignments": assignments_queryset[:50],
#         "portal_access": portal_access,
#         "allowed_modules": portal_access,
#         "user_role": user_role,
#     }

#     return render(
#         request,
#         "field_operations/assign_field_officer_property.html",
#         context,
#     )

def _prms_current_assembly(request):
    from admins.models import Assembly

    assembly_id = request.session.get("active_assembly_id")

    if assembly_id:
        assembly = Assembly.objects.filter(
            id=assembly_id,
            is_active=True,
        ).first()

        if assembly:
            return assembly

    profile = getattr(request.user, "profile", None)

    if profile and getattr(profile, "assembly_id", None):
        return Assembly.objects.filter(
            id=profile.assembly_id,
            is_active=True,
        ).first()

    return None


def _prms_model_has_field(model, field_name):
    return field_name in {
        field.name
        for field in model._meta.get_fields()
    }


def _prms_user_display_name(user):
    full_name = user.get_full_name().strip()
    return full_name or user.username


def _prms_field_officer_profiles(assembly=None):
    from django.db.models import Q

    from admins.models import UserProfile

    officers = (
        UserProfile.objects
        .select_related("user", "assembly")
        .filter(
            role="field_officer",
            user__is_active=True,
        )
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username",
        )
    )

    if assembly:
        if hasattr(UserProfile, "allowed_assemblies"):
            officers = officers.filter(
                Q(assembly=assembly)
                | Q(allowed_assemblies=assembly)
            ).distinct()
        else:
            officers = officers.filter(
                Q(assembly=assembly)
                | Q(assembly__isnull=True)
            ).distinct()

    return officers


def _prms_property_outstanding_amount(property_obj):
    from decimal import Decimal

    from django.db.models import (
        DecimalField,
        ExpressionWrapper,
        F,
        Sum,
        Value,
    )
    from django.db.models.functions import Coalesce

    from billing.models import Bill

    money_field = DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    balance_expr = ExpressionWrapper(
        F("amount_due") - F("amount_paid"),
        output_field=money_field,
    )

    return (
        Bill.objects
        .filter(property_record=property_obj)
        .exclude(status__in=["paid", "cancelled"])
        .aggregate(
            total=Coalesce(
                Sum(balance_expr),
                Value(
                    Decimal("0.00"),
                    output_field=money_field,
                ),
            )
        )["total"]
        or Decimal("0.00")
    )


def _prms_parse_coordinate(value, coordinate_name):
    from decimal import Decimal, InvalidOperation

    from django.core.exceptions import ValidationError

    value = (value or "").strip()

    if not value:
        return None

    try:
        coordinate = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(
            f"Enter a valid {coordinate_name.lower()} coordinate."
        ) from exc

    if (
        coordinate_name == "Latitude"
        and not Decimal("-90") <= coordinate <= Decimal("90")
    ):
        raise ValidationError(
            "Latitude must be between -90 and 90."
        )

    if (
        coordinate_name == "Longitude"
        and not Decimal("-180") <= coordinate <= Decimal("180")
    ):
        raise ValidationError(
            "Longitude must be between -180 and 180."
        )

    return coordinate


def _prms_create_field_visit(
    request,
    property_obj,
    verification_type,
    verification_status,
    owner_present,
    notes,
    latitude,
    longitude,
):
    visit_type_map = {
        "property_verification": "verification",
        "site_assessment": "verification",
        "payment_verification": "verification",
        "dispute_investigation": "follow_up",
        "follow_up": "follow_up",
    }

    outcome_map = {
        "verified": "compliant",
        "pending": "follow_up_required",
        "under_review": "follow_up_required",
        "flagged": "follow_up_required",
        "possible_duplicate": "follow_up_required",
        "rejected": "property_not_found",
    }

    owner_label = (
        "Yes"
        if owner_present == "yes"
        else "No"
    )

    return FieldVisit.objects.create(
        assembly=property_obj.assembly,
        property=property_obj,
        officer=request.user,

        visit_type=visit_type_map.get(
            verification_type,
            "verification",
        ),

        submitted_verification_type=(
            verification_type
        ),

        submitted_verification_status=(
            verification_status
        ),

        payment_status_seen="unknown",

        outcome=outcome_map.get(
            verification_status,
            "follow_up_required",
        ),

        amount_outstanding_snapshot=(
            _prms_property_outstanding_amount(
                property_obj
            )
        ),

        visited_at=timezone.now(),

        notes=(
            f"Owner present: {owner_label}\n\n"
            f"{notes}"
        ).strip(),

        latitude=latitude,
        longitude=longitude,
    )

def _prms_save_property_photos(
    request,
    property_obj,
):
    from django.core.exceptions import ValidationError

    from properties.models import PropertyPhoto

    photos = request.FILES.getlist("photos")

    if not photos:
        return 0

    if len(photos) > 5:
        raise ValidationError(
            "Upload no more than 5 verification photos."
        )

    saved_count = 0

    for uploaded_file in photos:
        content_type = (
            getattr(
                uploaded_file,
                "content_type",
                "",
            )
            or ""
        ).lower()

        if (
            content_type
            and not content_type.startswith("image/")
        ):
            raise ValidationError(
                "Verification uploads must be image files."
            )

        if uploaded_file.size > 8 * 1024 * 1024:
            raise ValidationError(
                (
                    f"{uploaded_file.name} is larger than "
                    "the 8 MB upload limit."
                )
            )

        PropertyPhoto.objects.create(
            property=property_obj,
            image=uploaded_file,
            uploaded_by=request.user,
            caption="Field verification photo",
        )

        saved_count += 1

    return saved_count


def assign_field_officer_property(request):
    from datetime import date

    from django.core.exceptions import ValidationError
    from django.db import transaction

    if not request.user.is_authenticated:
        return redirect("admin-login")

    user_role = get_user_role(request.user)

    allowed_roles = {
        "sys_admin",
        "revenue_admin",
        "property_officer",
    }

    if user_role not in allowed_roles:
        messages.error(
            request,
            "You are not authorized to assign properties to field officers.",
        )
        return redirect(
            landing_url_for_user(request.user)
        )

    assembly = _prms_current_assembly(request)

    properties_queryset = (
        Property.objects
        .select_related(
            "owner",
            "assembly",
        )
        .filter(is_active=True)
        .exclude(
            verification_status="verified",
        )
        .order_by(
            "property_reference"
        )
    )

    if assembly:
        properties_queryset = (
            properties_queryset.filter(
                assembly=assembly,
            )
        )

    officers_queryset = (
        _prms_field_officer_profiles(
            assembly
        )
    )

    assignments_queryset = (
        FieldAssignment.objects
        .select_related(
            "property",
            "property__owner",
            "officer",
            "assembly",
            "assigned_by",
        )
        .order_by(
            "-assigned_at",
            "-created_at",
        )
    )

    if assembly:
        assignments_queryset = (
            assignments_queryset.filter(
                assembly=assembly,
            )
        )

    if request.method == "POST":
        property_ids = [
            value.strip()
            for value
            in request.POST.getlist(
                "property_ids"
            )
            if value.strip()
        ]

        officer_id = (
            request.POST.get("officer_id")
            or ""
        ).strip()

        priority = (
            request.POST.get("priority")
            or "medium"
        ).strip()

        due_date_value = (
            request.POST.get("due_date")
            or ""
        ).strip()

        notes = (
            request.POST.get("notes")
            or ""
        ).strip()

        try:
            if not property_ids:
                raise ValidationError(
                    "Select at least one property."
                )

            if not officer_id:
                raise ValidationError(
                    "Select a field officer."
                )

            allowed_priorities = {
                value
                for value, _label
                in FieldAssignment.PRIORITY_CHOICES
            }

            if priority not in allowed_priorities:
                raise ValidationError(
                    "Select a valid assignment priority."
                )

            due_date = None

            if due_date_value:
                try:
                    due_date = (
                        date.fromisoformat(
                            due_date_value
                        )
                    )
                except ValueError as exc:
                    raise ValidationError(
                        "Enter a valid assignment due date."
                    ) from exc

                if due_date < timezone.localdate():
                    raise ValidationError(
                        "The assignment due date cannot be in the past."
                    )

            officer_profile = (
                officers_queryset.filter(
                    user_id=officer_id,
                )
                .first()
            )

            if not officer_profile:
                raise ValidationError(
                    "Select a valid field officer."
                )

            unique_property_ids = list(
                dict.fromkeys(
                    property_ids
                )
            )

            selected_properties = list(
                properties_queryset.filter(
                    id__in=unique_property_ids
                )
            )

            if (
                len(selected_properties)
                != len(unique_property_ids)
            ):
                raise ValidationError(
                    "One or more selected properties are unavailable or already verified."
                )

            created_count = 0
            reassigned_count = 0

            with transaction.atomic():
                for property_obj in (
                    selected_properties
                ):
                    if not officer_profile.can_access_assembly(
                        property_obj.assembly_id
                    ):
                        raise ValidationError(
                            (
                                f"{property_obj.property_reference}: "
                                "the selected officer cannot access this assembly."
                            )
                        )

                    existing_assignment = (
                        FieldAssignment.objects
                        .select_for_update()
                        .filter(
                            property=property_obj,
                            status__in=[
                                "assigned",
                                "in_progress",
                            ],
                        )
                        .first()
                    )

                    if existing_assignment:
                        existing_assignment.officer = (
                            officer_profile.user
                        )
                        existing_assignment.priority = (
                            priority
                        )
                        existing_assignment.due_date = (
                            due_date
                        )
                        existing_assignment.notes = (
                            notes
                        )
                        existing_assignment.assigned_by = (
                            request.user
                        )
                        existing_assignment.status = (
                            "assigned"
                        )
                        existing_assignment.assigned_at = (
                            timezone.now()
                        )
                        existing_assignment.completed_at = (
                            None
                        )

                        existing_assignment.save(
                            update_fields=[
                                "officer",
                                "priority",
                                "due_date",
                                "notes",
                                "assigned_by",
                                "status",
                                "assigned_at",
                                "completed_at",
                                "updated_at",
                            ]
                        )

                        reassigned_count += 1

                    else:
                        FieldAssignment.objects.create(
                            assembly=(
                                property_obj.assembly
                            ),
                            property=property_obj,
                            officer=(
                                officer_profile.user
                            ),
                            assigned_by=(
                                request.user
                            ),
                            status="assigned",
                            priority=priority,
                            due_date=due_date,
                            notes=notes,
                            assigned_at=(
                                timezone.now()
                            ),
                        )

                        created_count += 1

            messages.success(
                request,
                (
                    f"{created_count} assignment(s) created; "
                    f"{reassigned_count} reassigned/updated."
                ),
            )

            return redirect(
                "field_operations:assign-field-officer-property"
            )

        except ValidationError as exc:
            messages.error(
                request,
                "; ".join(exc.messages),
            )

    portal_access = get_allowed_modules(
        request.user
    )

    return render(
        request,
        (
            "field_operations/"
            "assign_field_officer_property.html"
        ),
        {
            "page_title": "Assign Properties",
            "page_subtitle": (
                "Assign one or more properties "
                "to a field officer."
            ),
            "context_assembly": assembly,
            "properties": (
                properties_queryset[:500]
            ),
            "officers": officers_queryset,
            "assignments": (
                assignments_queryset[:100]
            ),
            "portal_access": portal_access,
            "allowed_modules": portal_access,
            "user_role": user_role,
        },
    )


def field_officer_verify_property(
    request,
    property_id=None,
):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.shortcuts import redirect, render
    from django.urls import reverse
    from django.utils import timezone

    from admins.access import (
        get_allowed_modules,
        get_user_role,
        landing_url_for_user,
    )
    from properties.models import Property

    from .models import FieldAssignment

    if not request.user.is_authenticated:
        return redirect("admin-login")

    user_role = get_user_role(request.user)

    if user_role != "field_officer":
        messages.error(
            request,
            (
                "Only field officers can submit "
                "property verification."
            ),
        )

        return redirect(
            landing_url_for_user(request.user)
        )

    assembly = _prms_current_assembly(request)

    portal_access = get_allowed_modules(
        request.user
    )

    active_assignments = (
        FieldAssignment.objects
        .select_related(
            "property",
            "property__owner",
            "property__assembly",
            "assembly",
        )
        .filter(
            officer=request.user,
            status__in=[
                "assigned",
                "in_progress",
            ],
        )
        .order_by(
            "-priority",
            "due_date",
            "-assigned_at",
        )
    )

    if assembly:
        active_assignments = (
            active_assignments.filter(
                assembly=assembly,
            )
        )

    assigned_properties = (
        Property.objects
        .select_related(
            "owner",
            "assembly",
        )
        .filter(
            id__in=active_assignments.values_list(
                "property_id",
                flat=True,
            )
        )
        .order_by("-created_at")
    )

    property_obj = None

    if property_id:
        property_obj = (
            assigned_properties.filter(
                id=property_id,
            )
            .first()
        )

        if not property_obj:
            messages.error(
                request,
                (
                    "This property is not assigned "
                    "to you for verification."
                ),
            )

            return redirect(
                (
                    "field_operations:"
                    "field-officer-verify"
                )
            )

    verification_type_choices = [
        (
            "property_verification",
            "Property Verification",
        ),
        (
            "site_assessment",
            "Site Assessment",
        ),
        (
            "payment_verification",
            "Payment Verification",
        ),
        (
            "dispute_investigation",
            "Dispute Investigation",
        ),
        (
            "follow_up",
            "Follow-up Visit",
        ),
    ]

    verification_status_choices = (
        Property.VERIFICATION_STATUS_CHOICES
    )

    form_error = ""

    form_values = {
        "property_id": (
            property_obj.id
            if property_obj
            else ""
        ),
        "property_reference": (
            property_obj.property_reference
            if property_obj
            else ""
        ),
        "verification_type": (
            "property_verification"
        ),
        "verification_status": (
            property_obj.verification_status
            if property_obj
            else ""
        ),
        "owner_present": "yes",
        "notes": "",
        "latitude": (
            str(property_obj.latitude)
            if (
                property_obj
                and property_obj.latitude is not None
            )
            else ""
        ),
        "longitude": (
            str(property_obj.longitude)
            if (
                property_obj
                and property_obj.longitude is not None
            )
            else ""
        ),
    }

    if request.method == "POST":
        form_values.update(
            {
                "property_id": (
                    request.POST.get("property_id")
                    or ""
                ).strip(),
                "property_reference": (
                    request.POST.get(
                        "property_reference"
                    )
                    or ""
                ).strip(),
                "verification_type": (
                    request.POST.get(
                        "verification_type"
                    )
                    or ""
                ).strip(),
                "verification_status": (
                    request.POST.get(
                        "verification_status"
                    )
                    or ""
                ).strip(),
                "owner_present": (
                    request.POST.get(
                        "owner_present"
                    )
                    or "yes"
                ).strip(),
                "notes": (
                    request.POST.get("notes")
                    or ""
                ).strip(),
                "latitude": (
                    request.POST.get("latitude")
                    or ""
                ).strip(),
                "longitude": (
                    request.POST.get("longitude")
                    or ""
                ).strip(),
            }
        )

        allowed_statuses = {
            value
            for value, _label
            in verification_status_choices
        }

        allowed_types = {
            value
            for value, _label
            in verification_type_choices
        }

        try:
            if (
                form_values["verification_type"]
                not in allowed_types
            ):
                raise ValidationError(
                    "Select a valid verification type."
                )

            if (
                form_values["verification_status"]
                not in allowed_statuses
            ):
                raise ValidationError(
                    (
                        "Select a valid verification "
                        "status."
                    )
                )

            if (
                form_values["owner_present"]
                not in {"yes", "no"}
            ):
                raise ValidationError(
                    (
                        "Select whether the owner "
                        "was present."
                    )
                )

            if not form_values["notes"]:
                raise ValidationError(
                    "Enter verification notes."
                )

            latitude = _prms_parse_coordinate(
                form_values["latitude"],
                "Latitude",
            )

            longitude = _prms_parse_coordinate(
                form_values["longitude"],
                "Longitude",
            )

            with transaction.atomic():
                assignment_queryset = (
                    FieldAssignment.objects
                    .select_for_update()
                    .select_related(
                        "property",
                        "property__assembly",
                    )
                    .filter(
                        officer=request.user,
                        status__in=[
                            "assigned",
                            "in_progress",
                        ],
                    )
                )

                if assembly:
                    assignment_queryset = (
                        assignment_queryset.filter(
                            assembly=assembly,
                        )
                    )

                assignment = None

                if form_values["property_id"]:
                    assignment = (
                        assignment_queryset.filter(
                            property_id=(
                                form_values[
                                    "property_id"
                                ]
                            )
                        )
                        .first()
                    )

                elif form_values[
                    "property_reference"
                ]:
                    assignment = (
                        assignment_queryset.filter(
                            property__property_reference__iexact=form_values[
                                "property_reference"
                            ]
                        )
                        .first()
                    )

                if not assignment:
                    raise ValidationError(
                        (
                            "Property not found or this "
                            "property is not assigned "
                            "to you."
                        )
                    )

                property_obj = (
                    Property.objects
                    .select_for_update()
                    .get(
                        pk=assignment.property_id
                    )
                )

                property_obj.verification_status = (
                    form_values[
                        "verification_status"
                    ]
                )

                update_fields = [
                    "verification_status",
                    "updated_at",
                ]

                if (
                    form_values["verification_status"]
                    == "verified"
                ):
                    property_obj.last_verified_at = (
                        timezone.now()
                    )
                else:
                    property_obj.last_verified_at = None

                update_fields.append(
                    "last_verified_at"
                )

                if latitude is not None:
                    property_obj.latitude = latitude
                    update_fields.append("latitude")

                if longitude is not None:
                    property_obj.longitude = longitude
                    update_fields.append("longitude")

                property_obj.save(
                    update_fields=list(
                        dict.fromkeys(
                            update_fields
                        )
                    )
                )

                _prms_create_field_visit(
                    request=request,
                    property_obj=property_obj,
                    verification_type=(
                        form_values[
                            "verification_type"
                        ]
                    ),
                    verification_status=(
                        form_values[
                            "verification_status"
                        ]
                    ),
                    owner_present=(
                        form_values[
                            "owner_present"
                        ]
                    ),
                    notes=form_values["notes"],
                    latitude=latitude,
                    longitude=longitude,
                )

                photo_count = (
                    _prms_save_property_photos(
                        request=request,
                        property_obj=property_obj,
                    )
                )

                if (
                    form_values[
                        "verification_status"
                    ]
                    == "verified"
                ):
                    assignment.status = "completed"
                    assignment.completed_at = (
                        timezone.now()
                    )

                elif (
                    form_values[
                        "verification_status"
                    ]
                    == "rejected"
                ):
                    assignment.status = "rejected"
                    assignment.completed_at = (
                        timezone.now()
                    )

                else:
                    assignment.status = "in_progress"
                    assignment.completed_at = None

                assignment.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "updated_at",
                    ]
                )

            message = (
                "Verification submitted successfully."
            )

            if photo_count:
                message += (
                    f" {photo_count} photo(s) uploaded."
                )

            messages.success(
                request,
                message,
            )

            return redirect(
                (
                    "field_operations:"
                    "field-officer-stats"
                )
            )

        except ValidationError as exc:
            form_error = "; ".join(
                exc.messages
            )

        except Exception:
            logger.exception(
                "Field verification failed for user %s.",
                request.user.pk,
            )

            form_error = (
                "Verification could not be saved. "
                "Please try again. If the problem "
                "continues, contact the administrator."
            )

    officer_name = _prms_user_display_name(
        request.user
    )

    context = {
        "is_field_officer": True,
        "page_title": "Submit Verification",
        "page_subtitle": (
            "Complete field verification report"
        ),
        "portal_access": portal_access,
        "allowed_modules": portal_access,
        "context_assembly": assembly,
        "officer_name": officer_name,
        "officer_initial": (
            officer_name[0].upper()
            if officer_name
            else "F"
        ),
        "officer_zone": (
            assembly.name
            if assembly
            else "Assigned Assembly"
        ),
        "assigned_properties": (
            assigned_properties
        ),
        "active_assignments": (
            active_assignments
        ),
        "property_obj": property_obj,
        "verification_type_choices": (
            verification_type_choices
        ),
        "verification_status_choices": (
            verification_status_choices
        ),
        "form_error": form_error,
        "dashboard_url": reverse(
            "field_operations:field-operations"
        ),
        "verify_url": reverse(
            (
                "field_operations:"
                "field-officer-verify"
            )
        ),
        "stats_url": reverse(
            (
                "field_operations:"
                "field-officer-stats"
            )
        ),
        "cancel_url": reverse(
            "field_operations:field-operations"
        ),
        **form_values,
    }

    return render(
        request,
        (
            "field_operations/"
            "field_officer_verify.html"
        ),
        context,
    )