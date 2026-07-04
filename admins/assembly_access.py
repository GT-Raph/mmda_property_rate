from admins.models import Assembly
from properties.models import Owner


def accessible_assemblies_for_user(user):
    """Return active assemblies the authenticated user may access."""
    if not user or not user.is_authenticated:
        return Assembly.objects.none()

    profile = getattr(user, "profile", None)
    if not profile:
        return Assembly.objects.none()

    if profile.role == "sys_admin":
        return Assembly.objects.filter(is_active=True).order_by("name")

    if profile.role != "citizen":
        if not profile.assembly_id:
            return Assembly.objects.none()

        return Assembly.objects.filter(
            pk=profile.assembly_id,
            is_active=True,
        )

    allowed_ids = set(
        profile.allowed_assemblies.filter(is_active=True).values_list(
            "id",
            flat=True,
        )
    )

    if profile.assembly_id:
        allowed_ids.add(profile.assembly_id)

    allowed_ids.update(
        Owner.objects.filter(
            linked_user=user,
            assembly__is_active=True,
        ).values_list("assembly_id", flat=True)
    )

    return Assembly.objects.filter(
        id__in=allowed_ids,
        is_active=True,
    ).order_by("name")


def user_can_access_assembly(user, assembly_or_id):
    assembly_id = getattr(assembly_or_id, "pk", assembly_or_id)
    if not assembly_id:
        return False

    return accessible_assemblies_for_user(user).filter(
        pk=assembly_id
    ).exists()
