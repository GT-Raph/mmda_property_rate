import re
from decimal import Decimal

from django import forms
from django.forms import modelform_factory
from django.utils import timezone

from properties.models import Property


MODEL_FIELDS = {
    field.name: field
    for field in Property._meta.get_fields()
    if getattr(field, "concrete", False) and not getattr(field, "auto_created", False)
}

FIELD_CANDIDATES = [
    "owner",
    "property_use",
    "building_type",
    "area_town",
    "suburb",
    "street_name",
    "house_number",
    "digital_address",
    "landmark",
    "rateable_value",
    "latitude",
    "longitude",
    "verification_status",
    "is_active",
]

AVAILABLE_FIELDS = [
    field_name
    for field_name in FIELD_CANDIDATES
    if field_name in MODEL_FIELDS and getattr(MODEL_FIELDS[field_name], "editable", True)
]

BasePropertyForm = modelform_factory(Property, fields=AVAILABLE_FIELDS)


class PropertyCreateForm(BasePropertyForm):
    class Meta(BasePropertyForm.Meta):
        fields = AVAILABLE_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        placeholders = {
            "area_town": "Enter area or town",
            "suburb": "Enter suburb",
            "street_name": "Enter street name",
            "house_number": "Enter house number",
            "digital_address": "Enter digital address",
            "landmark": "Enter landmark",
            "latitude": "Latitude",
            "longitude": "Longitude",
        }

        for field_name, placeholder in placeholders.items():
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.update({"placeholder": placeholder})

        if "rateable_value" in self.fields:
            self.fields["rateable_value"].widget.attrs.update(
                {
                    "placeholder": "Enter rateable value",
                    "step": "0.01",
                    "min": "0",
                }
            )

        if "verification_status" in self.fields:
            choices = [
                choice[0]
                for choice in self.fields["verification_status"].choices
                if choice[0]
            ]
            if "pending" in choices and not self.initial.get("verification_status"):
                self.fields["verification_status"].initial = "pending"

        if "is_active" in self.fields and self.initial.get("is_active") is None:
            self.fields["is_active"].initial = True

        for _, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "checkbox-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            else:
                existing_class = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = f"{existing_class} form-input".strip()

    def clean_rateable_value(self):
        if "rateable_value" not in self.cleaned_data:
            return None

        value = self.cleaned_data.get("rateable_value")
        if value is None:
            return value

        if Decimal(value) < 0:
            raise forms.ValidationError("Rateable value cannot be negative.")

        return value

    @staticmethod
    def generate_property_reference():
        if "property_reference" not in MODEL_FIELDS:
            return ""

        year = timezone.localdate().year
        prefix = f"PROP-{year}-"

        last_ref = (
            Property.objects.filter(property_reference__startswith=prefix)
            .order_by("-property_reference")
            .values_list("property_reference", flat=True)
            .first()
        )

        next_number = 1
        if last_ref:
            match = re.search(r"(\d+)$", str(last_ref))
            if match:
                next_number = int(match.group(1)) + 1

        return f"{prefix}{next_number:05d}"

    def save(self, commit=True, assembly=None):
        instance = super().save(commit=False)

        if hasattr(instance, "assembly_id") and assembly is not None:
            instance.assembly = assembly

        if "property_reference" in MODEL_FIELDS:
            existing_ref = getattr(instance, "property_reference", "") or ""
            if not str(existing_ref).strip():
                generated_ref = self.generate_property_reference()
                if generated_ref:
                    instance.property_reference = generated_ref

        if hasattr(instance, "verification_status"):
            existing_status = getattr(instance, "verification_status", "")
            if not existing_status and "verification_status" in self.fields:
                choices = [
                    choice[0]
                    for choice in self.fields["verification_status"].choices
                    if choice[0]
                ]
                if "pending" in choices:
                    instance.verification_status = "pending"
                elif choices:
                    instance.verification_status = choices[0]

        if hasattr(instance, "is_active") and getattr(instance, "is_active", None) is None:
            instance.is_active = True

        if commit:
            instance.save()
            self.save_m2m()

        return instance