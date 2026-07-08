from django.urls import path

from . import views
from .views import add_property, property_registry

app_name = "properties"

urlpatterns = [
    path("", views.property_registry, name="property-registry"),
    path("add/", views.add_property, name="add-property"),

    path("<int:property_id>/", views.property_detail, name="property-detail"),
    path("<int:property_id>/edit/", views.edit_property, name="property-edit"),
    path("<int:property_id>/document/", views.property_document, name="property-document"),

    path("api/rate-preview/", views.property_rate_preview, name="property-rate-preview"),
]
