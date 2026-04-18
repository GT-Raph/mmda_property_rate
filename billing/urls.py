from django.urls import path
from .views import billing_management

app_name = "billing"

urlpatterns = [
    path("", billing_management, name="billing-management"),
]