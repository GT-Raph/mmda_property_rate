from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from admins.models import Assembly, ReportRun, UserProfile
from billing.models import Bill, BillDispute, RatePolicy
from field_operations.models import FieldVisit
from payments.models import Payment
from properties.models import Property


class Command(BaseCommand):
    help = "Create system role groups and assign permissions"

    def handle(self, *args, **options):
        role_permissions = {
            "sys_admin": "__all__",
            "revenue_admin": [
                "view_property", "add_property", "change_property",
                "view_bill", "add_bill", "change_bill",
                "view_payment", "add_payment", "change_payment",
                "view_fieldvisit", "add_fieldvisit", "change_fieldvisit",
                "view_billdispute", "change_billdispute",
                "view_ratepolicy", "add_ratepolicy", "change_ratepolicy",
                "view_reportrun", "add_reportrun", "change_reportrun",
                "view_assembly",
                "view_userprofile",
            ],
            "property_officer": [
                "view_property", "add_property", "change_property",
                "view_bill",
                "view_assembly",
                "view_userprofile",
            ],
            "payment_officer": [
                "view_payment", "add_payment", "change_payment",
                "view_bill", "change_bill",
                "view_property",
            ],
            "billing_officer": [
                "view_bill", "add_bill", "change_bill",
                "view_payment",
                "view_property",
                "view_ratepolicy", "add_ratepolicy", "change_ratepolicy",
                "view_reportrun", "add_reportrun",
            ],
            "report_officer": [
                "view_bill",
                "view_payment",
                "view_property",
                "view_fieldvisit",
                "view_billdispute",
                "view_reportrun", "add_reportrun", "change_reportrun",
            ],
            "field_officer": [
                "view_fieldvisit", "add_fieldvisit", "change_fieldvisit",
                "view_property",
            ],
            "citizen": [],
        }

        all_models = [
            Assembly,
            UserProfile,
            ReportRun,
            Property,
            Bill,
            BillDispute,
            RatePolicy,
            Payment,
            FieldVisit,
        ]

        all_permissions = Permission.objects.filter(
            content_type__in=[
                ContentType.objects.get_for_model(model) for model in all_models
            ]
        )

        for role_name, codename_list in role_permissions.items():
            group, created = Group.objects.get_or_create(name=role_name)

            if created:
                self.stdout.write(self.style.SUCCESS(f"Created group: {role_name}"))
            else:
                self.stdout.write(f"Updated group: {role_name}")

            group.permissions.clear()

            if codename_list == "__all__":
                group.permissions.set(all_permissions)
            else:
                perms = Permission.objects.filter(codename__in=codename_list)
                group.permissions.set(perms)

        self.stdout.write(self.style.SUCCESS("All role groups seeded successfully."))