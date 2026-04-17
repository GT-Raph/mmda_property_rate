from django.urls import path
from .views import property_registry

app_name = "properties"

urlpatterns = [
    path("", property_registry, name="property-registry"),
]