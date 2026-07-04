from django.core.management.base import BaseCommand
from django.db import transaction

from admins.models import UserProfile
from properties.models import Owner


class Command(BaseCommand):
    help = (
        "Add each citizen's linked owner assemblies to "
        "UserProfile.allowed_assemblies and set a default assembly when missing."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        profiles_updated = 0
        assembly_links_added = 0

        profiles = UserProfile.objects.filter(
            role="citizen"
        ).select_related("user", "assembly")

        for profile in profiles.iterator():
            assembly_ids = list(
                Owner.objects.filter(
                    linked_user=profile.user,
                    assembly__is_active=True,
                )
                .values_list("assembly_id", flat=True)
                .distinct()
            )

            if not assembly_ids:
                continue

            existing_ids = set(
                profile.allowed_assemblies.filter(
                    id__in=assembly_ids
                ).values_list("id", flat=True)
            )

            missing_ids = [
                assembly_id
                for assembly_id in assembly_ids
                if assembly_id not in existing_ids
            ]

            if missing_ids:
                profile.allowed_assemblies.add(*missing_ids)
                assembly_links_added += len(missing_ids)

            if not profile.assembly_id:
                profile.assembly_id = assembly_ids[0]
                profile.save(update_fields=["assembly"])
                profiles_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Backfill complete: "
                f"{profiles_updated} default assemblies set, "
                f"{assembly_links_added} allowed assembly links added."
            )
        )
