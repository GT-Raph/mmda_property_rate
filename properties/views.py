from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def property_registry(request):
    properties = [
        {
            "ref": "PROP-2024-00453",
            "owner_name": "Kwame Mensah",
            "location": "East Legon, Accra",
            "property_type": "Residential",
            "type_class": "type-blue",
            "rateable_value": "GH₵ 850,000",
            "status": "Active",
            "status_class": "status-active",
        },
        {
            "ref": "PROP-2024-00452",
            "owner_name": "Ama Adjei",
            "location": "Osu, Accra",
            "property_type": "Commercial",
            "type_class": "type-blue",
            "rateable_value": "GH₵ 1,200,000",
            "status": "Active",
            "status_class": "status-active",
        },
        {
            "ref": "PROP-2024-00451",
            "owner_name": "Kofi Asante",
            "location": "Tema, Greater Accra",
            "property_type": "Residential",
            "type_class": "type-blue",
            "rateable_value": "GH₵ 650,000",
            "status": "Pending",
            "status_class": "status-pending",
        },
        {
            "ref": "PROP-2024-00450",
            "owner_name": "Abena Osei",
            "location": "Spintex, Accra",
            "property_type": "Residential",
            "type_class": "type-blue",
            "rateable_value": "GH₵ 720,000",
            "status": "Active",
            "status_class": "status-active",
        },
        {
            "ref": "PROP-2024-00449",
            "owner_name": "Yaw Boateng",
            "location": "Haatso, Accra",
            "property_type": "Mixed Use",
            "type_class": "type-blue",
            "rateable_value": "GH₵ 950,000",
            "status": "Active",
            "status_class": "status-active",
        },
        {
            "ref": "PROP-2024-00448",
            "owner_name": "Akosua Danquah",
            "location": "Madina, Accra",
            "property_type": "Commercial",
            "type_class": "type-blue",
            "rateable_value": "GH₵ 1,100,000",
            "status": "Inactive",
            "status_class": "status-inactive",
        },
    ]

    context = {
        "page_title": "Property Registry",
        "page_subtitle": "Manage and view all registered properties (8 total)",
        "properties": properties,
    }
    return render(request, "properties/property_registry.html", context)