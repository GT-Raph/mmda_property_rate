from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import path, reverse

from .models import (
    Bill,
    BillDispute,
    CommunityArea,
    PropertyClass,
    RatePolicy,
)


LEGACY_CLASS_PREFIX = "__legacy_property_class__:"


def _get_bound_value(form, field_name):
    if form.is_bound:
        return form.data.get(field_name)

    value = form.initial.get(field_name)

    if value not in (None, ""):
        return value

    instance = getattr(form, "instance", None)

    if instance and getattr(instance, "pk", None):
        if field_name == "assembly":
            return getattr(instance, "assembly_id", None)

        return getattr(instance, field_name, None)

    return None


class PropertyClassAdminForm(forms.ModelForm):
    class Meta:
        model = PropertyClass
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        assembly_id = _get_bound_value(self, "assembly")

        areas_queryset = CommunityArea.objects.none()

        if assembly_id:
            areas_queryset = (
                CommunityArea.objects.filter(
                    assembly_id=assembly_id,
                    is_active=True,
                )
                .select_related("assembly")
                .order_by(
                    "sub_metro",
                    "name",
                )
            )

        self.fields["covered_areas"].queryset = areas_queryset
        self.fields["covered_areas"].required = True
        self.fields["covered_areas"].help_text = (
            "Select every community/area that belongs to this class. "
            "When this class is selected in Rate Policies, all of these areas "
            "will be added automatically."
        )

        try:
            community_areas_url = reverse(
                "admin:billing_propertyclass_community_areas"
            )
        except Exception:
            community_areas_url = ""

        self.fields["assembly"].widget.attrs.update(
            {
                "data-community-areas-url": community_areas_url,
            }
        )

    def clean(self):
        cleaned_data = super().clean()

        assembly = cleaned_data.get("assembly")
        property_use = cleaned_data.get("property_use")
        name = (cleaned_data.get("name") or "").strip()
        covered_areas = cleaned_data.get("covered_areas")

        cleaned_data["name"] = name
        self.instance.name = name

        if covered_areas and assembly:
            invalid_areas = covered_areas.exclude(
                assembly=assembly
            )

            if invalid_areas.exists():
                raise ValidationError(
                    {
                        "covered_areas": (
                            "Every selected area must belong to the selected assembly."
                        )
                    }
                )

        if assembly and property_use and covered_areas:
            overlapping_classes = (
                PropertyClass.objects.filter(
                    assembly=assembly,
                    property_use=property_use,
                    covered_areas__in=covered_areas,
                )
                .exclude(pk=self.instance.pk)
                .distinct()
            )

            if overlapping_classes.exists():
                class_names = ", ".join(
                    overlapping_classes.values_list(
                        "name",
                        flat=True,
                    )
                )

                raise ValidationError(
                    {
                        "covered_areas": (
                            "One or more selected areas are already assigned to another "
                            f"{dict(PropertyClass._meta.get_field('property_use').choices).get(property_use, property_use)} "
                            f"class: {class_names}."
                        )
                    }
                )

        return cleaned_data


