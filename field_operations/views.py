from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def field_operations_dashboard(request):
    officers = [
        {
            "name": "Emmanuel Ansah",
            "code": "FO-001",
            "assigned": 45,
            "completed": 42,
            "progress": 93,
        },
        {
            "name": "Grace Owusu",
            "code": "FO-002",
            "assigned": 38,
            "completed": 35,
            "progress": 92,
        },
        {
            "name": "Samuel Boateng",
            "code": "FO-003",
            "assigned": 41,
            "completed": 39,
            "progress": 95,
        },
    ]

    recent_activities = [
        {
            "title": "Property Verification",
            "property_ref": "PROP-2024-00453",
            "location": "East Legon, Accra",
            "description": "Property verified. All details match records. Owner present during inspection.",
            "officer": "Emmanuel Ansah",
            "datetime": "2024-04-12 at 14:30",
            "status": "Verified",
            "status_class": "status-verified",
            "icon": "✓",
            "icon_class": "activity-green",
        },
        {
            "title": "Payment Verification",
            "property_ref": "PROP-2024-00452",
            "location": "Osu, Accra",
            "description": "Owner claimed payment was made. Awaiting confirmation from payment system.",
            "officer": "Grace Owusu",
            "datetime": "2024-04-12 at 11:15",
            "status": "Pending",
            "status_class": "status-pending",
            "icon": "◔",
            "icon_class": "activity-yellow",
        },
        {
            "title": "Site Assessment",
            "property_ref": "PROP-2024-00450",
            "location": "Spintex, Accra",
            "description": "Conducted site assessment for new property registration. Measurements confirmed.",
            "officer": "Emmanuel Ansah",
            "datetime": "2024-04-11 at 09:45",
            "status": "Verified",
            "status_class": "status-verified",
            "icon": "✓",
            "icon_class": "activity-green",
        },
        {
            "title": "Dispute Investigation",
            "property_ref": "PROP-2024-00289",
            "location": "Madina, Accra",
            "description": "Investigated classification dispute. Confirmed property is residential, not commercial.",
            "officer": "Samuel Boateng",
            "datetime": "2024-04-10 at 16:20",
            "status": "Verified",
            "status_class": "status-verified",
            "icon": "✓",
            "icon_class": "activity-green",
        },
        {
            "title": "Property Verification",
            "property_ref": "PROP-2024-00234",
            "location": "Tema, Greater Accra",
            "description": "Discrepancy found: Property has 3 floors, records show 2. Requires update.",
            "officer": "Grace Owusu",
            "datetime": "2024-04-10 at 13:00",
            "status": "Discrepancy",
            "status_class": "status-discrepancy",
            "icon": "✕",
            "icon_class": "activity-red",
        },
        {
            "title": "Site Assessment",
            "property_ref": "PROP-2024-00198",
            "location": "Haatso, Accra",
            "description": "New commercial property assessed. Recommended Class B classification.",
            "officer": "Samuel Boateng",
            "datetime": "2024-04-09 at 10:30",
            "status": "Verified",
            "status_class": "status-verified",
            "icon": "✓",
            "icon_class": "activity-green",
        },
    ]

    context = {
        "page_title": "Field Operations",
        "page_subtitle": "Monitor field officer activities and verifications",
        "officers": officers,
        "recent_activities": recent_activities,
    }
    return render(request, "field_operations/field_operations.html", context)