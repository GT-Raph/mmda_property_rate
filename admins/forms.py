from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from admins.models import AdminPreference


class ProfileSettingsForm(forms.Form):
    full_name = forms.CharField(max_length=255)
    email = forms.EmailField()
    phone_number = forms.CharField(max_length=20, required=False)

    def __init__(self, *args, user=None, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.profile = profile

        if user and not self.is_bound:
            self.fields["full_name"].initial = user.get_full_name().strip() or user.username
            self.fields["email"].initial = user.email or ""

        if profile and not self.is_bound:
            self.fields["phone_number"].initial = profile.phone_number or ""

    def save(self):
        full_name = self.cleaned_data["full_name"].strip()
        parts = full_name.split(maxsplit=1)

        self.user.first_name = parts[0] if parts else ""
        self.user.last_name = parts[1] if len(parts) > 1 else ""
        self.user.email = self.cleaned_data["email"]
        self.user.save()

        if self.profile:
            self.profile.phone_number = self.cleaned_data["phone_number"]
            self.profile.save()

        return self.user


class NotificationSettingsForm(forms.ModelForm):
    class Meta:
        model = AdminPreference
        fields = [
            "email_notifications",
            "payment_alerts",
            "dispute_alerts",
            "system_updates",
        ]


class PRMSPasswordChangeForm(PasswordChangeForm):
    current_password = forms.CharField(
        widget=forms.PasswordInput(),
        label="Current Password",
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(),
        label="New Password",
    )
    confirm_new_password = forms.CharField(
        widget=forms.PasswordInput(),
        label="Confirm New Password",
    )

    field_order = ["current_password", "new_password", "confirm_new_password"]

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["current_password"] = self.fields.pop("old_password")
        self.fields["new_password"] = self.fields.pop("new_password1")
        self.fields["confirm_new_password"] = self.fields.pop("new_password2")


class TotpVerifyForm(forms.Form):
    token = forms.CharField(max_length=6, min_length=6)