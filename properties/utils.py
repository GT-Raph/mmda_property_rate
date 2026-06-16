import re

from django.contrib.auth import get_user_model
from django.db import transaction

from admins.models import UserProfile
from properties.models import Owner

User = get_user_model()


def normalize_text(value):
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


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

    phone_tail = normalize_phone(owner.primary_phone)[-4:] if owner.primary_phone else ""
    base = f"{base_name}{phone_tail}" if phone_tail else base_name
    username = base[:140]

    counter = 1
    while User.objects.filter(username=username).exists():
        suffix = str(counter)
        username = f"{base[:140 - len(suffix)]}{suffix}"
        counter += 1

    return username


def candidate_citizen_users_for_owner(owner):
    qs = User.objects.filter(is_active=True, profile__role="citizen").select_related("profile")

    if owner.assembly_id:
        qs = qs.filter(profile__assembly_id=owner.assembly_id)

    return qs


def find_matching_citizen_for_owner(owner):
    if not owner:
        return None

    if owner.linked_user_id:
        return owner.linked_user

    owner_name = normalize_text(owner.full_name)
    owner_phone_primary = normalize_phone(owner.primary_phone)
    owner_phone_alt = normalize_phone(owner.alternate_phone)
    owner_email = normalize_text(owner.email)

    if not owner_name:
        return None

    candidate_users = list(candidate_citizen_users_for_owner(owner))
    if not candidate_users:
        return None

    # 1. Exact full name + phone
    phone_matches = []
    for user in candidate_users:
        user_name = normalize_text(user.get_full_name())
        profile_phone = normalize_phone(getattr(user.profile, "phone_number", ""))

        if user_name == owner_name and profile_phone and profile_phone in {owner_phone_primary, owner_phone_alt}:
            phone_matches.append(user)

    if len(phone_matches) == 1:
        return phone_matches[0]

    # 2. Exact full name + email
    email_matches = []
    if owner_email:
        for user in candidate_users:
            user_name = normalize_text(user.get_full_name())
            user_email = normalize_text(user.email)

            if user_name == owner_name and user_email and user_email == owner_email:
                email_matches.append(user)

    if len(email_matches) == 1:
        return email_matches[0]

    # 3. Exact full name only, but only if unique
    name_matches = []
    for user in candidate_users:
        if normalize_text(user.get_full_name()) == owner_name:
            name_matches.append(user)

    if len(name_matches) == 1:
        return name_matches[0]

    return None


@transaction.atomic
def link_or_create_citizen_for_owner(owner, default_password="1234"):
    if not owner:
        return {
            "user": None,
            "owner": None,
            "created": False,
            "linked": False,
            "username": "",
            "temporary_password": "",
        }

    if owner.linked_user_id:
        return {
            "user": owner.linked_user,
            "owner": owner,
            "created": False,
            "linked": True,
            "username": owner.linked_user.username,
            "temporary_password": "",
        }

    matched_user = find_matching_citizen_for_owner(owner)

    if matched_user:
        owner.linked_user = matched_user
        owner.save(update_fields=["linked_user"])

        profile, _ = UserProfile.objects.get_or_create(
            user=matched_user,
            defaults={
                "role": "citizen",
                "assembly": owner.assembly,
                "phone_number": owner.primary_phone or "",
                "is_verified": False,
            },
        )

        updated_fields = []
        if profile.role != "citizen":
            profile.role = "citizen"
            updated_fields.append("role")
        if owner.assembly_id and profile.assembly_id != owner.assembly_id:
            profile.assembly = owner.assembly
            updated_fields.append("assembly")
        if owner.primary_phone and profile.phone_number != owner.primary_phone:
            profile.phone_number = owner.primary_phone
            updated_fields.append("phone_number")

        if updated_fields:
            profile.save(update_fields=updated_fields)

        return {
            "user": matched_user,
            "owner": owner,
            "created": False,
            "linked": True,
            "username": matched_user.username,
            "temporary_password": "",
        }

    first_name, last_name = split_full_name(owner.full_name)
    username = build_unique_username(owner)

    safe_email = (owner.email or "").strip().lower()
    if safe_email and User.objects.filter(email__iexact=safe_email).exclude(email="").exists():
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

    UserProfile.objects.get_or_create(
        user=user,
        defaults={
            "role": "citizen",
            "assembly": owner.assembly,
            "phone_number": owner.primary_phone or "",
            "is_verified": False,
        },
    )

    owner.linked_user = user
    owner.save(update_fields=["linked_user"])

    return {
        "user": user,
        "owner": owner,
        "created": True,
        "linked": True,
        "username": user.username,
        "temporary_password": default_password,
    }