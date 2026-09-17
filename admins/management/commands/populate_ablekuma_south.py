import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from admins.models import Assembly, UserProfile
from billing.models import Bill, BillDispute, CommunityArea, RatePolicy
from citizens.models import CitizenDispute
from field_operations.models import FieldAssignment, FieldVisit
from payments.models import Payment
from properties.models import Owner, Property
from properties.utils import link_or_create_citizen_for_owner


User = get_user_model()
TARGET_COUNT = 100
VERIFIED_COUNT = 60
FULLY_PAID_COUNT = 50
PART_PAID_COUNT = 5
VERIFIED_UNPAID_COUNT = 5
OWNER_COUNT = 85
OFFICER_COUNT = 4
MIN_ABS_COMMUNITIES = 8
OUTPUT_SUBDIR = Path("private_population_reports")
MOBILE_MONEY_PROVIDERS = ("mtn", "vodafone", "airteltigo")

PROPERTY_COMBINATIONS = (
    ("residential", "apartment"),
    ("residential", "detached"),
    ("residential", "compound"),
    ("commercial", "office"),
    ("commercial", "shop"),
    ("industrial", "warehouse"),
    ("mixed_use", "other"),
    ("institutional", "school"),
)

FIRST_NAMES = (
    "Kwame", "Ama", "Kofi", "Akosua", "Yaw", "Yaa", "Kojo", "Adwoa",
    "Kwabena", "Abena", "Kwaku", "Akua", "Nii", "Naa", "Fiifi", "Esi",
    "Selorm", "Dzifa", "Elorm", "Mawusi", "Nana", "Efua", "Joseph", "Grace",
    "Daniel", "Patricia", "Michael", "Linda", "Samuel", "Mabel",
)
LAST_NAMES = (
    "Mensah", "Owusu", "Asare", "Ofori", "Boateng", "Agyeman", "Addo",
    "Quartey", "Lamptey", "Tetteh", "Annan", "Lartey", "Odoi", "Adjei",
    "Sackey", "Aryee", "Darko", "Amankwah", "Badu", "Danso", "Amoah",
)
OFFICER_NAMES = (
    ("Isaac", "Tetteh"),
    ("Mavis", "Quartey"),
    ("Emmanuel", "Lamptey"),
    ("Priscilla", "Sackey"),
)


def aware(day, hour=9):
    return timezone.make_aware(datetime.combine(day, time(hour=hour)))


def registration_dates(today):
    result = []
    for year, count, months in (
        (2024, 10, tuple(range(1, 13))),
        (2025, 30, tuple(range(1, 13))),
        (2026, 60, tuple(range(1, min(today.month, 12) + 1))),
    ):
        for index in range(count):
            month = months[index % len(months)]
            day = 3 + ((index * 7) % 22)
            candidate = date(year, month, min(day, 28))
            if candidate > today:
                candidate = today - timedelta(days=index % 20)
            result.append(aware(candidate, 8 + (index % 8)))
    return result


def owner_property_counts():
    # 72 single-property, 11 two-property and 2 three-property owners.
    return ([1] * 72) + ([2] * 11) + ([3] * 2)


