from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Owner, Property


def _normalize_text(value):
    return (value or "").strip().lower()


def _normalize_phone(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""

    if digits.startswith("233"):
        return digits
    if digits.startswith("0"):
        return f"233{digits[1:]}"
    return digits


def _owner_property_count(owner):
    return Property.objects.filter(owner=owner).count()


def _choose_master_owner(owners):
    def score(owner):
        return (
            1 if getattr(owner, "linked_user_id", None) else 0,
            1 if getattr(owner, "ghana_card_number", None) else 0,
            1 if getattr(owner, "email", None) else 0,
            1 if getattr(owner, "primary_phone", None) else 0,
            _owner_property_count(owner),
            -owner.id,
        )
    return sorted(owners, key=score, reverse=True)[0]


def _merge_owner_data(master, duplicate):
    changed_fields = []

    fields_to_fill = [
        "full_name",
        "primary_phone",
        "alternate_phone",
        "email",
        "ghana_card_number",
        "postal_address",
        "residential_address",
        "linked_user",
        "assembly",
    ]

    for field_name in fields_to_fill:
        if not hasattr(master, field_name) or not hasattr(duplicate, field_name):
            continue

        master_value = getattr(master, field_name, None)
        duplicate_value = getattr(duplicate, field_name, None)

        if master_value in [None, ""] and duplicate_value not in [None, ""]:
            setattr(master, field_name, duplicate_value)
            changed_fields.append(field_name)

    if changed_fields:
        master.save(update_fields=list(set(changed_fields)))


def _validate_merge_candidates(owners):
    if len(owners) < 2:
        raise ValidationError("Select at least two owner records to merge.")

    assembly_ids = {getattr(owner, "assembly_id", None) for owner in owners if getattr(owner, "assembly_id", None)}
    if len(assembly_ids) > 1:
        raise ValidationError("Cannot merge owners from different assemblies.")

    full_names = {_normalize_text(getattr(owner, "full_name", "")) for owner in owners if getattr(owner, "full_name", "")}
    if len(full_names) > 1:
        raise ValidationError("Cannot merge owners with different full names.")

    linked_users = {getattr(owner, "linked_user_id", None) for owner in owners if getattr(owner, "linked_user_id", None)}
    if len(linked_users) > 1:
        raise ValidationError("Cannot merge owners linked to different citizen accounts.")

    ghana_cards = {
        _normalize_text(getattr(owner, "ghana_card_number", ""))
        for owner in owners
        if getattr(owner, "ghana_card_number", "")
    }
    if len(ghana_cards) > 1:
        raise ValidationError("Cannot merge owners with different Ghana card numbers.")

    emails = {
        _normalize_text(getattr(owner, "email", ""))
        for owner in owners
        if getattr(owner, "email", "")
    }
    if len(emails) > 1:
        raise ValidationError("Cannot merge owners with different email addresses.")

    primary_phones = {
        _normalize_phone(getattr(owner, "primary_phone", ""))
        for owner in owners
        if getattr(owner, "primary_phone", "")
    }
    if len(primary_phones) > 1:
        raise ValidationError("Cannot merge owners with different primary phone numbers.")

    return True


class OwnerAdminForm(forms.ModelForm):
    class Meta:
        model = Owner
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        full_name = cleaned_data.get("full_name")
        primary_phone = cleaned_data.get("primary_phone")
        alternate_phone = cleaned_data.get("alternate_phone")
        email = cleaned_data.get("email")
        ghana_card_number = cleaned_data.get("ghana_card_number")
        linked_user = cleaned_data.get("linked_user")
        assembly = cleaned_data.get("assembly")

        qs = Owner.objects.exclude(pk=self.instance.pk)

        if linked_user and qs.filter(linked_user=linked_user).exists():
            raise ValidationError({"linked_user": "Owner with this linked user already exists."})

        possible_dupes = qs
        if assembly:
            possible_dupes = possible_dupes.filter(assembly=assembly)

        if full_name:
            possible_dupes = possible_dupes.filter(full_name__iexact=full_name.strip())

        reasons = []

        if ghana_card_number and possible_dupes.filter(ghana_card_number__iexact=str(ghana_card_number).strip()).exists():
            reasons.append("same Ghana card number")

        if email and possible_dupes.filter(email__iexact=str(email).strip()).exists():
            reasons.append("same email")

        normalized_primary = _normalize_phone(primary_phone)
        normalized_alternate = _normalize_phone(alternate_phone)

        if normalized_primary:
            for owner in possible_dupes:
                owner_primary = _normalize_phone(getattr(owner, "primary_phone", ""))
                owner_alternate = _normalize_phone(getattr(owner, "alternate_phone", ""))
                if normalized_primary in {owner_primary, owner_alternate}:
                    reasons.append("same phone number")
                    break

        if normalized_alternate:
            for owner in possible_dupes:
                owner_primary = _normalize_phone(getattr(owner, "primary_phone", ""))
                owner_alternate = _normalize_phone(getattr(owner, "alternate_phone", ""))
                if normalized_alternate in {owner_primary, owner_alternate}:
                    reasons.append("same phone number")
                    break

        if reasons:
            raise ValidationError(
                f"Possible duplicate owner detected: another owner already exists with the same full name and {', '.join(sorted(set(reasons)))}."
            )

        return cleaned_data


@admin.action(description="Merge selected owners (safe merge)")
def merge_selected_owners(modeladmin, request, queryset):
    owners = list(queryset.order_by("id"))

    try:
        _validate_merge_candidates(owners)
    except ValidationError as exc:
        modeladmin.message_user(request, str(exc), level=messages.ERROR)
        return

    master = _choose_master_owner(owners)
    duplicates = [owner for owner in owners if owner.id != master.id]

    moved_properties = 0
    deleted_ids = []

    with transaction.atomic():
        for duplicate in duplicates:
            _merge_owner_data(master, duplicate)
            moved_properties += Property.objects.filter(owner=duplicate).update(owner=master)
            deleted_ids.append(duplicate.id)
            duplicate.delete()

    modeladmin.message_user(
        request,
        (
            f"Merged {len(deleted_ids)} duplicate owner record(s) into owner #{master.id} ({master.full_name}). "
            f"Moved {moved_properties} propert{'y' if moved_properties == 1 else 'ies'}."
        ),
        level=messages.SUCCESS,
    )


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    form = OwnerAdminForm
    actions = [merge_selected_owners]

    list_display = (
        "id",
        "full_name",
        "primary_phone",
        "email",
        "ghana_card_number",
        "assembly",
        "linked_user",
        "property_count",
    )
    list_filter = ("assembly",)
    search_fields = (
        "full_name",
        "primary_phone",
        "alternate_phone",
        "email",
        "ghana_card_number",
        "linked_user__username",
        "linked_user__first_name",
        "linked_user__last_name",
    )
    autocomplete_fields = ("linked_user",)
    ordering = ("full_name", "id")

    def property_count(self, obj):
        return Property.objects.filter(owner=obj).count()
    property_count.short_description = "Properties"


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        "property_reference",
        "owner",
        "property_use",
        "property_class",
        "building_type",
        "community_area",
        "area_town",
        "suburb",
        "rateable_value",
        "assembly",
        "registered_by",
        "created_at",
    )
    list_filter = ("assembly", "property_use", "property_class", "building_type", "is_active", "verification_status")
    search_fields = (
        "property_reference",
        "owner__full_name",
        "owner__primary_phone",
        "owner__email",
        "address_line",
        "suburb",
        "area_town",
        "community_area__name",
        "property_class__name",
        "digital_address",
    )
    autocomplete_fields = ("owner", "registered_by", "community_area", "applied_rate_policy")
