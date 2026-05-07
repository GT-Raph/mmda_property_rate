from django.urls import path

from .views import (
    assembly_management,
    begin_2fa_setup,
    confirm_2fa_setup,
    dashboard,
    disable_2fa,
    reports_analytics,
    revoke_session,
    settings_view,
)

app_name = "admins"

urlpatterns = [
    path("", dashboard, name="admin-dashboard"),
    path("reports/", reports_analytics, name="reports-analytics"),
    path("assembly/", assembly_management, name="assembly-management"),
    path("settings/", settings_view, name="settings"),
    path("settings/2fa/setup/", begin_2fa_setup, name="begin-2fa-setup"),
    path("settings/2fa/confirm/", confirm_2fa_setup, name="confirm-2fa-setup"),
    path("settings/2fa/disable/", disable_2fa, name="disable-2fa"),
    path("settings/session/<int:audit_id>/revoke/", revoke_session, name="revoke-session"),
]