class Command(BaseCommand):
    help = "Preview or populate 100 ordinary PRMS records in Ablekuma South."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--assembly-id", type=int)
        parser.add_argument("--assembly-short-code")
        parser.add_argument(
            "--override-run-marker",
            action="store_true",
            help="Developer-only override; collision checks still apply.",
        )

    def handle(self, *args, **options):
        assembly = self._select_assembly(options)
        output_dir = Path(settings.MEDIA_ROOT) / OUTPUT_SUBDIR
        marker_path = output_dir / f"ablekuma_south_assembly_{assembly.pk}.json"
        self._print_startup(assembly)
        preflight = self._preflight(assembly, marker_path, options)
        self._print_preflight(preflight)

        if not options["confirm"]:
            self.stdout.write(self.style.WARNING("DRY-RUN ONLY: no records were created."))
            return

        if preflight["errors"]:
            raise CommandError("Population blocked by preflight errors; no records were created.")

        output_dir.mkdir(parents=True, exist_ok=True)
        stale_manifest = preflight.get("stale_manifest")
        if stale_manifest:
            stale_run_id = stale_manifest.get("execution_id") or "unknown"
            archived_marker = output_dir / (
                f"ablekuma_south_assembly_{assembly.pk}_{stale_run_id}.json"
            )
            if not archived_marker.exists():
                shutil.copy2(marker_path, archived_marker)
        run_id = timezone.now().strftime("%Y%m%dT%H%M%SZ")
        planned_payment_references = [
            f"PRMS-{timezone.localdate().year}-AS-{run_id[-7:-1]}-{index + 1:04d}"
            for index in range(FULLY_PAID_COUNT + PART_PAID_COUNT)
        ]
        if Payment.objects.filter(
            transaction_reference__in=planned_payment_references
        ).exists():
            raise CommandError(
                "A planned Mobile Money transaction reference already exists; "
                "no records were created."
            )
        in_progress = marker_path.with_suffix(".in_progress.json")
        in_progress.write_text(
            json.dumps({"status": "in_progress", "run_id": run_id, "assembly_id": assembly.pk}, indent=2),
            encoding="utf-8",
        )
        try:
            with transaction.atomic():
                baseline_property_ids = preflight["baseline_property_ids"]
                locked_property_ids = set(
                    Property.objects.select_for_update()
                    .filter(pk__in=baseline_property_ids)
                    .values_list("pk", flat=True)
                )
                if locked_property_ids != set(baseline_property_ids):
                    raise CommandError(
                        "Existing Property baseline changed after preflight; transaction aborted."
                    )
                result = self._populate(assembly, preflight, run_id)
                workbook_bytes = self._build_workbook(assembly, result)
            report_path = output_dir / f"PRMS_Ablekuma_South_Population_Report_{run_id}.xlsx"
            report_path.write_bytes(workbook_bytes)
            manifest = self._manifest(assembly, run_id, report_path, result)
            marker_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            in_progress.unlink(missing_ok=True)
        except Exception:
            # An in-progress marker is deliberately retained if the database
            # committed but private output creation failed.
            if not marker_path.exists():
                in_progress.unlink(missing_ok=True)
            raise

        self.stdout.write(self.style.SUCCESS("Ablekuma South population completed."))
        self.stdout.write(f"Private report: {report_path.resolve()}")
        self._print_result(result)

    def _select_assembly(self, options):
        assembly_id = options.get("assembly_id")
        short_code = (options.get("assembly_short_code") or "").strip()
        if assembly_id and short_code:
            raise CommandError("Use either --assembly-id or --assembly-short-code, not both.")
        if assembly_id:
            assembly = Assembly.objects.filter(pk=assembly_id, is_active=True).first()
        elif short_code:
            matches = Assembly.objects.filter(short_code__iexact=short_code, is_active=True)
            assembly = matches.first() if matches.count() == 1 else None
        else:
            matches = Assembly.objects.filter(is_active=True)
            assembly = matches.first() if matches.count() == 1 else None
        if not assembly:
            raise CommandError("Target Assembly could not be determined safely. Supply an unambiguous Assembly.")
        return assembly

    def _counts(self, assembly):
        props = Property.objects.filter(assembly=assembly)
        return {
            "properties": Property.objects.count(),
            "abs_properties": props.filter(community_area__sub_metro="ABS").count(),
            "oks_properties": props.filter(community_area__sub_metro="OKS").count(),
            "aks_properties": props.filter(community_area__sub_metro="AKS").count(),
            "owners": Owner.objects.count(),
            "users": User.objects.count(),
            "bills": Bill.objects.count(),
            "payments": Payment.objects.count(),
            "field_officers": UserProfile.objects.filter(role="field_officer", assembly=assembly).count(),
        }

    def _print_startup(self, assembly):
        db = connection.settings_dict
        self.stdout.write(f"Database engine: {db.get('ENGINE', '')}")
        self.stdout.write(f"Database identifier: {db.get('NAME', '')}")
        self.stdout.write(f"Selected Assembly: {assembly.name}")
        self.stdout.write(f"Assembly short code: {assembly.short_code}")
        for label, value in self._counts(assembly).items():
            self.stdout.write(f"Existing {label.replace('_', ' ')}: {value}")

    def _preflight(self, assembly, marker_path, options):
        errors = []
        abs_areas = list(
            CommunityArea.objects.filter(assembly=assembly, sub_metro="ABS", is_active=True).order_by("name")
        )
        if len(abs_areas) < MIN_ABS_COMMUNITIES:
            errors.append(
                f"At least {MIN_ABS_COMMUNITIES} active ABS Community Areas are required; found {len(abs_areas)}. "
                "Create approved ABS master records separately before population."
            )
        if any(area.sub_metro != "ABS" for area in abs_areas):
            errors.append("A selected Community Area is outside ABS.")

        today = timezone.localdate()
        if assembly.active_billing_year != today.year:
            errors.append(
                f"Assembly active billing year must be {today.year}; "
                f"found {assembly.active_billing_year}."
            )
        policies = {}
        missing = []
        for property_use, building_type in PROPERTY_COMBINATIONS:
            policy = None
            for area in abs_areas:
                policy = RatePolicy.get_applicable_policy(
                    assembly=assembly,
                    property_use=property_use,
                    community_area=area,
                    building_type=building_type,
                    on_date=today,
                    year=today.year,
                )
                if policy:
                    break
            if policy:
                policies[(property_use, building_type)] = policy
            else:
                missing.append(f"{property_use}/{building_type}")
        if missing:
            errors.append(
                "Missing active ABS Rate Policies for: " + ", ".join(missing)
                + ". Rate impost and minimum-charge values require separate approval."
            )
        if abs_areas:
            planned_policy_gaps = set()
            for index in range(TARGET_COUNT):
                area = abs_areas[index % len(abs_areas)]
                property_use, building_type = PROPERTY_COMBINATIONS[index % len(PROPERTY_COMBINATIONS)]
                policy = RatePolicy.get_applicable_policy(
                    assembly=assembly,
                    property_use=property_use,
                    community_area=area,
                    building_type=building_type,
                    on_date=today,
                    year=today.year,
                )
                if not policy:
                    planned_policy_gaps.add(f"{area.name}: {property_use}/{building_type}")
            if planned_policy_gaps:
                errors.append(
                    "The planned Property distribution lacks a matching policy for: "
                    + "; ".join(sorted(planned_policy_gaps))
                )

        stale_manifest = None
        if marker_path.exists() and not options.get("override_run_marker"):
            try:
                prior_manifest = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                errors.append(f"The completed run marker cannot be validated safely: {exc}")
            else:
                expected_manifest_lengths = {
                    "owner_ids": OWNER_COUNT,
                    "user_ids": OWNER_COUNT,
                    "field_officer_user_ids": OFFICER_COUNT,
                    "property_ids": TARGET_COUNT,
                    "bill_ids": TARGET_COUNT,
                    "payment_ids": FULLY_PAID_COUNT + PART_PAID_COUNT,
                    "assignment_ids": TARGET_COUNT,
                    "field_visit_ids": VERIFIED_COUNT,
                    "bill_dispute_ids": 10,
                    "citizen_dispute_ids": 2,
                }
                malformed = (
                    prior_manifest.get("status") != "completed"
                    or prior_manifest.get("assembly_id") != assembly.pk
                    or any(
                        len(prior_manifest.get(key, [])) != expected
                        for key, expected in expected_manifest_lengths.items()
                    )
                )
                if malformed:
                    errors.append(
                        "The completed run marker has an unexpected structure and "
                        "cannot be treated as safely stale."
                    )
                manifest_models = {
                    "owner_ids": Owner,
                    "user_ids": User,
                    "field_officer_user_ids": User,
                    "property_ids": Property,
                    "bill_ids": Bill,
                    "payment_ids": Payment,
                    "assignment_ids": FieldAssignment,
                    "field_visit_ids": FieldVisit,
                    "bill_dispute_ids": BillDispute,
                    "citizen_dispute_ids": CitizenDispute,
                }
                surviving = {
                    key: model.objects.filter(pk__in=prior_manifest.get(key, [])).count()
                    for key, model in manifest_models.items()
                }
                if malformed:
                    pass
                elif any(surviving.values()):
                    errors.append(
                        "A completed run marker still references live database records: "
                        + ", ".join(
                            f"{key}={count}" for key, count in surviving.items() if count
                        )
                    )
                else:
                    stale_manifest = prior_manifest
        in_progress = marker_path.with_suffix(".in_progress.json")
        if in_progress.exists() and not options.get("override_run_marker"):
            errors.append(f"An incomplete/uncertain run marker exists: {in_progress}")

        identity_namespace = None
        for namespace in range(1, 100):
            identities = self._planned_identities(namespace)
            owner_collisions = Owner.objects.filter(
                Q(primary_phone__in=identities["owner_phones"])
                | Q(alternate_phone__in=identities["alternate_phones"])
                | Q(email__in=identities["owner_emails"])
                | Q(ghana_card_number__in=identities["ghana_cards"])
            ).exists()
            user_collisions = User.objects.filter(
                Q(username__in=identities["citizen_usernames"])
                | Q(email__in=identities["owner_emails"])
                | Q(username__in=identities["officer_usernames"])
                | Q(email__in=identities["officer_emails"])
            ).exists()
            profile_collisions = UserProfile.objects.filter(
                phone_number__in=(
                    identities["owner_phones"] + identities["officer_phones"]
                )
            ).exists()
            if not owner_collisions and not user_collisions and not profile_collisions:
                identity_namespace = namespace
                break
        if identity_namespace is None:
            errors.append("No collision-free generated identity namespace is available.")

        return {
            "areas": abs_areas,
            "policies": policies,
            "missing": missing,
            "errors": errors,
            "stale_manifest": stale_manifest,
            "identity_namespace": identity_namespace,
            "baseline_property_ids": list(
                Property.objects.order_by("pk").values_list("pk", flat=True)
            ),
        }

    def _print_preflight(self, preflight):
        self.stdout.write(f"Active ABS Community Areas: {len(preflight['areas'])}")
        for area in preflight["areas"]:
            self.stdout.write(f"  - {area.name} [ABS]")
        self.stdout.write("Usable active policies:")
        for combo, policy in preflight["policies"].items():
            self.stdout.write(
                f"  - {combo[0]}/{combo[1]}: {policy.policy_name}; "
                f"rate={policy.rate_impost}; minimum={policy.minimum_charge}"
            )
        if preflight.get("stale_manifest"):
            self.stdout.write(
                "Previous manifest is stale: all referenced database records are absent."
            )
        if preflight.get("identity_namespace"):
            self.stdout.write(
                f"Collision-free identity namespace: {preflight['identity_namespace']}"
            )
        for error in preflight["errors"]:
            self.stderr.write(self.style.ERROR(f"BLOCKER: {error}"))

    def _planned_identities(self, namespace):
        offset = (namespace - 1) * 100000
        owner_numbers = [offset + index for index in range(1, OWNER_COUNT + 1)]
        owner_phones = [f"0208{number:06d}" for number in owner_numbers]
        owner_emails = [
            f"{FIRST_NAMES[i % len(FIRST_NAMES)].lower()}."
            f"{LAST_NAMES[(i * 7) % len(LAST_NAMES)].lower()}{number}@example.invalid"
            for i, number in enumerate(owner_numbers)
            if i % 3
        ]
        suffix = "" if namespace == 1 else str(namespace)
        return {
            "offset": offset,
            "owner_phones": owner_phones,
            "alternate_phones": [
                f"0509{number:06d}" for i, number in enumerate(owner_numbers) if i % 5 == 0
            ],
            "owner_emails": owner_emails,
            "citizen_usernames": [f"233{phone[1:]}" for phone in owner_phones],
            "ghana_cards": [
                f"GHA-{700000000 + offset + i:09d}-{i % 10}"
                for i in range(OWNER_COUNT)
            ],
            "officer_usernames": [
                f"{first.lower()}.{last.lower()}.field{suffix}"
                for first, last in OFFICER_NAMES
            ],
            "officer_emails": [
                f"{first.lower()}.{last.lower()}.field{suffix}@example.invalid"
                for first, last in OFFICER_NAMES
            ],
            "officer_phones": [
                f"0277{offset + index:06d}" for index in range(1, OFFICER_COUNT + 1)
            ],
        }

    def _owner_data(self, index, assembly, namespace):
        identities = self._planned_identities(namespace)
        number = identities["offset"] + index + 1
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[(index * 7) % len(LAST_NAMES)]
        phone = f"0208{number:06d}"
        email = f"{first.lower()}.{last.lower()}{number}@example.invalid" if index % 3 else ""
        return {
            "assembly": assembly,
            "full_name": f"{first} {last}",
            "primary_phone": phone,
            "alternate_phone": f"0509{number:06d}" if index % 5 == 0 else "",
            "email": email,
            "ghana_card_number": f"GHA-{700000000 + identities['offset'] + index:09d}-{index % 10}",
            "postal_address": f"P.O. Box AS {120 + index}, Accra" if index % 4 == 0 else "",
            "residential_address": f"House {12 + index}, Ablekuma South, Accra",
        }

    def _create_officers(self, assembly, credentials, namespace):
        identities = self._planned_identities(namespace)
        officers = []
        for index, (first, last) in enumerate(OFFICER_NAMES, 1):
            username = identities["officer_usernames"][index - 1]
            if User.objects.filter(username__iexact=username).exists():
                raise CommandError(f"Field Officer username collision: {username}")
            password = f"Prms-{secrets_token(index)}"
            user = User.objects.create_user(
                username=username,
                first_name=first,
                last_name=last,
                email=identities["officer_emails"][index - 1],
                password=password,
                is_active=True,
            )
            profile = user.profile
            profile.role = "field_officer"
            profile.assembly = assembly
            profile.phone_number = identities["officer_phones"][index - 1]
            profile.is_verified = True
            profile.must_change_password = False
            profile.save()
            officers.append(user)
            credentials.append({
                "name": user.get_full_name(), "username": username, "password": password,
                "employee_id": profile.employee_id, "phone": profile.phone_number,
                "role": profile.get_role_display(), "assembly": assembly.name,
            })
        return officers

    def _populate(self, assembly, preflight, run_id):
        today = timezone.localdate()
        dates = registration_dates(today)
        citizen_credentials = []
        officer_credentials = []
        namespace = preflight["identity_namespace"]
        officers = self._create_officers(assembly, officer_credentials, namespace)

        owners = []
        property_owner_map = []
        cursor = 0
        for owner_index, count in enumerate(owner_property_counts()):
            owner = Owner.objects.create(
                **self._owner_data(owner_index, assembly, namespace)
            )
            account = link_or_create_citizen_for_owner(owner)
            if not account.get("created"):
                raise CommandError(f"A new Citizen account was not created for {owner.full_name}; aborting.")
            citizen_credentials.append({
                "owner": owner, "username": account["username"],
                "password": account["temporary_password"], "user": account["user"],
            })
            Owner.objects.filter(pk=owner.pk).update(created_at=dates[cursor])
            User.objects.filter(pk=account["user"].pk).update(date_joined=dates[cursor])
            UserProfile.objects.filter(user=account["user"]).update(created_at=dates[cursor])
            owner.refresh_from_db()
            owners.append(owner)
            property_owner_map.extend([owner] * count)
            cursor += count

        properties = []
        assignments = []
        visits = []
        payments = []
        for index in range(TARGET_COUNT):
            community = preflight["areas"][index % len(preflight["areas"])]
            if community.sub_metro != "ABS":
                raise CommandError("Non-ABS Community Area detected; transaction aborted.")
            property_use, building_type = PROPERTY_COMBINATIONS[index % len(PROPERTY_COMBINATIONS)]
            policy = RatePolicy.get_applicable_policy(
                assembly=assembly, property_use=property_use, community_area=community,
                building_type=building_type, on_date=today, year=today.year,
            )
            if not policy:
                raise CommandError(f"Rate Policy disappeared for {property_use}/{building_type}.")
            registered_at = dates[index]
            verified = index < VERIFIED_COUNT
            prop = Property.objects.create(
                assembly=assembly,
                owner=property_owner_map[index],
                address_line=f"{14 + index} {community.name} Road",
                area_town=community.name,
                suburb=community.name,
                landmark=("Near the community market" if index % 3 == 0 else ""),
                digital_address=(f"GA-{120 + index:03d}-{4000 + index}" if index % 2 == 0 else ""),
                community_area=community,
                latitude=Decimal("5.530000") + Decimal(index % 20) / Decimal("10000"),
                longitude=Decimal("-0.250000") + Decimal(index % 17) / Decimal("10000"),
                property_use=property_use,
                building_type=building_type,
                property_class=policy.property_class,
                applied_rate_policy=policy,
                number_of_floors=1 + (index % 4),
                number_of_units=1 + (index % 6),
                year_built=1985 + (index % 39),
                occupancy_status=("vacant" if index % 13 == 0 else "occupied"),
                rateable_value=Decimal("65000.00") + Decimal(index * 3750),
                registration_source="admin",
                verification_status="pending",
                is_active=True,
            )
            Property.objects.filter(pk=prop.pk).update(created_at=registered_at)
            prop.refresh_from_db()
            bill = Bill.objects.get(property_record=prop, billing_year=today.year)
            bill.issued_at = aware(date(today.year, min(index % max(today.month, 1) + 1, today.month), 5 + index % 20))
            bill.due_date = date(today.year, 12, 31)
            bill.save()

            officer = officers[index % len(officers)]
            assignment_at = registered_at + timedelta(days=2 + index % 10)
            assignment = FieldAssignment.objects.create(
                assembly=assembly, property=prop, officer=officer,
                status="completed" if verified else ("assigned" if index < 88 else "in_progress"),
                priority=("high" if index % 9 == 0 else "medium"),
                due_date=(assignment_at + timedelta(days=14)).date(),
                notes="Routine property verification assignment.",
                assigned_at=assignment_at,
                completed_at=(assignment_at + timedelta(days=3 + index % 8) if verified else None),
            )
            assignments.append(assignment)

            if verified:
                visit_at = assignment.completed_at
                prop.verification_status = "verified"
                prop.last_verified_at = visit_at
                prop.save(update_fields=["verification_status", "last_verified_at", "updated_at"])
                visit = FieldVisit.objects.create(
                    assembly=assembly, property=prop, officer=officer,
                    visit_type="verification", submitted_verification_type="property_verification",
                    payment_status_seen="unknown", outcome="compliant",
                    submitted_verification_status="verified", visited_at=visit_at,
                    latitude=prop.latitude, longitude=prop.longitude,
                    gps_accuracy_meters=Decimal("8.00") + Decimal(index % 6),
                    gps_distance_meters=Decimal("0.00"), gps_validation_status="matched",
                    notes="Owner details, property use and rateable characteristics confirmed on site.",
                )
                visits.append(visit)
                bill.refresh_from_db()
                if index < FULLY_PAID_COUNT:
                    amount = bill.balance
                elif index < FULLY_PAID_COUNT + PART_PAID_COUNT:
                    amount = (bill.balance * Decimal("0.40")).quantize(Decimal("0.01"))
                else:
                    amount = Decimal("0.00")
                if amount > 0:
                    paid_at = max(visit_at + timedelta(days=2 + index % 12), aware(date(today.year, 1, 1)))
                    if paid_at > timezone.now():
                        paid_at = timezone.now() - timedelta(hours=index + 1)
                    transaction_reference = f"PRMS-{today.year}-AS-{run_id[-7:-1]}-{index + 1:04d}"
                    payment = Payment.objects.create(
                        assembly=assembly, property=prop, bill=bill,
                        payer_name=prop.owner.full_name, payer_phone=prop.owner.primary_phone,
                        payer_email=prop.owner.email, property_reference_entered=prop.property_reference,
                        amount=amount, payment_method="momo",
                        provider=MOBILE_MONEY_PROVIDERS[index % len(MOBILE_MONEY_PROVIDERS)],
                        transaction_reference=transaction_reference,
                        external_reference=transaction_reference,
                        status="successful", paid_at=paid_at,
                    )
                    payment.refresh_from_db()
                    payments.append(payment)
            properties.append(prop)

        disputes = self._create_disputes(properties[:10])
        citizen_disputes = self._create_citizen_disputes(properties[:2])
        result = {
            "owners": owners, "properties": properties, "officers": officers,
            "assignments": assignments, "visits": visits, "payments": payments,
            "disputes": disputes, "citizen_disputes": citizen_disputes,
            "citizen_credentials": citizen_credentials,
            "officer_credentials": officer_credentials,
        }
        self._validate_result(result)
        return result

    def _create_disputes(self, properties):
        statuses = ["submitted", "under_review", "resolved", "rejected"]
        issue_types = [choice[0] for choice in BillDispute.ISSUE_TYPE_CHOICES]
        disputes = []
        for index, prop in enumerate(properties):
            bill = prop.bills.order_by("-billing_year").first()
            status = statuses[index % len(statuses)]
            dispute = BillDispute.objects.create(
                bill=bill, raised_by=prop.owner.linked_user,
                issue_type=issue_types[index % len(issue_types)],
                description="Owner requested a review of the recorded assessment details.",
                status=status,
                admin_notes=("Assessment reviewed." if status in {"resolved", "rejected"} else ""),
                reviewed_at=(timezone.now() - timedelta(days=index) if status in {"resolved", "rejected"} else None),
                resolution_summary=("Review completed and outcome communicated." if status == "resolved" else ""),
            )
            BillDispute.objects.filter(pk=dispute.pk).update(
                created_at=timezone.now() - timedelta(days=(index + 1) * 9),
            )
            dispute.refresh_from_db()
            disputes.append(dispute)
        return disputes

    def _create_citizen_disputes(self, properties):
        rows = []
        for index, prop in enumerate(properties):
            rows.append(CitizenDispute.objects.create(
                user=prop.owner.linked_user, assembly=prop.assembly, property_record=prop,
                bill=prop.bills.order_by("-billing_year").first(),
                dispute_type=("rate_assessment" if index == 0 else "payment_issue"),
                description="Please review the assessment details shown for this property.",
                status="submitted",
            ))
        return rows

    def _validate_result(self, result):
        properties = result["properties"]
        if len(properties) != TARGET_COUNT or any(p.community_area.sub_metro != "ABS" for p in properties):
            raise CommandError("Final Property count/geographic validation failed.")
        verified = [p for p in properties if Property.objects.get(pk=p.pk).verification_status == "verified"]
        pending = [p for p in properties if Property.objects.get(pk=p.pk).verification_status != "verified"]
        if len(verified) != 60 or len(pending) != 40:
            raise CommandError("Final verification distribution validation failed.")
        all_bills = [
            Bill.objects.get(property_record=p, billing_year=timezone.localdate().year)
            for p in properties
        ]
        verified_bills = [b for b in all_bills if b.property_record_id in {p.pk for p in verified}]
        status_counts = Counter(b.status for b in verified_bills)
        if (
            len(all_bills) != TARGET_COUNT
            or status_counts["paid"] != FULLY_PAID_COUNT
            or status_counts["part_paid"] != PART_PAID_COUNT
            or sum(b.amount_paid == 0 for b in verified_bills) != VERIFIED_UNPAID_COUNT
        ):
            raise CommandError("Final payment distribution validation failed.")
        payments = Payment.objects.filter(pk__in=[p.pk for p in result["payments"]])
        if (
            payments.count() != FULLY_PAID_COUNT + PART_PAID_COUNT
            or payments.exclude(status="successful").exists()
            or payments.exclude(payment_method="momo").exists()
            or payments.exclude(provider__in=MOBILE_MONEY_PROVIDERS).exists()
            or payments.exclude(applied_to_bill=True).exists()
        ):
            raise CommandError("Final Mobile Money payment validation failed.")
        if any(
            Payment.objects.filter(
                property=p, status="successful", applied_to_bill=True
            ).exists()
            for p in pending
        ):
            raise CommandError("A non-verified Property received an applied successful Payment.")
        if (
            len(result["owners"]) != OWNER_COUNT
            or len(result["assignments"]) != TARGET_COUNT
            or len(result["visits"]) != VERIFIED_COUNT
            or len(result["disputes"]) != 10
            or len(result["citizen_disputes"]) != 2
        ):
            raise CommandError("Final linked-record count validation failed.")

    def _manifest(self, assembly, run_id, report_path, result):
        def ids(key):
            return [obj.pk for obj in result[key]]
        return {
            "status": "completed", "execution_id": run_id,
            "assembly_id": assembly.pk, "assembly_short_code": assembly.short_code,
            "report_path": str(report_path.resolve()),
            "owner_ids": ids("owners"),
            "user_ids": [item["user"].pk for item in result["citizen_credentials"]],
            "field_officer_user_ids": ids("officers"),
            "property_ids": ids("properties"),
            "bill_ids": list(Bill.objects.filter(property_record__in=result["properties"]).values_list("pk", flat=True)),
            "payment_ids": ids("payments"), "assignment_ids": ids("assignments"),
            "field_visit_ids": ids("visits"), "bill_dispute_ids": ids("disputes"),
            "citizen_dispute_ids": ids("citizen_disputes"),
        }

    def _build_workbook(self, assembly, result):
        wb = Workbook()
        wb.remove(wb.active)
        properties = result["properties"]
        bills = {b.property_record_id: b for b in Bill.objects.filter(property_record__in=properties, billing_year=timezone.localdate().year)}
        assignments = {a.property_id: a for a in result["assignments"]}
        visits = {v.property_id: v for v in result["visits"]}
        payments = result["payments"]
        verified = [p for p in properties if p.verification_status == "verified"]
        paid = [p for p in verified if bills[p.pk].status == "paid"]
        partial = [p for p in verified if bills[p.pk].status == "part_paid"]
        unpaid = [p for p in verified if bills[p.pk].amount_paid == 0]
        total_due = sum((b.amount_due for b in bills.values()), Decimal("0"))
        total_paid = sum((b.amount_paid for b in bills.values()), Decimal("0"))
        summary = [
            ("Assembly", assembly.name), ("Sub-Metro", "Ablekuma South"),
            ("Execution timestamp", timezone.localtime().replace(tzinfo=None)),
            ("Total Properties", len(properties)), ("Total Owners", len(result["owners"])),
            ("Citizen accounts created", len(result["citizen_credentials"])),
            ("Field Officers created", len(result["officers"])),
            ("Verified", len(verified)), ("Pending", len(properties) - len(verified)),
            ("Paid", len(paid)), ("Partially Paid", len(partial)),
            ("Verified Unpaid", len(unpaid)), ("Total billed", total_due),
            ("Total collected", total_paid), ("Total outstanding", total_due - total_paid),
            ("Bill disputes", len(result["disputes"])),
        ]
        ws = wb.create_sheet("SUMMARY")
        ws.append(["Metric", "Value"])
        for row in summary: ws.append(list(row))

        ws = wb.create_sheet("OWNERS")
        ws.append([
            "Owner name", "Phone", "Alternate phone", "Email", "Ghana Card",
            "Residential address", "Property references", "Property count",
        ])
        props_by_owner = defaultdict(list)
        for prop in properties:
            props_by_owner[prop.owner_id].append(prop)
        for owner in result["owners"]:
            owner_props = props_by_owner[owner.pk]
            ws.append([
                owner.full_name, owner.primary_phone, owner.alternate_phone,
                owner.email, owner.ghana_card_number, owner.residential_address,
                ", ".join(p.property_reference for p in owner_props),
                len(owner_props),
            ])

        ws = wb.create_sheet("CITIZEN CREDENTIALS")
        ws.append(["Owner name", "Phone", "Email", "Username", "Temporary password", "Must change password", "Property references", "Verification", "Bill/payment status"])
        for item in result["citizen_credentials"]:
            owner = item["owner"]
            owner_props = props_by_owner[owner.pk]
            ws.append([owner.full_name, owner.primary_phone, owner.email, item["username"], item["password"], item["user"].profile.must_change_password, ", ".join(p.property_reference for p in owner_props), ", ".join(p.verification_status for p in owner_props), ", ".join(bills[p.pk].status for p in owner_props)])

        ws = wb.create_sheet("FIELD OFFICER CREDENTIALS")
        ws.append(["Name", "Username", "Temporary password", "Employee ID", "Phone", "Role", "Assembly", "Assignments", "Pending", "Completed"])
        for item, officer in zip(result["officer_credentials"], result["officers"]):
            officer_assignments = [a for a in result["assignments"] if a.officer_id == officer.pk]
            ws.append([item["name"], item["username"], item["password"], item["employee_id"], item["phone"], item["role"], item["assembly"], len(officer_assignments), sum(a.status in {"assigned", "in_progress"} for a in officer_assignments), sum(a.status == "completed" for a in officer_assignments)])

        ws = wb.create_sheet("FIELD OFFICER ASSIGNMENTS")
        ws.append([
            "Property reference", "Owner", "Field Officer", "Officer username",
            "Status", "Priority", "Assigned date", "Due date", "Completed date", "Notes",
        ])
        for assignment in result["assignments"]:
            ws.append([
                assignment.property.property_reference,
                assignment.property.owner.full_name,
                assignment.officer.get_full_name(), assignment.officer.username,
                assignment.status, assignment.priority,
                assignment.assigned_at.replace(tzinfo=None), assignment.due_date,
                assignment.completed_at.replace(tzinfo=None) if assignment.completed_at else None,
                assignment.notes,
            ])

        ws = wb.create_sheet("PROPERTIES")
        ws.append(["Property reference", "Owner", "Owner phone", "Community Area", "Sub-metro", "Address/location", "Property Use", "Property Class", "Building Type", "Rateable Value", "Verification", "Field Officer", "Registration date", "Verification date", "Bill number", "Amount due", "Amount paid", "Outstanding", "Bill status"])
        for prop in properties:
            bill = bills[prop.pk]; assignment = assignments[prop.pk]
            ws.append([prop.property_reference, prop.owner.full_name, prop.owner.primary_phone, prop.community_area.name, prop.community_area.sub_metro, prop.address_line, prop.get_property_use_display(), prop.property_class, prop.get_building_type_display(), prop.rateable_value, prop.verification_status, assignment.officer.get_full_name(), prop.created_at.replace(tzinfo=None), prop.last_verified_at.replace(tzinfo=None) if prop.last_verified_at else None, bill.bill_number, bill.amount_due, bill.amount_paid, bill.balance, bill.status])

        ws = wb.create_sheet("BILLS")
        ws.append([
            "Property reference", "Owner", "Bill number", "Billing year",
            "Principal", "Penalty", "Arrears", "Amount due", "Amount paid",
            "Outstanding", "Status", "Issued date", "Due date",
        ])
        for prop in properties:
            bill = bills[prop.pk]
            ws.append([
                prop.property_reference, prop.owner.full_name, bill.bill_number,
                bill.billing_year, bill.principal_amount, bill.penalty_amount,
                bill.arrears_brought_forward, bill.amount_due, bill.amount_paid,
                bill.balance, bill.status,
                bill.issued_at.replace(tzinfo=None) if bill.issued_at else None,
                bill.due_date,
            ])

        ws = wb.create_sheet("PAYMENTS")
        ws.append([
            "Property reference", "Owner", "Bill number", "Transaction reference",
            "External reference", "Payment method", "Provider", "Amount", "Status",
            "Reconciliation", "Applied to bill", "Paid date",
        ])
        for payment in payments:
            ws.append([
                payment.property.property_reference, payment.property.owner.full_name,
                payment.bill.bill_number, payment.transaction_reference,
                payment.external_reference, payment.get_payment_method_display(),
                payment.provider, payment.amount, payment.status,
                payment.reconciliation_status, payment.applied_to_bill,
                payment.paid_at.replace(tzinfo=None),
            ])

        ws = wb.create_sheet("FIELD VISITS")
        ws.append(["Property reference", "Owner", "Field Officer", "Assignment status", "Visit date", "Submitted status", "GPS status", "Verification date", "Notes"])
        for prop in properties:
            assignment = assignments[prop.pk]; visit = visits.get(prop.pk)
            ws.append([prop.property_reference, prop.owner.full_name, assignment.officer.get_full_name(), assignment.status, visit.visited_at.replace(tzinfo=None) if visit else None, visit.submitted_verification_status if visit else "", visit.gps_validation_status if visit else "", prop.last_verified_at.replace(tzinfo=None) if prop.last_verified_at else None, visit.notes if visit else assignment.notes])

        ws = wb.create_sheet("BILL DISPUTES")
        ws.append(["Property reference", "Bill", "Owner", "Issue type", "Status", "Created", "Resolved/reviewed"])
        for dispute in result["disputes"]:
            prop = dispute.bill.property_record
            ws.append([prop.property_reference, dispute.bill.bill_number, prop.owner.full_name, dispute.get_issue_type_display(), dispute.status, dispute.created_at.replace(tzinfo=None), dispute.reviewed_at.replace(tzinfo=None) if dispute.reviewed_at else None])

        ws = wb.create_sheet("CITIZEN DISPUTES")
        ws.append([
            "Property reference", "Bill", "Owner", "Dispute type", "Status",
            "Description", "Created", "Updated",
        ])
        for dispute in result["citizen_disputes"]:
            ws.append([
                dispute.property_record.property_reference,
                dispute.bill.bill_number if dispute.bill_id else "",
                dispute.property_record.owner.full_name,
                dispute.get_dispute_type_display(), dispute.status,
                dispute.description, dispute.submitted_at.replace(tzinfo=None),
                dispute.updated_at.replace(tzinfo=None),
            ])

        for sheet in wb.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="8A6500")
                cell.alignment = Alignment(horizontal="center")
            for index, column in enumerate(sheet.columns, 1):
                width = min(max(len(str(cell.value or "")) for cell in column) + 2, 45)
                sheet.column_dimensions[get_column_letter(index)].width = max(width, 12)
        output = BytesIO(); wb.save(output); return output.getvalue()

    def _print_result(self, result):
        props = result["properties"]
        bills = Bill.objects.filter(property_record__in=props, billing_year=timezone.localdate().year)
        self.stdout.write(f"Properties created: {len(props)}")
        self.stdout.write(f"Owners created: {len(result['owners'])}")
        self.stdout.write(f"Citizen accounts created: {len(result['citizen_credentials'])}")
        self.stdout.write(f"Field Officers created: {len(result['officers'])}")
        self.stdout.write(f"Assignments created: {len(result['assignments'])}")
        self.stdout.write(f"Field Visits created: {len(result['visits'])}")
        self.stdout.write(f"Bills in population: {bills.count()}")
        self.stdout.write(f"Payments created: {len(result['payments'])}")
        self.stdout.write(f"Bill disputes created: {len(result['disputes'])}")
        self.stdout.write(f"Total billed: {bills.aggregate(v=Sum('amount_due'))['v'] or 0}")
        self.stdout.write(f"Total collected: {bills.aggregate(v=Sum('amount_paid'))['v'] or 0}")


def secrets_token(index):
    # Passwords are unique per run and never written into source or the database
    # in plaintext. The index only prevents an unlikely within-run collision.
    import secrets
    return f"{secrets.randbelow(900000) + 100000}{index}"
