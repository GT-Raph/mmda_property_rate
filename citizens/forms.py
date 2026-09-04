from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from .models import CitizenPreference, CitizenDispute


class CitizenDisputeForm(forms.ModelForm):
    supporting_document = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-input"}),
    )

    class Meta:
        model = CitizenDispute
        fields = ["property_record", "bill", "dispute_type", "description"]
        widgets = {
            "property_record": forms.Select(attrs={"class": "select"}),
            "bill": forms.Select(attrs={"class": "select"}),
            "dispute_type": forms.Select(attrs={"class": "select"}),
            "description": forms.Textarea(
                attrs={
                    "class": "textarea",
                    "placeholder": "Please provide detailed information about your dispute...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        property_queryset = kwargs.pop("property_queryset", None)
        bill_queryset = kwargs.pop("bill_queryset", None)
        super().__init__(*args, **kwargs)

        self.fields["property_record"].label = "Select Property"
        self.fields["bill"].label = "Bill Number (Optional)"
        self.fields["dispute_type"].label = "Dispute Type"
        self.fields["description"].label = "Description"
        self.fields["supporting_document"].label = "Supporting Document (Optional)"

        self.fields["property_record"].empty_label = "Select a property"
        self.fields["bill"].required = False
        self.fields["bill"].empty_label = "Leave blank if not about a specific bill"

        if property_queryset is not None:
            self.fields["property_record"].queryset = property_queryset

        if bill_queryset is not None:
            self.fields["bill"].queryset = bill_queryset

    def clean_description(self):
        value = (self.cleaned_data.get("description") or "").strip()
        if len(value) < 50:
            raise forms.ValidationError("Description must be at least 50 characters long.")
        return value

    def clean_supporting_document(self):
        file = self.cleaned_data.get("supporting_document")
        if not file:
            return file

        allowed_types = {
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/jpg",
        }

        if getattr(file, "content_type", None) not in allowed_types:
            raise forms.ValidationError(
                "Only PDF, JPG, and PNG files are accepted."
            )

        if file.size > 5 * 1024 * 1024:
            raise forms.ValidationError(
                "File is too large. Maximum file size is 5MB."
            )

        return file

    def clean(self):
        cleaned_data = super().clean()
        property_record = cleaned_data.get("property_record")
        bill = cleaned_data.get("bill")

        if bill and property_record and bill.property_record_id != property_record.id:
            self.add_error("bill", "The selected bill does not belong to the selected property.")

        return cleaned_data


class CitizenPaymentForm(forms.Form):
    NETWORK_CHOICES = [
        ("mtn", "MTN"),
        ("vodafone", "Vodafone"),
        ("airteltigo", "AirtelTigo"),
    ]

    network = forms.ChoiceField(choices=NETWORK_CHOICES)
    mobile_number = forms.CharField(max_length=20)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["network"].widget.attrs.update(
            {
                "class": "form-select",
                "autocomplete": "off",
            }
        )
        self.fields["mobile_number"].widget.attrs.update(
            {
                "class": "form-input",
                "placeholder": "0XX XXX XXXX",
                "autocomplete": "tel",
                "inputmode": "tel",
            }
        )


class CitizenNameForm(forms.Form):
    full_name = forms.CharField(max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].widget.attrs.update(
            {
                "class": "modal-input",
                "placeholder": "Enter full name",
            }
        )


class CitizenEmailForm(forms.Form):
    email = forms.EmailField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {
                "class": "modal-input",
                "placeholder": "Enter email address",
            }
        )


class CitizenPhoneForm(forms.Form):
    phone_number = forms.CharField(max_length=20)

    def clean_phone_number(self):
        value = (self.cleaned_data.get("phone_number") or "").strip()
        if not value:
            raise forms.ValidationError("Phone number is required.")
        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone_number"].widget.attrs.update(
            {
                "class": "modal-input",
                "placeholder": "Enter phone number",
            }
        )


class CitizenAddressForm(forms.Form):
    address = forms.CharField(max_length=255)

    def clean_address(self):
        value = (self.cleaned_data.get("address") or "").strip()
        if not value:
            raise forms.ValidationError("Address is required.")
        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].widget.attrs.update(
            {
                "class": "modal-input",
                "placeholder": "Enter address",
            }
        )


class CitizenNotificationForm(forms.ModelForm):
    class Meta:
        model = CitizenPreference
        fields = [
            "bill_reminders",
            "payment_confirmations",
            "property_updates",
            "promotions_offers",
        ]
        widgets = {
            "bill_reminders": forms.CheckboxInput(attrs={"class": "switch-input"}),
            "payment_confirmations": forms.CheckboxInput(attrs={"class": "switch-input"}),
            "property_updates": forms.CheckboxInput(attrs={"class": "switch-input"}),
            "promotions_offers": forms.CheckboxInput(attrs={"class": "switch-input"}),
        }


class CitizenPasswordForm(PasswordChangeForm):
    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)

        self.fields["old_password"].widget.attrs.update(
            {
                "class": "modal-input",
                "placeholder": "Enter current password",
            }
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "modal-input",
                "placeholder": "Enter new password",
            }
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "modal-input",
                "placeholder": "Confirm new password",
            }
        )