class RatePolicyAdminForm(forms.ModelForm):
    property_class = forms.ChoiceField(
        label="Property class",
        required=True,
        choices=(),
        help_text=(
            "Choose a class configured under Property classes. "
            "The covered areas will load automatically."
        ),
    )

    class Meta:
        model = RatePolicy
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.selected_property_class = None

        assembly_id = _get_bound_value(self, "assembly")
        property_use = _get_bound_value(self, "property_use")

        class_queryset = PropertyClass.objects.filter(
            is_active=True
        ).select_related("assembly").order_by("name")

        if assembly_id:
            class_queryset = class_queryset.filter(
                assembly_id=assembly_id
            )

        if property_use:
            class_queryset = class_queryset.filter(
                property_use=property_use
            )

        class_choices = [
            ("", "---------"),
            *[
                (str(property_class.pk), property_class.name)
                for property_class in class_queryset
            ],
        ]

        if not class_queryset.exists() and not self.instance.pk:
            class_choices = [
                ("", "Create a Property class first"),
            ]

        if self.instance.pk and self.instance.property_class:
            matched_class = PropertyClass.objects.filter(
                assembly_id=self.instance.assembly_id,
                property_use=self.instance.property_use,
                name__iexact=self.instance.property_class,
            ).first()

            if matched_class:
                self.initial["property_class"] = str(
                    matched_class.pk
                )
            else:
                legacy_value = (
                    f"{LEGACY_CLASS_PREFIX}"
                    f"{self.instance.property_class}"
                )
                class_choices.append(
                    (
                        legacy_value,
                        f"{self.instance.property_class} (legacy)",
                    )
                )
                self.initial["property_class"] = legacy_value

        self.fields["property_class"].choices = class_choices

        areas_queryset = CommunityArea.objects.filter(
            is_active=True
        ).select_related("assembly").order_by(
            "sub_metro",
            "name",
        )

        if assembly_id:
            areas_queryset = areas_queryset.filter(
                assembly_id=assembly_id
            )

        self.fields["covered_areas"].queryset = areas_queryset
        self.fields["covered_areas"].required = False
        self.fields["covered_areas"].help_text = (
            "This list is controlled by the selected Property class. "
            "All areas assigned to that class will be saved automatically."
        )

        try:
            property_classes_url = reverse(
                "admin:billing_ratepolicy_property_classes"
            )
            property_class_areas_url = reverse(
                "admin:billing_ratepolicy_property_class_areas"
            )
        except Exception:
            property_classes_url = ""
            property_class_areas_url = ""

        self.fields["property_use"].widget.attrs.update(
            {
                "data-property-classes-url": property_classes_url,
            }
        )
        self.fields["property_class"].widget.attrs.update(
            {
                "data-property-class-areas-url": property_class_areas_url,
            }
        )

    def clean_property_class(self):
        selected_value = (
            self.cleaned_data.get("property_class")
            or ""
        ).strip()

        if not selected_value:
            raise ValidationError(
                "Select a property class."
            )

        if selected_value.startswith(
            LEGACY_CLASS_PREFIX
        ):
            legacy_name = selected_value.removeprefix(
                LEGACY_CLASS_PREFIX
            ).strip()

            if not legacy_name:
                raise ValidationError(
                    "The legacy property class is invalid."
                )

            self.selected_property_class = None
            return legacy_name

        try:
            property_class = (
                PropertyClass.objects
                .prefetch_related("covered_areas")
                .get(
                    pk=selected_value,
                    is_active=True,
                )
            )
        except (
            PropertyClass.DoesNotExist,
            ValueError,
            TypeError,
        ):
            raise ValidationError(
                "Select a valid property class."
            )

        assembly = self.cleaned_data.get("assembly")
        property_use = self.cleaned_data.get(
            "property_use"
        )

        if assembly and property_class.assembly_id != assembly.id:
            raise ValidationError(
                "The selected property class does not belong to the selected assembly."
            )

        if (
            property_use
            and property_class.property_use != property_use
        ):
            raise ValidationError(
                "The selected property class does not belong to the selected property use."
            )

        self.selected_property_class = property_class
        return property_class.name

    def clean(self):
        cleaned_data = super().clean()

        assembly = cleaned_data.get("assembly")
        year = cleaned_data.get("year")
        property_use = cleaned_data.get("property_use")
        property_class = (
            cleaned_data.get("property_class")
            or ""
        ).strip()
        building_type = (
            cleaned_data.get("building_type")
            or ""
        ).strip()
        status = cleaned_data.get("status")
        effective_from = cleaned_data.get(
            "effective_from"
        )
        effective_to = cleaned_data.get(
            "effective_to"
        )
        posted_areas = cleaned_data.get("covered_areas")

        selected_class = getattr(
            self,
            "selected_property_class",
            None,
        )

        if selected_class:
            class_areas = selected_class.covered_areas.filter(
                is_active=True
            )
            current_area_ids = set(
                class_areas.values_list("id", flat=True)
            )

            if not current_area_ids:
                raise ValidationError(
                    {
                        "property_class": (
                            "The selected property class has no active areas. "
                            "Add areas to the class before creating a rate policy."
                        )
                    }
                )
        else:
            current_area_ids = set(
                posted_areas.values_list(
                    "id",
                    flat=True,
                )
            ) if posted_areas else set()

        if status == "active" and all(
            [
                assembly,
                year,
                property_use,
                property_class,
                effective_from,
            ]
        ):
            current_end = (
                effective_to
                or effective_from.replace(
                    month=12,
                    day=31,
                )
            )

            conflicts = RatePolicy.objects.filter(
                assembly=assembly,
                year=year,
                property_use=property_use,
                property_class__iexact=property_class,
                building_type=building_type,
                status="active",
            ).exclude(pk=self.instance.pk)

            for other in conflicts:
                other_end = (
                    other.effective_to
                    or other.effective_from.replace(
                        month=12,
                        day=31,
                    )
                )

                dates_overlap = (
                    other.effective_from <= current_end
                    and effective_from <= other_end
                )

                if not dates_overlap:
                    continue

                other_area_ids = set(
                    other.covered_areas.values_list(
                        "id",
                        flat=True,
                    )
                )

                if current_area_ids and (
                    current_area_ids & other_area_ids
                ):
                    raise ValidationError(
                        "Another active rate policy overlaps with the same area(s), "
                        "class, year and building type."
                    )

                if not current_area_ids and not other_area_ids:
                    raise ValidationError(
                        "Another active fallback policy already overlaps with the "
                        "same class, year and building type."
                    )

        return cleaned_data


