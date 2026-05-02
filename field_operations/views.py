from django.db.models import Count, Q
from django.shortcuts import render

from admins.decorators import module_required
from admins.models import Assembly, UserProfile
from billing.models import BillDispute
from field_operations.models import FieldVisit


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


def _officer_name(user):
    full_name = user.get_full_name().strip()
    return full_name or user.username


def _visit_status(visit):
    text = f"{getattr(visit, 'outcome', '')} {getattr(visit, 'notes', '')}".lower()

    if any(word in text for word in ["discrep", "mismatch", "issue", "fail"]):
        return "Discrepancy", "status-discrepancy", "activity-red", "✕"

    if any(word in text for word in ["pending", "await", "review"]):
        return "Pending", "status-pending", "activity-yellow", "◔"

    return "Verified", "status-verified", "activity-green", "✓"


def _visit_title(visit):
    if hasattr(visit, "get_visit_type_display"):
        raw = visit.get_visit_type_display()
    else:
        raw = str(getattr(visit, "visit_type", "Verification")).replace("_", " ").title()

    mapping = {
        "Verification": "Property Verification",
        "Payment Verification": "Payment Verification",
        "Assessment": "Site Assessment",
        "Site Assessment": "Site Assessment",
        "Dispute": "Dispute Investigation",
        "Dispute Investigation": "Dispute Investigation",
    }
    return mapping.get(raw, raw)


def _visit_location(prop):
    parts = []
    suburb = getattr(prop, "suburb", "") or ""
    area = getattr(prop, "area_town", "") or ""
    region = getattr(prop, "region", "") or ""

    if suburb:
        parts.append(suburb)
    if area and area not in parts:
        parts.append(area)
    if region and region not in parts:
        parts.append(region)

    return ", ".join(parts) if parts else "Location not set"


def _visit_description(visit):
    notes = getattr(visit, "notes", "") or ""
    if notes.strip():
        return notes.strip()

    status, _, _, _ = _visit_status(visit)
    title = _visit_title(visit)

    if title == "Payment Verification":
        return "Owner claimed payment was made. Awaiting confirmation from payment system."
    if title == "Site Assessment":
        return "Conducted site assessment for property registration. Measurements confirmed."
    if title == "Dispute Investigation":
        return "Investigated a reported dispute and recorded findings."
    if status == "Discrepancy":
        return "Discrepancy found during verification. Record requires review."
    return "Property verified. All details match records."


@module_required("field_operations")
def field_operations_dashboard(request):
    assembly = _get_current_assembly(request)

    officer_profiles = UserProfile.objects.filter(role="field_officer").select_related("user", "assembly")
    visit_qs = FieldVisit.objects.select_related("property__owner", "officer").order_by("-visited_at", "-created_at")

    if assembly:
        officer_profiles = officer_profiles.filter(assembly=assembly)
        visit_qs = visit_qs.filter(property__assembly=assembly)

    officer_cards = []
    for profile in officer_profiles[:3]:
        officer_visits = visit_qs.filter(officer=profile.user)
        assigned_count = officer_visits.values("property_id").distinct().count()
        completed_count = officer_visits.filter(
            Q(outcome__icontains="verified")
            | Q(outcome__icontains="completed")
            | Q(outcome__icontains="success")
            | Q(notes__icontains="verified")
            | Q(notes__icontains="completed")
        ).count()

        progress = 0
        if assigned_count > 0:
            progress = round((completed_count / assigned_count) * 100)

        officer_cards.append(
            {
                "name": _officer_name(profile.user),
                "code": profile.employee_id or f"FO-{profile.user_id:03d}",
                "assigned": assigned_count,
                "completed": completed_count,
                "progress": progress,
            }
        )

    recent_activities = []
    for visit in visit_qs[:6]:
        status_label, status_class, icon_class, icon = _visit_status(visit)
        title = _visit_title(visit)
        prop = visit.property
        when = visit.visited_at or visit.created_at

        recent_activities.append(
            {
                "title": title,
                "property_ref": getattr(prop, "property_reference", "N/A"),
                "location": _visit_location(prop),
                "description": _visit_description(visit),
                "officer": _officer_name(visit.officer),
                "datetime": when.strftime("%Y-%m-%d at %H:%M") if when else "—",
                "status": status_label,
                "status_class": status_class,
                "icon": icon,
                "icon_class": icon_class,
            }
        )

    context = {
        "page_title": "Field Operations",
        "page_subtitle": "Monitor field officer activities and verifications",
        "officer_cards": officer_cards,
        "recent_activities": recent_activities,
        "context_assembly": assembly,
    }
    return render(request, "field_operations/field_operations.html", context)