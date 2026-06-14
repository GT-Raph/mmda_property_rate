import copy
import re
from decimal import Decimal

from django import forms
from django.forms import modelform_factory
from django.utils import timezone

from properties.models import Property


def _model_field_map(model):
    return {
        field.name: field
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False) and not getattr(field, "auto_created", False)
    }


PROPERTY_MODEL_FIELDS = _model_field_map(Property)
OWNER_MODEL = Property._meta.get_field("owner").remote_field.model
OWNER_MODEL_FIELDS = _model_field_map(OWNER_MODEL)

PROPERTY_FIELD_CANDIDATES = [
    "property_use",
    "building_type",
    "occupancy_status",
    "number_of_floors",
    "number_of_units",
    "year_built",
    "address_line",
    "area_town",
    "suburb",
    "digital_address",
    "landmark",
    "rateable_value",
    "latitude",
    "longitude",
    "is_exempt",
    "exemption_reason",
    "verification_status",
    "is_active",
]

PROPERTY_FORM_FIELDS = [
    field_name
    for field_name in PROPERTY_FIELD_CANDIDATES
    if field_name in PROPERTY_MODEL_FIELDS
    and getattr(PROPERTY_MODEL_FIELDS[field_name], "editable", True)
]

OWNER_AUTO_SET_FIELDS = {
    "assembly",
    "created_at",
    "updated_at",
}

OWNER_FORM_FIELDS = [
    field_name
    for field_name, field in OWNER_MODEL_FIELDS.items()
    if field_name not in OWNER_AUTO_SET_FIELDS and getattr(field, "editable", True)
]

PropertyBaseForm = modelform_factory(Property, fields=PROPERTY_FORM_FIELDS)
OwnerBaseForm = modelform_factory(OWNER_MODEL, fields=OWNER_FORM_FIELDS)


def _owner_display_field():
    for candidate in ["full_name", "name", "owner_name"]:
        if candidate in OWNER_MODEL_FIELDS:
            return candidate
    return "id"


class PropertyCreateForm(PropertyBaseForm):
    class Meta(PropertyBaseForm.Meta):
        fields = PROPERTY_FORM_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.property_field_names = list(self.fields.keys())
        self.owner_selector_field_names = []
        self.owner_field_names = []
        self.owner_required_field_names = []

        owner_order_field = _owner_display_field()
        owner_queryset = OWNER_MODEL.objects.all().order_by(owner_order_field)

        self.fields["existing_owner"] = forms.ModelChoiceField(
            queryset=owner_queryset,
            required=False,
            empty_label="Select existing owner",
            label="Existing Owner",
        )
        self.owner_selector_field_names.append("existing_owner")

        self.fields["create_new_owner"] = forms.BooleanField(
            required=False,
            initial=False,
            label="Add New Owner Instead",
        )
        self.owner_selector_field_names.append("create_new_owner")

        for field_name in OWNER_FORM_FIELDS:
            base_field = copy.deepcopy(OwnerBaseForm.base_fields[field_name])
            original_required = base_field.required
            base_field.required = False

            prefixed_name = f"owner_{field_name}"
            self.fields[prefixed_name] = base_field
            self.owner_field_names.append(prefixed_name)

            if original_required:
                self.owner_required_field_names.append(prefixed_name)

        placeholders = {
            "address_line": "Enter full address",
            "area_town": "Enter area or town",
            "suburb": "Enter suburb",
            "digital_address": "Enter digital address",
            "landmark": "Enter landmark",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "rateable_value": "Enter rateable value",
            "owner_full_name": "Enter owner's full name",
            "owner_phone_number": "Enter phone number",
            "owner_primary_phone": "Enter phone number",
            "owner_alternate_phone": "Enter alternate phone number",
            "owner_email": "Enter email address",
            "owner_postal_address": "Enter postal address",
            "owner_residential_address": "Enter residential address",
            "owner_ghana_card_number": "Enter Ghana card number",
        }

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "checkbox-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            else:
                existing_class = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = f"{existing_class} form-input".strip()

            if field_name in placeholders and not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"placeholder": placeholders[field_name]})

        labels = {
            "address_line": "Address",
            "number_of_floors": "Number of Floors",
            "number_of_units": "Number of Units",
            "year_built": "Year Built",
            "occupancy_status": "Occupancy Status",
            "rateable_value": "Rateable Value",
            "is_exempt": "Exempt Property",
            "exemption_reason": "Exemption Reason",
        }
        for field_name, label in labels.items():
            if field_name in self.fields:
                self.fields[field_name].label = label

        if "rateable_value" in self.fields:
            self.fields["rateable_value"].widget.attrs.update(
                {
                    "step": "0.01",
                    "min": "0",
                }
            )

        for coordinate_field in ["latitude", "longitude"]:
            if coordinate_field in self.fields:
                self.fields[coordinate_field].widget.attrs.update(
                    {
                        "readonly": "readonly",
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

    def clean_rateable_value(self):
        if "rateable_value" not in self.cleaned_data:
            return None

        value = self.cleaned_data.get("rateable_value")
        if value is None:
            return value

        if Decimal(value) < 0:
            raise forms.ValidationError("Rateable value cannot be negative.")

        return value

    def clean(self):
        cleaned_data = super().clean()

        existing_owner = cleaned_data.get("existing_owner")
        create_new_owner = cleaned_data.get("create_new_owner")

        owner_values = {
            field_name: cleaned_data.get(field_name)
            for field_name in self.owner_field_names
        }

        has_new_owner_data = any(
            value not in [None, "", []]
            for value in owner_values.values()
        )

        wants_new_owner = bool(create_new_owner or (not existing_owner and has_new_owner_data))

        if existing_owner and wants_new_owner:
            self.add_error(
                "existing_owner",
                "Choose either an existing owner or add a new owner, not both.",
            )

        if not existing_owner and not wants_new_owner:
            self.add_error(
                "existing_owner",
                "Select an existing owner or enter new owner details.",
            )

        if wants_new_owner:
            for field_name in self.owner_required_field_names:
                value = cleaned_data.get(field_name)
                if value in [None, ""]:
                    self.add_error(
                        field_name,
                        f"{self.fields[field_name].label} is required.",
                    )

        cleaned_data["_wants_new_owner"] = wants_new_owner
        return cleaned_data

    @staticmethod
    def generate_property_reference():
        if "property_reference" not in PROPERTY_MODEL_FIELDS:
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

    def _build_owner_instance(self, assembly=None):
        owner = OWNER_MODEL()

        if "assembly" in OWNER_MODEL_FIELDS and assembly is not None:
            setattr(owner, "assembly", assembly)

        for field_name in OWNER_FORM_FIELDS:
            prefixed_name = f"owner_{field_name}"
            value = self.cleaned_data.get(prefixed_name)

            if value not in [None, ""] or isinstance(self.fields[prefixed_name].widget, forms.CheckboxInput):
                setattr(owner, field_name, value)

        owner.save()
        return owner

    def save(self, commit=True, assembly=None):
        instance = super().save(commit=False)

        if hasattr(instance, "assembly_id") and assembly is not None:
            instance.assembly = assembly

        existing_owner = self.cleaned_data.get("existing_owner")
        wants_new_owner = self.cleaned_data.get("_wants_new_owner", False)

        if wants_new_owner:
            owner = self._build_owner_instance(assembly=assembly)
        else:
            owner = existing_owner

        instance.owner = owner

        if "property_reference" in PROPERTY_MODEL_FIELDS:
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