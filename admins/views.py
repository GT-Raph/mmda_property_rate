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


@login_required
def reports_analytics(request):
    stats = [
        {
            "icon": "↗",
            "icon_class": "icon-green",
            "title": "Collection Rate",
            "value": "68.5%",
            "meta": "vs 62% last month",
        },
        {
            "icon": "📄",
            "icon_class": "icon-blue",
            "title": "Bills Generated",
            "value": "10,845",
            "meta": "this month",
        },
        {
            "icon": "⭳",
            "icon_class": "icon-green",
            "title": "Reports Generated",
            "value": "24",
            "meta": "this week",
        },
    ]

    reports = [
        {
            "title": "Monthly Revenue Report",
            "description": "Comprehensive revenue collection summary for the month",
            "generated": "April 11, 2024",
            "format": "PDF, Excel",
        },
        {
            "title": "Property Registration Summary",
            "description": "New properties registered and verification status",
            "generated": "April 10, 2024",
            "format": "PDF, Excel",
        },
        {
            "title": "Payment Collection Trends",
            "description": "Analysis of payment patterns and collection efficiency",
            "generated": "April 5, 2024",
            "format": "PDF, Excel",
        },
        {
            "title": "Outstanding Bills Report",
            "description": "Properties with overdue payments and follow-up actions",
            "generated": "April 11, 2024",
            "format": "PDF, Excel",
        },
        {
            "title": "Dispute Resolution Summary",
            "description": "Status of disputes, resolution rate, and common issues",
            "generated": "April 8, 2024",
            "format": "PDF",
        },
        {
            "title": "Field Operations Report",
            "description": "Field officer activities, verifications, and productivity",
            "generated": "April 12, 2024",
            "format": "PDF, Excel",
        },
    ]

    context = {
        "page_title": "Reports & Analytics",
        "page_subtitle": "Generate and export system reports",
        "stats": stats,
        "reports": reports,
    }
    return render(request, "admins/reports_analytics.html", context)


@login_required
def settings_view(request):
    active_tab = request.GET.get("tab", "profile")

    context = {
        "page_title": "Settings",
        "page_subtitle": "Manage your account settings and preferences",
        "active_tab": active_tab,
        "profile_data": {
            "full_name": request.user.get_full_name() or "Super Admin",
            "email": request.user.email or "admin@mmda.gov.gh",
            "phone": "0244123456",
            "role": "Super Admin",
        },
        "notifications": [
            {
                "title": "Email Notifications",
                "description": "Receive email updates about system activity",
                "enabled": True,
            },
            {
                "title": "Payment Alerts",
                "description": "Get notified when payments are received",
                "enabled": True,
            },
            {
                "title": "Dispute Alerts",
                "description": "Notifications for new disputes and resolutions",
                "enabled": True,
            },
            {
                "title": "System Updates",
                "description": "Updates about new features and maintenance",
                "enabled": False,
            },
        ],
        "sessions": [
            {
                "device": "Windows PC - Chrome",
                "meta": "Current session • Accra, Ghana",
                "status": "Active",
            }
        ],
    }
    return render(request, "admins/settings.html", context)