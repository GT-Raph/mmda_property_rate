from django import forms


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

        self.fields["network"].widget.attrs.update({"class": "form-select"})
        self.fields["mobile_number"].widget.attrs.update(
            {
                "class": "form-input",
                "placeholder": "0XX XXX XXXX",
            }
        )