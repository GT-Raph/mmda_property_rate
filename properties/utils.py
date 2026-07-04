import re

from django.contrib.auth import get_user_model
from django.db import transaction

from admins.models import UserProfile

User = get_user_model()


def normalize_text(value):
    value = (value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def normalize_phone(value):
    value = (value or "").strip()
    digits = re.sub(r"[^\d]", "", value)

    if not digits:
        return ""

    if digits.startswith("233"):
        return digits
    if digits.startswith("0"):
        return f"233{digits[1:]}"
    return digits


def split_full_name(full_name):
    full_name = (full_name or "").strip()
    if not full_name:
        return "", ""

    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def build_unique_username(owner):
    base_name = normalize_text(owner.full_name).replace(" ", "")
    base_name = re.sub(r"[^a-z0-9]", "", base_name) or "citizen"

    phone_tail = (
        normalize_phone(owner.primary_phone)[-4:]
        if owner.primary_phone
        else ""
    )
    base = f"{base_name}{phone_tail}" if phone_tail else base_name
    username = base[:140]

    counter = 1
    while User.objects.filter(username=username).exists():
        suffix = str(counter)
        username = f"{base[:140 - len(suffix)]}{suffix}"
        counter += 1

    return username


def candidate_citizen_users_for_owner(owner):
    """
    Search globally, not only inside one assembly.

    A citizen account is global and may be linked to owner records in several
    assemblies.
    """
    return (
        User.objects.filter(
            is_active=True,
            profile__role="citizen",
        )
        .select_related("profile")
        .prefetch_related("owner_records")
        .distinct()
    )


def _user_owner_phone_values(user):
    values = set()

    profile = getattr(user, "profile", None)
    profile_phone = normalize_phone(
        getattr(profile, "phone_number", "") if profile else ""
    )
    if profile_phone:
        values.add(profile_phone)

    for owner_record in user.owner_records.all():
        primary = normalize_phone(owner_record.primary_phone)
        alternate = normalize_phone(owner_record.alternate_phone)

        if primary:
            values.add(primary)
        if alternate:
            values.add(alternate)

    return values


def _single_user_or_none(queryset):
    users = list(queryset[:2])
    if len(users) == 1:
        return users[0]
    return None


def find_matching_citizen_for_owner(owner):
    if not owner:
        return None

    if owner.linked_user_id:
        return owner.linked_user

    owner_name = normalize_text(owner.full_name)
    owner_primary_phone = normalize_phone(owner.primary_phone)
    owner_alternate_phone = normalize_phone(owner.alternate_phone)
    owner_email = normalize_text(owner.email)
    owner_ghana_card = normalize_text(owner.ghana_card_number)

    candidates = candidate_citizen_users_for_owner(owner)

    # Strongest match: a Ghana Card already recorded on another linked owner
    # record. This allows the same citizen to be found across assemblies.
    if owner_ghana_card:
        matched_user = _single_user_or_none(
            candidates.filter(
                owner_records__ghana_card_number__iexact=owner.ghana_card_number.strip()
            ).distinct()
        )
        if matched_user:
            return matched_user

    # Exact email match.
    if owner_email:
        matched_user = _single_user_or_none(
            candidates.filter(email__iexact=owner.email.strip()).distinct()
        )
        if matched_user:
            return matched_user

    # Exact phone match against the profile and all existing owner records.
    owner_phone_values = {
        value
        for value in [owner_primary_phone, owner_alternate_phone]
        if value
    }

    if owner_phone_values:
        phone_matches = []
        for user in candidates:
            if owner_phone_values & _user_owner_phone_values(user):
                phone_matches.append(user)

        if len(phone_matches) == 1:
            return phone_matches[0]

    # Name plus email or phone is a reliable fallback.
    if owner_name:
        name_matches = []

        for user in candidates:
            if normalize_text(user.get_full_name()) != owner_name:
                continue

            email_matches = (
                owner_email
                and normalize_text(user.email) == owner_email
            )
            phone_matches = bool(
                owner_phone_values & _user_owner_phone_values(user)
            )

            if email_matches or phone_matches:
                name_matches.append(user)

        if len(name_matches) == 1:
            return name_matches[0]

    return None


def ensure_citizen_profile_access(user, owner):
    """
    Ensure the citizen profile is complete and grant access to the owner's
    assembly without removing access to any previous assembly.
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)

    updated_fields = []

    if profile.role != "citizen":
        profile.role = "citizen"
        updated_fields.append("role")

    # Keep the first assembly as the default assembly. Additional assemblies
    # are stored in allowed_assemblies.
    if not profile.assembly_id and owner.assembly_id:
        profile.assembly = owner.assembly
        updated_fields.append("assembly")

    if (
        owner.primary_phone
        and profile.phone_number != owner.primary_phone
    ):
        profile.phone_number = owner.primary_phone
        updated_fields.append("phone_number")

    if updated_fields:
        profile.save(update_fields=updated_fields)

    assembly_added = False
    if owner.assembly_id:
        before = profile.allowed_assemblies.filter(
            pk=owner.assembly_id
        ).exists()
        profile.allowed_assemblies.add(owner.assembly)
        assembly_added = not before

    return profile, assembly_added


@transaction.atomic
def link_or_create_citizen_for_owner(owner, default_password="1234"):
    if not owner:
        return {
            "user": None,
            "owner": None,
            "created": False,
            "linked": False,
            "assembly_added": False,
            "username": "",
            "temporary_password": "",
        }

    if owner.linked_user_id:
        user = owner.linked_user
        _profile, assembly_added = ensure_citizen_profile_access(user, owner)

        return {
            "user": user,
            "owner": owner,
            "created": False,
            "linked": True,
            "assembly_added": assembly_added,
            "username": user.username,
            "temporary_password": "",
        }

    matched_user = find_matching_citizen_for_owner(owner)

    if matched_user:
        owner.linked_user = matched_user
        owner.save(update_fields=["linked_user"])

        _profile, assembly_added = ensure_citizen_profile_access(
            matched_user,
            owner,
        )

        return {
            "user": matched_user,
            "owner": owner,
            "created": False,
            "linked": True,
            "assembly_added": assembly_added,
            "username": matched_user.username,
            "temporary_password": "",
        }

    first_name, last_name = split_full_name(owner.full_name)
    username = build_unique_username(owner)

    safe_email = (owner.email or "").strip().lower()
    if (
        safe_email
        and User.objects.filter(email__iexact=safe_email)
        .exclude(email="")
        .exists()
    ):
        safe_email = ""

    user = User(
        username=username,
        first_name=first_name,
        last_name=last_name,
        email=safe_email,
        is_active=True,
    )
    user.set_password(default_password)
    user.save()

    owner.linked_user = user
    owner.save(update_fields=["linked_user"])

    _profile, assembly_added = ensure_citizen_profile_access(user, owner)

    return {
        "user": user,
        "owner": owner,
        "created": True,
        "linked": True,
        "assembly_added": assembly_added,
        "username": user.username,
        "temporary_password": default_password,
    }
