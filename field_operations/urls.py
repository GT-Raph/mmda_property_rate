from django.urls import path
from .views import field_operations_dashboard

app_name = "field_operations"

urlpatterns = [
    path("", field_operations_dashboard, name="field-operations"),
]