from django.urls import path

from .views import (
    citizen_dashboard,
    citizen_properties,
    citizen_property_bills,
    citizen_property_certificate,
    citizen_bills,
    citizen_bill_detail,
    citizen_payment_confirm,
    citizen_payment_processing,
    citizen_payment_success,
    citizen_payment_history,
)

app_name = "citizens"

urlpatterns = [
    path("", citizen_dashboard, name="dashboard"),
    path("properties/", citizen_properties, name="properties"),
    path("properties/<int:property_id>/bills/", citizen_property_bills, name="property-bills"),
    path("properties/<int:property_id>/certificate/", citizen_property_certificate, name="property-certificate"),

    path("bills/", citizen_bills, name="bills"),
    path("bills/<int:bill_id>/", citizen_bill_detail, name="bill-detail"),

    path("payments/confirm/", citizen_payment_confirm, name="payment-confirm"),
    path("payments/processing/", citizen_payment_processing, name="payment-processing"),
    path("payments/success/", citizen_payment_success, name="payment-success"),
    path("payments/history/", citizen_payment_history, name="payment-history"),
]