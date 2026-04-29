from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.timesince import timesince

from .models import FieldVisit


def _officer_name(officer):
    if not officer:
        return "Unknown Officer"

    full_name = officer.get_full_name().strip()
    if full_name:
        return full_name

    return officer.username


def _officer_code(officer):
    if not officer:
        return "FO-000"

    profile = getattr(officer, "profile", None)
    if profile and getattr(profile, "employee_id", ""):
        return profile.employee_id

    return f"FO-{officer.pk:03d}"


def _location_text(property_obj):
    if not property_obj:
        return "—"

    parts = []
    suburb = getattr(property_obj, "suburb", "") or ""
    area_town = getattr(property_obj, "area_town", "") or ""

    if suburb:
        parts.append(suburb)
    if area_town and area_town not in parts:
        parts.append(area_town)

    return ", ".join(parts) or getattr(property_obj, "address_line", "") or "—"


def _status_meta(visit):
    outcome = (getattr(visit, "outcome", "") or "").strip().lower()
    notes = (getattr(visit, "notes", "") or "").strip().lower()
    combined = f"{outcome} {notes}"

    if any(word in combined for word in ["discrep", "mismatch", "failed", "issue", "error"]):
        return {
            "status": "Discrepancy",
            "status_class": "status-discrepancy",
            "icon": "✕",
            "icon_class": "activity-red",
            "is_completed": True,
        }

    if any(word in combined for word in ["pending", "await", "follow", "review", "open"]):
        return {
            "status": "Pending",
            "status_class": "status-pending",
            "icon": "◔",
            "icon_class": "activity-yellow",
            "is_completed": False,
        }

    return {
        "status": "Verified",
        "status_class": "status-verified",
        "icon": "✓",
        "icon_class": "activity-green",
        "is_completed": True,
    }


def _time_label(dt):
    if not dt:
        return "just now"
    return f"{timesince(dt, timezone.now()).split(',')[0]} ago"


@login_required
def field_operations_dashboard(request):
    search_query = request.GET.get("q", "").strip()

    visits_qs = (
        FieldVisit.objects.select_related(
            "officer",
            "officer__profile",
            "property",
            "property__owner",
        )
        .order_by("-visited_at", "-created_at")
    )

    if search_query:
        visits_qs = visits_qs.filter(
            Q(property__property_reference__icontains=search_query)
            | Q(property__owner__full_name__icontains=search_query)
            | Q(property__area_town__icontains=search_query)
            | Q(property__suburb__icontains=search_query)
            | Q(officer__first_name__icontains=search_query)
            | Q(officer__last_name__icontains=search_query)
            | Q(officer__username__icontains=search_query)
            | Q(officer__profile__employee_id__icontains=search_query)
            | Q(notes__icontains=search_query)
        )

    visits = list(visits_qs)

    latest_property_visit = {}
    for visit in visits:
        key = (visit.officer_id, visit.property_id)
        if key not in latest_property_visit:
            latest_property_visit[key] = visit

    officer_buckets = defaultdict(list)
    for visit in latest_property_visit.values():
        officer_buckets[visit.officer].append(visit)

    officers = []
    for officer, officer_visits in officer_buckets.items():
        assigned = len(officer_visits)
        completed = 0

        for visit in officer_visits:
            status_info = _status_meta(visit)
            if status_info["is_completed"]:
                completed += 1

        progress = int(round((completed / assigned) * 100)) if assigned else 0

        officers.append(
            {
                "name": _officer_name(officer),
                "code": _officer_code(officer),
                "assigned": assigned,
                "completed": completed,
                "progress": min(progress, 100),
            }
        )

    officers.sort(key=lambda item: (-item["completed"], item["name"]))

    recent_activities = []
    for visit in visits[:12]:
        status_info = _status_meta(visit)

        if hasattr(visit, "get_visit_type_display"):
            title = visit.get_visit_type_display()
        else:
            title = str(getattr(visit, "visit_type", "Field Activity")).replace("_", " ").title()

        property_obj = visit.property
        property_ref = getattr(property_obj, "property_reference", "—")
        location = _location_text(property_obj)

        description = (getattr(visit, "notes", "") or "").strip()
        if not description:
            description = "Field visit recorded successfully."

        visited_at = getattr(visit, "visited_at", None) or getattr(visit, "created_at", None)

        recent_activities.append(
            {
                "title": title,
                "property_ref": property_ref,
                "location": location,
                "description": description,
                "officer": _officer_name(visit.officer),
                "datetime": timezone.localtime(visited_at).strftime("%Y-%m-%d at %H:%M") if visited_at else "—",
                "time_ago": _time_label(visited_at),
                "status": status_info["status"],
                "status_class": status_info["status_class"],
                "icon": status_info["icon"],
                "icon_class": status_info["icon_class"],
            }
        )

    context = {
        "page_title": "Field Operations",
        "page_subtitle": "Monitor field officer activities and verifications",
        "officers": officers,
        "recent_activities": recent_activities,
        "search_query": search_query,
        "last_updated": timezone.localtime().strftime("%d %b %Y %H:%M:%S"),
    }
    return render(request, "field_operations/field_operations.html", context)