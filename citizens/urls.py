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
    citizen_profile,
    citizen_update_name,
    citizen_update_email,
    citizen_update_phone,
    citizen_update_address,
    citizen_update_notifications,
    citizen_change_password,
    citizen_certificates,
    citizen_certificate_download,
    citizen_certificate_qr,
    certificate_verify,
)

app_name = "citizens"

urlpatterns = [
    path("", citizen_dashboard, name="dashboard"),
    path("properties/", citizen_properties, name="properties"),
    path("properties/<int:property_id>/bills/", citizen_property_bills, name="property-bills"),

    # main certificate route
    path("properties/<int:property_id>/certificate/", citizen_property_certificate, name="property-certificate"),

    # alias route so old templates using this name won't break
    path("properties/<int:property_id>/certificate/qr/", citizen_property_certificate, name="property-certificate-qr-page"),

    path("bills/", citizen_bills, name="bills"),
    path("bills/<int:bill_id>/", citizen_bill_detail, name="bill-detail"),

    path("payments/confirm/", citizen_payment_confirm, name="payment-confirm"),
    path("payments/processing/", citizen_payment_processing, name="payment-processing"),
    path("payments/success/", citizen_payment_success, name="payment-success"),
    path("payments/history/", citizen_payment_history, name="payment-history"),

    path("profile/", citizen_profile, name="profile"),
    path("profile/update/name/", citizen_update_name, name="update-name"),
    path("profile/update/email/", citizen_update_email, name="update-email"),
    path("profile/update/phone/", citizen_update_phone, name="update-phone"),
    path("profile/update/address/", citizen_update_address, name="update-address"),
    path("profile/update/notifications/", citizen_update_notifications, name="update-notifications"),
    path("profile/change-password/", citizen_change_password, name="change-password"),

    path("certificates/", citizen_certificates, name="certificates"),
    path("certificates/<uuid:certificate_uuid>/download/", citizen_certificate_download, name="certificate-download"),
    path("certificates/<uuid:certificate_uuid>/qr.png", citizen_certificate_qr, name="certificate-qr"),

    path("verify/certificate/<uuid:certificate_uuid>/", certificate_verify, name="certificate-verify"),
]