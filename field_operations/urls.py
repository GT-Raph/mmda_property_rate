from django.urls import path

from . import views


app_name = "field_operations"


urlpatterns = [
    path(
        "",
        views.field_operations_dashboard,
        name="field-operations",
    ),
    path(
    "stats/",
    views.field_officer_stats,
    name="field-officer-stats",
    ),
    path(
    "verify/",
    views.field_officer_verify_property,
    name="field-officer-verify",
    ),
    path(
        "verify/<int:property_id>/",
        views.field_officer_verify_property,
        name="field-officer-verify-property",
    ),
]