@admin.register(CommunityArea)
class CommunityAreaAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sub_metro",
        "assembly",
        "is_active",
    )
    list_filter = (
        "assembly",
        "sub_metro",
        "is_active",
    )
    search_fields = (
        "name",
        "assembly__name",
    )
    list_editable = ("is_active",)
    ordering = (
        "assembly__name",
        "sub_metro",
        "name",
    )


@admin.register(PropertyClass)
class PropertyClassAdmin(admin.ModelAdmin):
    form = PropertyClassAdminForm
    list_display = (
        "name",
        "property_use",
        "assembly",
        "area_count",
        "is_active",
    )
    list_filter = (
        "assembly",
        "property_use",
        "is_active",
    )
    search_fields = (
        "name",
        "assembly__name",
        "covered_areas__name",
    )
    filter_horizontal = ("covered_areas",)
    list_editable = ("is_active",)
    ordering = (
        "assembly__name",
        "property_use",
        "name",
    )

    fieldsets = (
        (
            "Property Class Details",
            {
                "fields": (
                    "assembly",
                    "property_use",
                    "name",
                    "covered_areas",
                    "is_active",
                )
            },
        ),
    )

    class Media:
        js = (
            "billing/js/property_class_admin.js",
        )

    def get_urls(self):
        custom_urls = [
            path(
                "ajax/community-areas/",
                self.admin_site.admin_view(
                    self.community_areas_view
                ),
                name="billing_propertyclass_community_areas",
            ),
        ]

        return custom_urls + super().get_urls()

    def community_areas_view(self, request):
        assembly_id = (
            request.GET.get("assembly")
            or ""
        ).strip()

        if not assembly_id:
            return JsonResponse(
                {
                    "results": [],
                }
            )

        areas = (
            CommunityArea.objects.filter(
                assembly_id=assembly_id,
                is_active=True,
            )
            .order_by(
                "sub_metro",
                "name",
            )
        )

        return JsonResponse(
            {
                "results": [
                    {
                        "id": area.pk,
                        "text": str(area),
                    }
                    for area in areas
                ]
            }
        )

    @admin.display(description="Areas")
    def area_count(self, obj):
        return obj.covered_areas.count()


