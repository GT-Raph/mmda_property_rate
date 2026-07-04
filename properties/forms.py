import copy
import re
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.forms import modelform_factory
from django.utils import timezone

from billing.models import (
    CommunityArea,
    PropertyClass,
    RatePolicy,
)
from properties.models import Property


def _model_field_map(model):
    return {
        field.name: field
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False)
        and not getattr(field, "auto_created", False)
    }


PROPERTY_MODEL_FIELDS = _model_field_map(Property)

OWNER_MODEL = (
    Property._meta.get_field("owner")
    .remote_field.model
)

OWNER_MODEL_FIELDS = _model_field_map(
    OWNER_MODEL
)


PROPERTY_FIELD_CANDIDATES = [
    "property_use",
    "building_type",
    "community_area",
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
    and getattr(
        PROPERTY_MODEL_FIELDS[field_name],
        "editable",
        True,
    )
]


OWNER_AUTO_SET_FIELDS = {
    "assembly",
    "created_at",
    "updated_at",
}


OWNER_FORM_FIELDS = [
    field_name
    for field_name, field
    in OWNER_MODEL_FIELDS.items()
    if field_name not in OWNER_AUTO_SET_FIELDS
    and getattr(field, "editable", True)
]


PropertyBaseForm = modelform_factory(
    Property,
    fields=PROPERTY_FORM_FIELDS,
)


OwnerBaseForm = modelform_factory(
    OWNER_MODEL,
    fields=OWNER_FORM_FIELDS,
)


def _owner_display_field():
    for candidate in [
        "full_name",
        "name",
        "owner_name",
    ]:
        if candidate in OWNER_MODEL_FIELDS:
            return candidate

    return "id"


def _normalize_text(value):
    value = (
        value
        or ""
    ).strip().lower()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value


def _normalize_phone(value):
    value = (
        value
        or ""
    ).strip()

    digits = re.sub(
        r"[^\d]",
        "",
        value,
    )

    if not digits:
        return ""

    if digits.startswith("233"):
        return digits

    if digits.startswith("0"):
        return f"233{digits[1:]}"

    return digits


