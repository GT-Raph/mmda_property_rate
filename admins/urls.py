from django.urls import path
from .views import dashboard, reports_analytics, settings_view, assembly_management

app_name = "admins"

urlpatterns = [
    path("", dashboard, name="admin-dashboard"),
    path("reports/", reports_analytics, name="reports-analytics"),
    path("assembly/", assembly_management, name="assembly-management"),
    path("settings/", settings_view, name="settings"),
]