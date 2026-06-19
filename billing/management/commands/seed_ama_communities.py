from django.core.management.base import BaseCommand, CommandError

from admins.models import Assembly
from billing.models import CommunityArea


AREA_DATA = {
    "OKS": [
        "Ridge",
        "North Ridge",
        "West Ridge",
        "Roman Ridge",
        "Dzorwulu",
        "Airport Residential Area",
        "Cantonments",
        "Ringway Estates",
        "North Kaneshie",
        "Awudome",
        "Avenor",
        "Mataheko",
        "Tesano",
        "South Kaneshie",
        "Industrial Residential Enclave",
        "Graphic Road Residential Area",
        "Bubuashie",
        "Darkuman (parts)",
        "New Fadama (parts)",
        "Sukura (parts)",
        "Odorkor Extension (parts)",
        "Abossey Okai Residential Area",
        "Russia Area",
        "Pipe Ano Area",
        "Kaneshie Market Area",
        "Abossey Okai",
        "Graphic Road",
        "Industrial Area",
        "Circle Business Area",
        "Avenor Commercial Zone",
        "Awudome Commercial Zone",
        "Kaneshie Transport Terminal",
    ],
    "ABS": [
        "Korle Bu Senior Staff Housing",
        "Beach Road Residential Area",
        "VIP Residential Enclave",
        "Korle Lagoon View Area",
        "Official Residential Area",
        "High-End Mamprobi Enclave",
        "South Korle Gonno Estates",
        "Premium Coastal Housing Zone",
        "Korle Gonno",
        "Mamprobi",
        "New Mamprobi",
        "Korle Bu",
        "Glefe",
        "Banana Inn Area",
        "Old Dansoman Extension",
        "South Chorkor Residential Zone",
        "Chorkor",
        "Sempe",
        "Old Winneba Road Area",
        "Gbegbeyise",
        "Amanfong",
        "Akotoku",
        "Tsui Bleoo",
        "Fishing Harbour Communities",
        "Korle Bu Commercial Zone",
        "Mamprobi Market Area",
        "Chorkor Market Area",
        "Korle Gonno Market Area",
        "Beach Road Commercial Strip",
        "Glefe Commercial Zone",
        "Main Lorry Station Area",
        "Coastal Business Zone",
    ],
    "AKS": [
        "High Street Residential Enclave",
        "Ministries Residential Area",
        "Independence Avenue Residential Area",
        "Ambassadorial Residential Zone",
        "Government Residential Area",
        "Heritage Residential Zone",
        "Official Quarters Area",
        "Central Accra Executive Area",
        "Adabraka",
        "Timber Market Residential Area",
        "Central Business Fringe Area",
        "Rawlings Park Residential Area",
        "Opera Square Area",
        "Ussher Fort Residential Area",
        "Victoriaborg Residential Area",
        "Ridge Fringe Area",
        "Jamestown",
        "Ussher Town",
        "Tudu",
        "Cow Lane",
        "Ngleshie",
        "Bukom",
        "Old Fadama Fringe Area",
        "Lighthouse Area",
        "Makola Market",
        "High Street",
        "Accra Central",
        "Rawlings Park",
        "Opera Square",
        "UTC Area",
        "Ministries Business District",
    ],
}


class Command(BaseCommand):
    help = "Seed AMA community / area records for rate policy matching."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assembly-id",
            type=int,
            help="Assembly ID to attach the areas to.",
        )
        parser.add_argument(
            "--assembly-short-code",
            type=str,
            default="AMA",
            help="Assembly short code to attach the areas to (default: AMA).",
        )

    def handle(self, *args, **options):
        assembly = None

        if options.get("assembly_id"):
            try:
                assembly = Assembly.objects.get(id=options["assembly_id"])
            except Assembly.DoesNotExist:
                raise CommandError("Assembly with the provided ID was not found.")
        else:
            short_code = (options.get("assembly_short_code") or "").strip()
            assembly = Assembly.objects.filter(short_code__iexact=short_code).first()
            if not assembly:
                raise CommandError("Assembly with the provided short code was not found.")

        created_count = 0
        existing_count = 0

        for sub_metro, area_names in AREA_DATA.items():
            for area_name in area_names:
                obj, created = CommunityArea.objects.get_or_create(
                    assembly=assembly,
                    sub_metro=sub_metro,
                    name=area_name,
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
                f"Community areas seeded for {assembly.name}. Created: {created_count}, Existing: {existing_count}"
            )
        )
