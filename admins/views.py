import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    context = {
        "page_title": "Dashboard",
        "page_subtitle": "Property Rate Management System Overview",
        "summary_cards": [
            {
                "title": "Total Properties",
                "value": "11,300",
                "meta": "vs last month",
                "change": "12.5%",
                "trend": "up",
                "icon": "🏢",
                "icon_class": "soft-green",
            },
            {
                "title": "Bills Generated",
                "value": "10,845",
                "meta": "this month",
                "change": "8.3%",
                "trend": "up",
                "icon": "📄",
                "icon_class": "soft-blue",
            },
            {
                "title": "Revenue Collected",
                "value": "GH₵ 4.2M",
                "meta": "this month",
                "change": "15.2%",
                "trend": "up",
                "icon": "💲",
                "icon_class": "soft-green",
            },
            {
                "title": "Outstanding",
                "value": "GH₵ 2.8M",
                "meta": "vs last month",
                "change": "5.1%",
                "trend": "down",
                "icon": "⚠️",
                "icon_class": "soft-yellow",
            },
        ],
        "recent_activities": [
            {
                "icon": "💲",
                "icon_class": "soft-green",
                "title": "Payment received: GH₵ 2500",
                "subtitle": "PROP-2024-00453 • Kwame Mensah",
                "time": "10 minutes ago",
                "highlight": True,
            },
            {
                "icon": "📄",
                "icon_class": "soft-blue",
                "title": "New property registered in East Legon",
                "subtitle": "PROP-2024-00454 • Ama Adjei",
                "time": "25 minutes ago",
                "highlight": False,
            },
            {
                "icon": "⚠️",
                "icon_class": "soft-yellow",
                "title": "Rate calculation dispute",
                "subtitle": "PROP-2023-01122 • Kofi Asante",
                "time": "1 hour ago",
                "highlight": False,
            },
            {
                "icon": "💲",
                "icon_class": "soft-green",
                "title": "Payment received: GH₵ 1800",
                "subtitle": "PROP-2024-00102 • Abena Osei",
                "time": "2 hours ago",
                "highlight": True,
            },
        ],
        "alerts": [
            {
                "message": "1,243 properties have overdue payments (>90 days)",
                "action": "View List →",
                "alert_class": "alert-warning",
            },
            {
                "message": "Monthly billing cycle starts in 3 days",
                "action": "Prepare →",
                "alert_class": "alert-info",
            },
            {
                "message": "Field verification completed for 45 properties",
                "action": "Review →",
                "alert_class": "alert-success",
            },
        ],
        "revenue_labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        "revenue_values": [450000, 520000, 480000, 630000, 590000, 720000],
        "payment_labels": ["Paid", "Partial", "Unpaid"],
        "payment_values": [6840, 1250, 3210],
        "payment_counts": {
            "paid": "6,840",
            "partial": "1,250",
            "unpaid": "3,210",
        },
    }
    return render(request, "admins/dashboard.html", context)