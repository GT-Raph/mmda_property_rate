from django.urls import path
from .views import (citizen_dashboard, citizen_properties, citizen_property_bills, citizen_property_certificate,)

app_name = "citizens"

urlpatterns = [
    path("", citizen_dashboard, name="dashboard"),
    path("properties/", citizen_properties, name="properties"),
    path("properties/<int:property_id>/bills/", citizen_property_bills, name="property-bills"),
    path("properties/<int:property_id>/certificate/", citizen_property_certificate, name="property-certificate"),
]