from django.core.management.base import BaseCommand, CommandError

from admins.models import Assembly
from billing.models import PropertyClass


CLASS_DATA = {
    "Okaikwai South": [
        ("residential", "Residential Class 1"),
        ("residential", "Residential Class 2"),
        ("residential", "Residential Class 3"),
        ("commercial", "Commercial Class 1"),
    ],
    "Ablekuma South": [
        ("residential", "Residential Class 1"),
        ("residential", "Residential Class 2"),
        ("residential", "Residential Class 3"),
        ("commercial", "Commercial Class 1"),
    ],
    "Ashiedu Keteke": [
        ("residential", "Residential Class 1"),
        ("residential", "Residential Class 2"),
        ("residential", "Residential Class 3"),
        ("commercial", "Commercial Class 1"),
    ],
}


class Command(BaseCommand):
    help = "Seed property classes for the current three assemblies."

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0

        for assembly_name, rows in CLASS_DATA.items():
            assembly = Assembly.objects.filter(name__iexact=assembly_name).first()
            if not assembly:
                raise CommandError(f"Assembly not found: {assembly_name}")

            for property_use, class_name in rows:
                obj, created = PropertyClass.objects.get_or_create(
                    assembly=assembly,
                    property_use=property_use,
                    name=class_name,
                    defaults={"is_active": True},
                )
                if created:
                    created_count += 1
                else:
                    existing_count += 1
                    if not obj.is_active:
                        obj.is_active = True
                        obj.save(update_fields=["is_active"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Property classes seeded. Created: {created_count}, Existing: {existing_count}"
            )
        )