class PropertyCreateForm(PropertyBaseForm):
    class Meta(PropertyBaseForm.Meta):
        fields = PROPERTY_FORM_FIELDS

    def __init__(
        self,
        *args,
        assembly=None,
        **kwargs,
    ):
        self.assembly = assembly

        super().__init__(
            *args,
            **kwargs,
        )

        if (
            self.assembly is None
            and getattr(
                self.instance,
                "assembly_id",
                None,
            )
        ):
            self.assembly = (
                self.instance.assembly
            )

        self.property_field_names = list(
            self.fields.keys()
        )

        self.owner_selector_field_names = []
        self.owner_field_names = []
        self.owner_required_field_names = []

        owner_order_field = (
            _owner_display_field()
        )

        owner_queryset = (
            OWNER_MODEL.objects.all()
        )

        if (
            self.assembly is not None
            and "assembly"
            in OWNER_MODEL_FIELDS
        ):
            owner_queryset = (
                owner_queryset.filter(
                    assembly=self.assembly
                )
            )

        owner_queryset = (
            owner_queryset.order_by(
                owner_order_field
            )
        )

        self.fields[
            "existing_owner"
        ] = forms.ModelChoiceField(
            queryset=owner_queryset,
            required=False,
            empty_label=(
                "Select existing owner"
            ),
            label="Existing Owner",
        )

        self.owner_selector_field_names.append(
            "existing_owner"
        )

        self.fields[
            "create_new_owner"
        ] = forms.BooleanField(
            required=False,
            initial=False,
            label=(
                "Add New Owner Instead"
            ),
        )

        self.owner_selector_field_names.append(
            "create_new_owner"
        )

        for field_name in OWNER_FORM_FIELDS:
            base_field = copy.deepcopy(
                OwnerBaseForm.base_fields[
                    field_name
                ]
            )

            original_required = (
                base_field.required
            )

            base_field.required = False

            prefixed_name = (
                f"owner_{field_name}"
            )

            self.fields[
                prefixed_name
            ] = base_field

            self.owner_field_names.append(
                prefixed_name
            )

            if original_required:
                self.owner_required_field_names.append(
                    prefixed_name
                )

        if "community_area" in self.fields:
            self.fields[
                "community_area"
            ].label = "Community / Area"

            community_queryset = (
                CommunityArea.objects.none()
            )

            if self.assembly is not None:
                community_queryset = (
                    CommunityArea.objects.filter(
                        assembly=self.assembly,
                        is_active=True,
                    )
                    .select_related(
                        "assembly"
                    )
                    .order_by(
                        "sub_metro",
                        "name",
                    )
                )

            self.fields[
                "community_area"
            ].queryset = community_queryset

            self.fields[
                "community_area"
            ].empty_label = (
                "Select community / area"
            )

        placeholders = {
            "address_line": (
                "Enter full address"
            ),
            "area_town": (
                "Enter area or town"
            ),
            "suburb": (
                "Enter suburb"
            ),
            "digital_address": (
                "Enter digital address"
            ),
            "landmark": (
                "Enter landmark"
            ),
            "latitude": "Latitude",
            "longitude": "Longitude",
            "rateable_value": (
                "Enter rateable value"
            ),
            "owner_full_name": (
                "Enter owner's full name"
            ),
            "owner_primary_phone": (
                "Enter phone number"
            ),
            "owner_alternate_phone": (
                "Enter alternate phone number"
            ),
            "owner_email": (
                "Enter email address"
            ),
            "owner_postal_address": (
                "Enter postal address"
            ),
            "owner_residential_address": (
                "Enter residential address"
            ),
            "owner_ghana_card_number": (
                "Enter Ghana card number"
            ),
        }

        for field_name, field in (
            self.fields.items()
        ):
            if isinstance(
                field.widget,
                forms.CheckboxInput,
            ):
                field.widget.attrs.update(
                    {
                        "class": (
                            "checkbox-input"
                        )
                    }
                )

            elif isinstance(
                field.widget,
                forms.Select,
            ):
                field.widget.attrs.update(
                    {
                        "class": (
                            "form-select"
                        )
                    }
                )

            else:
                existing_class = (
                    field.widget.attrs.get(
                        "class",
                        "",
                    )
                )

                field.widget.attrs[
                    "class"
                ] = (
                    f"{existing_class} "
                    "form-input"
                ).strip()

            if (
                field_name in placeholders
                and not isinstance(
                    field.widget,
                    forms.CheckboxInput,
                )
            ):
                field.widget.attrs.update(
                    {
                        "placeholder": (
                            placeholders[
                                field_name
                            ]
                        )
                    }
                )

        labels = {
            "address_line": "Address",
            "number_of_floors": (
                "Number of Floors"
            ),
            "number_of_units": (
                "Number of Units"
            ),
            "year_built": "Year Built",
            "occupancy_status": (
                "Occupancy Status"
            ),
            "rateable_value": (
                "Rateable Value"
            ),
            "is_exempt": (
                "Exempt Property"
            ),
            "exemption_reason": (
                "Exemption Reason"
            ),
        }

        for field_name, label in (
            labels.items()
        ):
            if field_name in self.fields:
                self.fields[
                    field_name
                ].label = label

        if "rateable_value" in self.fields:
            self.fields[
                "rateable_value"
            ].widget.attrs.update(
                {
                    "step": "0.01",
                    "min": "0",
                }
            )

        for coordinate_field in [
            "latitude",
            "longitude",
        ]:
            if coordinate_field in self.fields:
                self.fields[
                    coordinate_field
                ].widget.attrs.update(
                    {
                        "readonly": (
                            "readonly"
                        )
                    }
                )

        if (
            "verification_status"
            in self.fields
        ):
            choices = [
                choice[0]
                for choice in self.fields[
                    "verification_status"
                ].choices
                if choice[0]
            ]

            if (
                "pending" in choices
                and not self.initial.get(
                    "verification_status"
                )
            ):
                self.fields[
                    "verification_status"
                ].initial = "pending"

        if (
            "is_active" in self.fields
            and self.initial.get(
                "is_active"
            ) is None
        ):
            self.fields[
                "is_active"
            ].initial = True

    def clean_rateable_value(self):
        if (
            "rateable_value"
            not in self.cleaned_data
        ):
            return None

        value = self.cleaned_data.get(
            "rateable_value"
        )

        if value is None:
            return value

        if Decimal(value) < 0:
            raise forms.ValidationError(
                "Rateable value cannot "
                "be negative."
            )

        return value

    def clean_community_area(self):
        community_area = (
            self.cleaned_data.get(
                "community_area"
            )
        )

        if (
            community_area
            and self.assembly
            and community_area.assembly_id
            != self.assembly.id
        ):
            raise forms.ValidationError(
                "The selected community or area "
                "does not belong to the current "
                "assembly."
            )

        return community_area

    def _owner_value(
        self,
        field_name,
    ):
        return self.cleaned_data.get(
            f"owner_{field_name}"
        )

    def _find_existing_owner_match(
        self,
        assembly=None,
    ):
        queryset = (
            OWNER_MODEL.objects.all()
        )

        if (
            assembly is not None
            and "assembly"
            in OWNER_MODEL_FIELDS
        ):
            queryset = queryset.filter(
                assembly=assembly
            )

        linked_user = (
            self._owner_value(
                "linked_user"
            )
            if "linked_user"
            in OWNER_MODEL_FIELDS
            else None
        )

        if linked_user:
            owner = queryset.filter(
                linked_user=linked_user
            ).first()

            if owner:
                return owner

        ghana_card_number = (
            self._owner_value(
                "ghana_card_number"
            )
            if "ghana_card_number"
            in OWNER_MODEL_FIELDS
            else None
        )

        if ghana_card_number:
            owner = queryset.filter(
                ghana_card_number__iexact=(
                    str(
                        ghana_card_number
                    ).strip()
                )
            ).first()

            if owner:
                return owner

        primary_phone = (
            self._owner_value(
                "primary_phone"
            )
            if "primary_phone"
            in OWNER_MODEL_FIELDS
            else None
        )

        alternate_phone = (
            self._owner_value(
                "alternate_phone"
            )
            if "alternate_phone"
            in OWNER_MODEL_FIELDS
            else None
        )

        normalized_primary = (
            _normalize_phone(
                primary_phone
            )
        )

        normalized_alternate = (
            _normalize_phone(
                alternate_phone
            )
        )

        if (
            normalized_primary
            and "primary_phone"
            in OWNER_MODEL_FIELDS
        ):
            for owner in queryset:
                owner_primary = (
                    _normalize_phone(
                        getattr(
                            owner,
                            "primary_phone",
                            "",
                        )
                    )
                )

                owner_alternate = (
                    _normalize_phone(
                        getattr(
                            owner,
                            "alternate_phone",
                            "",
                        )
                    )
                )

                if normalized_primary in {
                    owner_primary,
                    owner_alternate,
                }:
                    return owner

        if (
            normalized_alternate
            and "alternate_phone"
            in OWNER_MODEL_FIELDS
        ):
            for owner in queryset:
                owner_primary = (
                    _normalize_phone(
                        getattr(
                            owner,
                            "primary_phone",
                            "",
                        )
                    )
                )

                owner_alternate = (
                    _normalize_phone(
                        getattr(
                            owner,
                            "alternate_phone",
                            "",
                        )
                    )
                )

                if normalized_alternate in {
                    owner_primary,
                    owner_alternate,
                }:
                    return owner

        email = (
            self._owner_value("email")
            if "email"
            in OWNER_MODEL_FIELDS
            else None
        )

        normalized_email = (
            _normalize_text(email)
        )

        if (
            normalized_email
            and "email"
            in OWNER_MODEL_FIELDS
        ):
            owner = queryset.filter(
                email__iexact=(
                    normalized_email
                )
            ).first()

            if owner:
                return owner

        full_name = (
            self._owner_value(
                "full_name"
            )
            if "full_name"
            in OWNER_MODEL_FIELDS
            else None
        )

        normalized_name = (
            _normalize_text(full_name)
        )

        if (
            normalized_name
            and "full_name"
            in OWNER_MODEL_FIELDS
        ):
            name_matches = (
                queryset.filter(
                    full_name__iexact=(
                        full_name.strip()
                    )
                )
            )

            if name_matches.count() == 1:
                return (
                    name_matches.first()
                )

        return None

    def resolve_rate_policy(
        self,
        assembly,
    ):
        if self.cleaned_data.get(
            "is_exempt"
        ):
            return None

        property_use = (
            self.cleaned_data.get(
                "property_use"
            )
        )

        building_type = (
            self.cleaned_data.get(
                "building_type"
            )
        )

        community_area = (
            self.cleaned_data.get(
                "community_area"
            )
        )

        if (
            not property_use
            or not community_area
        ):
            raise ValidationError(
                "Property use and community "
                "or area are required to match "
                "a rate policy."
            )

        if (
            assembly
            and community_area.assembly_id
            != assembly.id
        ):
            raise ValidationError(
                "The selected community or area "
                "does not belong to the current "
                "assembly."
            )

        today = timezone.localdate()

        policy = (
            RatePolicy.get_applicable_policy(
                assembly=assembly,
                property_use=property_use,
                community_area=community_area,
                building_type=building_type,
                on_date=today,
                year=today.year,
            )
        )

        if not policy:
            raise ValidationError(
                "No active rate policy matches "
                "the selected billing year, "
                "community or area, property use "
                "and building type."
            )

        return policy

    def clean(self):
        cleaned_data = super().clean()

        existing_owner = (
            cleaned_data.get(
                "existing_owner"
            )
        )

        create_new_owner = (
            cleaned_data.get(
                "create_new_owner"
            )
        )

        owner_values = {
            field_name: cleaned_data.get(
                field_name
            )
            for field_name
            in self.owner_field_names
        }

        has_new_owner_data = any(
            value not in [
                None,
                "",
                [],
            ]
            for value
            in owner_values.values()
        )

        wants_new_owner = bool(
            create_new_owner
            or (
                not existing_owner
                and has_new_owner_data
            )
        )

        if (
            existing_owner
            and has_new_owner_data
            and not create_new_owner
        ):
            self.add_error(
                "existing_owner",
                (
                    "Choose either an existing "
                    "owner or add a new owner, "
                    "not both."
                ),
            )

        if (
            not existing_owner
            and not wants_new_owner
        ):
            self.add_error(
                "existing_owner",
                (
                    "Select an existing owner "
                    "or enter new owner details."
                ),
            )

        if wants_new_owner:
            for field_name in (
                self.owner_required_field_names
            ):
                value = cleaned_data.get(
                    field_name
                )

                if value in [
                    None,
                    "",
                ]:
                    self.add_error(
                        field_name,
                        (
                            f"{self.fields[field_name].label} "
                            "is required."
                        ),
                    )

        cleaned_data[
            "_wants_new_owner"
        ] = wants_new_owner

        return cleaned_data

    @staticmethod
    def generate_property_reference():
        if (
            "property_reference"
            not in PROPERTY_MODEL_FIELDS
        ):
            return ""

        year = timezone.localdate().year
        prefix = f"PROP-{year}-"

        last_ref = (
            Property.objects.filter(
                property_reference__startswith=(
                    prefix
                )
            )
            .order_by(
                "-property_reference"
            )
            .values_list(
                "property_reference",
                flat=True,
            )
            .first()
        )

        next_number = 1

        if last_ref:
            match = re.search(
                r"(\d+)$",
                str(last_ref),
            )

            if match:
                next_number = (
                    int(
                        match.group(1)
                    )
                    + 1
                )

        return (
            f"{prefix}"
            f"{next_number:05d}"
        )

    def _build_or_reuse_owner_instance(
        self,
        assembly=None,
        commit=True,
    ):
        matched_owner = (
            self._find_existing_owner_match(
                assembly=assembly
            )
        )

        if matched_owner:
            return matched_owner

        owner = OWNER_MODEL()

        if (
            "assembly"
            in OWNER_MODEL_FIELDS
            and assembly is not None
        ):
            setattr(
                owner,
                "assembly",
                assembly,
            )

        for field_name in (
            OWNER_FORM_FIELDS
        ):
            prefixed_name = (
                f"owner_{field_name}"
            )

            value = self.cleaned_data.get(
                prefixed_name
            )

            if (
                value not in [
                    None,
                    "",
                ]
                or isinstance(
                    self.fields[
                        prefixed_name
                    ].widget,
                    forms.CheckboxInput,
                )
            ):
                setattr(
                    owner,
                    field_name,
                    value,
                )

        if commit:
            owner.save()

        return owner

    def _resolve_property_class(
        self,
        *,
        assembly,
        matched_policy,
    ):
        if not matched_policy:
            return None

        class_name = (
            matched_policy.property_class
            or ""
        ).strip()

        if not class_name:
            raise ValidationError(
                "The selected rate policy does "
                "not have a property class."
            )

        property_class = (
            PropertyClass.objects.filter(
                assembly=assembly,
                name__iexact=class_name,
                is_active=True,
            )
            .first()
        )

        if not property_class:
            raise ValidationError(
                (
                    f"The property class "
                    f"'{class_name}' attached to "
                    "the selected rate policy was "
                    "not found under the current "
                    "assembly."
                )
            )

        return property_class

    def save(
        self,
        commit=True,
        assembly=None,
    ):
        assembly = (
            assembly
            or self.assembly
        )

        instance = super().save(
            commit=False
        )

        if (
            hasattr(
                instance,
                "assembly_id",
            )
            and assembly is not None
        ):
            instance.assembly = assembly

        matched_policy = (
            self.resolve_rate_policy(
                assembly
            )
            if assembly
            else None
        )

        existing_owner = (
            self.cleaned_data.get(
                "existing_owner"
            )
        )

        wants_new_owner = (
            self.cleaned_data.get(
                "_wants_new_owner",
                False,
            )
        )

        if wants_new_owner:
            owner = (
                self._build_or_reuse_owner_instance(
                    assembly=assembly,
                    commit=commit,
                )
            )
        else:
            owner = existing_owner

        instance.owner = owner

        if hasattr(
            instance,
            "verification_status",
        ):
            existing_status = getattr(
                instance,
                "verification_status",
                "",
            )

            if (
                not existing_status
                and "verification_status"
                in self.fields
            ):
                choices = [
                    choice[0]
                    for choice
                    in self.fields[
                        "verification_status"
                    ].choices
                    if choice[0]
                ]

                if "pending" in choices:
                    instance.verification_status = (
                        "pending"
                    )
                elif choices:
                    instance.verification_status = (
                        choices[0]
                    )

        if (
            hasattr(
                instance,
                "is_active",
            )
            and getattr(
                instance,
                "is_active",
                None,
            ) is None
        ):
            instance.is_active = True

        if hasattr(
            instance,
            "applied_rate_policy",
        ):
            instance.applied_rate_policy = (
                matched_policy
            )

        if (
            "property_class"
            in PROPERTY_MODEL_FIELDS
        ):
            property_class_field = (
                PROPERTY_MODEL_FIELDS[
                    "property_class"
                ]
            )

            if matched_policy:
                if getattr(
                    property_class_field,
                    "many_to_one",
                    False,
                ):
                    instance.property_class = (
                        self._resolve_property_class(
                            assembly=assembly,
                            matched_policy=(
                                matched_policy
                            ),
                        )
                    )
                else:
                    instance.property_class = (
                        matched_policy.property_class
                    )
            else:
                if getattr(
                    property_class_field,
                    "many_to_one",
                    False,
                ):
                    instance.property_class = None
                else:
                    instance.property_class = ""

        if commit:
            instance.save()
            self.save_m2m()

        return instance