@admin.register(RatePolicy)
class RatePolicyAdmin(admin.ModelAdmin):
    form = RatePolicyAdminForm
    list_display = (
        "policy_name",
        "assembly",
        "year",
        "property_use",
        "property_class",
        "building_type",
        "status",
        "rate_impost",
        "minimum_charge",
        "effective_from",
        "effective_to",
        "covered_area_count",
    )
    list_filter = (
        "assembly",
        "year",
        "property_use",
        "property_class",
        "building_type",
        "status",
    )
    search_fields = (
        "policy_name",
        "property_class",
        "notes",
        "covered_areas__name",
    )
    filter_horizontal = ("covered_areas",)
    ordering = (
        "assembly__name",
        "-year",
        "property_use",
        "property_class",
        "building_type",
        "-effective_from",
    )

    fieldsets = (
        (
            "Basic Policy Details",
            {
                "fields": (
                    "assembly",
                    "policy_name",
                    "year",
                    "property_use",
                    "property_class",
                    "covered_areas",
                    "building_type",
                )
            },
        ),
        (
            "Calculation",
            {
                "fields": (
                    "rate_impost",
                    "minimum_charge",
                )
            },
        ),
        (
            "Validity & Status",
            {
                "fields": (
                    "effective_from",
                    "effective_to",
                    "status",
                    "notes",
                )
            },
        ),
    )

    class Media:
        js = (
            "billing/js/rate_policy_admin.js",
        )

    def get_urls(self):
        custom_urls = [
            path(
                "ajax/property-classes/",
                self.admin_site.admin_view(
                    self.property_classes_view
                ),
                name=(
                    "billing_ratepolicy_"
                    "property_classes"
                ),
            ),
            path(
                "ajax/property-class-areas/",
                self.admin_site.admin_view(
                    self.property_class_areas_view
                ),
                name=(
                    "billing_ratepolicy_"
                    "property_class_areas"
                ),
            ),
        ]

        return custom_urls + super().get_urls()

    def property_classes_view(self, request):
        assembly_id = (
            request.GET.get("assembly")
            or ""
        ).strip()
        property_use = (
            request.GET.get("property_use")
            or ""
        ).strip()

        queryset = PropertyClass.objects.filter(
            is_active=True
        ).order_by("name")

        if assembly_id:
            queryset = queryset.filter(
                assembly_id=assembly_id
            )
        else:
            queryset = queryset.none()

        if property_use:
            queryset = queryset.filter(
                property_use=property_use
            )
        else:
            queryset = queryset.none()

        results = [
            {
                "id": str(property_class.pk),
                "text": property_class.name,
            }
            for property_class in queryset
        ]

        return JsonResponse(
            {
                "results": results,
            }
        )

    def property_class_areas_view(self, request):
        property_class_id = (
            request.GET.get("property_class")
            or ""
        ).strip()

        if not property_class_id:
            return JsonResponse(
                {
                    "results": [],
                }
            )

        try:
            property_class = PropertyClass.objects.get(
                pk=property_class_id,
                is_active=True,
            )
        except (
            PropertyClass.DoesNotExist,
            ValueError,
            TypeError,
        ):
            return JsonResponse(
                {
                    "results": [],
                },
                status=404,
            )

        areas = (
            property_class.covered_areas
            .filter(is_active=True)
            .order_by("sub_metro", "name")
        )

        results = [
            {
                "id": str(area.pk),
                "text": (
                    f"{area.name} "
                    f"({area.get_sub_metro_display()})"
                ),
            }
            for area in areas
        ]

        return JsonResponse(
            {
                "property_class": {
                    "id": str(property_class.pk),
                    "name": property_class.name,
                },
                "results": results,
            }
        )

    def save_related(
        self,
        request,
        form,
        formsets,
        change,
    ):
        super().save_related(
            request,
            form,
            formsets,
            change,
        )

        selected_class = getattr(
            form,
            "selected_property_class",
            None,
        )

        if selected_class is None:
            selected_class = PropertyClass.objects.filter(
                assembly=form.instance.assembly,
                property_use=form.instance.property_use,
                name__iexact=form.instance.property_class,
                is_active=True,
            ).first()

        if selected_class:
            form.instance.covered_areas.set(
                selected_class.covered_areas.filter(
                    is_active=True
                )
            )

    @admin.display(description="Areas")
    def covered_area_count(self, obj):
        return obj.covered_areas.count()


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        "bill_number",
        "property_record",
        "billing_year",
        "rate_policy",
        "policy_name_snapshot",
        "property_class_snapshot",
        "amount_due",
        "amount_paid",
        "status",
        "due_date",
    )
    list_filter = (
        "assembly",
        "billing_year",
        "status",
    )
    search_fields = (
        "bill_number",
        "property_record__property_reference",
        "property_record__owner__full_name",
        "policy_name_snapshot",
        "property_class_snapshot",
    )
    autocomplete_fields = (
        "property_record",
        "rate_policy",
    )


@admin.register(BillDispute)
class BillDisputeAdmin(admin.ModelAdmin):
    list_display = (
        "bill",
        "issue_type",
        "status",
        "raised_by",
        "created_at",
    )
    list_filter = (
        "issue_type",
        "status",
    )
    search_fields = (
        "bill__bill_number",
        "bill__property_record__property_reference",
        "bill__property_record__owner__full_name",
        "description",
    )
