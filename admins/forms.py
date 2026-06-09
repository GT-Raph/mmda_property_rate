from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from admins.models import AdminPreference, Assembly


def _apply_input_classes(fields):
    for _, field in fields.items():
        widget = field.widget

        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = "form-check-input"
        elif isinstance(widget, forms.Textarea):
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} form-textarea".strip()
        elif isinstance(widget, forms.Select):
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} form-input".strip()
        else:
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} form-input".strip()


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

        self.fields["full_name"].widget.attrs["placeholder"] = "Enter full name"
        self.fields["email"].widget.attrs["placeholder"] = "Enter email address"
        self.fields["phone_number"].widget.attrs["placeholder"] = "Enter phone number"

        _apply_input_classes(self.fields)

    def save(self):
        full_name = self.cleaned_data["full_name"].strip()
        parts = full_name.split(maxsplit=1)

        self.user.first_name = parts[0] if parts else ""
        self.user.last_name = parts[1] if len(parts) > 1 else ""
        self.user.email = self.cleaned_data["email"]
        self.user.save(update_fields=["first_name", "last_name", "email"])

        if self.profile:
            self.profile.phone_number = self.cleaned_data["phone_number"]
            self.profile.save(update_fields=["phone_number"])

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_classes(self.fields)


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

        self.fields["current_password"].widget.attrs["placeholder"] = "Enter current password"
        self.fields["new_password"].widget.attrs["placeholder"] = "Enter new password"
        self.fields["confirm_new_password"].widget.attrs["placeholder"] = "Confirm new password"

        _apply_input_classes(self.fields)


class TotpVerifyForm(forms.Form):
    token = forms.CharField(max_length=6, min_length=6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["token"].widget.attrs["placeholder"] = "Enter 6-digit code"
        _apply_input_classes(self.fields)


ASSEMBLY_FIELD_CANDIDATES = [
    "name",
    "region",
    "district",
    "contact_email",
    "contact_phone",
    "address",
    "is_active",
]

ASSEMBLY_EDITABLE_FIELDS = [
    field_name
    for field_name in ASSEMBLY_FIELD_CANDIDATES
    if any(
        f.name == field_name and getattr(f, "editable", False)
        for f in Assembly._meta.get_fields()
    )
]


class AssemblyEditForm(forms.ModelForm):
    class Meta:
        model = Assembly
        fields = ASSEMBLY_EDITABLE_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        placeholders = {
            "name": "Enter assembly name",
            "region": "Enter region",
            "district": "Enter district",
            "contact_email": "Enter contact email",
            "contact_phone": "Enter contact phone",
            "address": "Enter address",
        }

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.Textarea):
                existing = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = f"{existing} form-textarea".strip()
                field.widget.attrs["rows"] = 3
                field.widget.attrs["placeholder"] = placeholders.get(name, "")
            else:
                existing = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = f"{existing} form-input".strip()
                field.widget.attrs["placeholder"] = placeholders.get(name, "")