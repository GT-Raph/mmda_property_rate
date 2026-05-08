from django.urls import path
from .views import add_property, property_registry

app_name = "properties"

urlpatterns = [
    path("", property_registry, name="property-registry"),
    path("add/", add_property, name="add-property"),
]