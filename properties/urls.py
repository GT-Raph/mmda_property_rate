from django.urls import path

from admins import views
from .views import add_property, property_registry
from . import views

app_name = "properties"

urlpatterns = [
    path("", property_registry, name="property-registry"),
    path("add/", add_property, name="add-property"),
    path("api/rate-preview/", views.property_rate_preview, name="property-rate-preview"),
]