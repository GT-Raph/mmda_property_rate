from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def billing_management(request):
    bills = [
        {
            "bill_no": "BILL-2024-00523",
            "property_ref": "PROP-2024-00453",
            "owner": "Kwame Mensah",
            "rateable_value": "GH₵ 850,000",
            "computed_rate": "GH₵ 12,750",
            "year": "2024",
            "status": "Paid",
            "status_class": "status-paid",
        },
        {
            "bill_no": "BILL-2024-00522",
            "property_ref": "PROP-2024-00452",
            "owner": "Ama Adjei",
            "rateable_value": "GH₵ 1,200,000",
            "computed_rate": "GH₵ 18,000",
            "year": "2024",
            "status": "Unpaid",
            "status_class": "status-unpaid",
        },
        {
            "bill_no": "BILL-2024-00521",
            "property_ref": "PROP-2024-00450",
            "owner": "Abena Osei",
            "rateable_value": "GH₵ 720,000",
            "computed_rate": "GH₵ 10,800",
            "year": "2024",
            "status": "Partial",
            "status_class": "status-partial",
        },
        {
            "bill_no": "BILL-2024-00520",
            "property_ref": "PROP-2024-00449",
            "owner": "Yaw Boateng",
            "rateable_value": "GH₵ 950,000",
            "computed_rate": "GH₵ 14,250",
            "year": "2024",
            "status": "Paid",
            "status_class": "status-paid",
        },
        {
            "bill_no": "BILL-2024-00519",
            "property_ref": "PROP-2024-00447",
            "owner": "Kwabena Owusu",
            "rateable_value": "GH₵ 1,350,000",
            "computed_rate": "GH₵ 20,250",
            "year": "2024",
            "status": "Unpaid",
            "status_class": "status-unpaid",
        },
    ]

    context = {
        "page_title": "Billing Management",
        "page_subtitle": "Generate and manage property rate bills",
        "bills": bills,
    }
    return render(request, "billing/billing_management.html", context)