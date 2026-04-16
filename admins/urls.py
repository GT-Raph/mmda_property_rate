from django.urls import path
from .views import dashboard

app_name = "admins"

urlpatterns = [
    path("", dashboard, name="admin-dashboard"),
]