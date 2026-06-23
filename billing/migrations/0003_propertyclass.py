from django.db import migrations, models
import django.db.models.deletion


PROPERTY_USE_CHOICES = [
    ("residential", "Residential"),
    ("commercial", "Commercial"),
    ("industrial", "Industrial"),
    ("mixed_use", "Mixed Use"),
    ("institutional", "Institutional"),
]


def copy_existing_rate_policy_classes(apps, schema_editor):
    RatePolicy = apps.get_model("billing", "RatePolicy")
    PropertyClass = apps.get_model("billing", "PropertyClass")

    for policy in RatePolicy.objects.exclude(property_class="").iterator():
        class_name = (policy.property_class or "").strip()

        if not class_name:
            continue

        property_class, _ = PropertyClass.objects.get_or_create(
            assembly_id=policy.assembly_id,
            property_use=policy.property_use,
            name=class_name,
            defaults={
                "is_active": True,
            },
        )

        area_ids = list(
            policy.covered_areas.values_list("id", flat=True)
        )

        if area_ids:
            property_class.covered_areas.add(*area_ids)


def reverse_copy_existing_rate_policy_classes(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        (
            "billing",
            "0002_initial",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="PropertyClass",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "property_use",
                    models.CharField(
                        choices=PROPERTY_USE_CHOICES,
                        max_length=20,
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=100),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True),
                ),
                (
                    "assembly",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="property_classes",
                        to="admins.assembly",
                    ),
                ),
                (
                    "covered_areas",
                    models.ManyToManyField(
                        help_text=(
                            "Select all communities/areas that belong to this class. "
                            "These areas will be copied automatically into a Rate Policy "
                            "when this class is selected."
                        ),
                        related_name="property_classes",
                        to="billing.communityarea",
                    ),
                ),
            ],
            options={
                "verbose_name": "Property class",
                "verbose_name_plural": "Property classes",
                "ordering": [
                    "assembly__name",
                    "property_use",
                    "name",
                ],
            },
        ),
        migrations.AddIndex(
            model_name="propertyclass",
            index=models.Index(
                fields=[
                    "assembly",
                    "property_use",
                    "is_active",
                ],
                name="billing_pr_assembl_a04f3d_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="propertyclass",
            index=models.Index(
                fields=["name"],
                name="billing_pr_name_d4309a_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="propertyclass",
            constraint=models.UniqueConstraint(
                fields=(
                    "assembly",
                    "property_use",
                    "name",
                ),
                name="unique_property_class_per_use",
            ),
        ),
        migrations.AlterField(
            model_name="ratepolicy",
            name="property_class",
            field=models.CharField(
                help_text=(
                    "Select a class configured under Property classes in Django admin."
                ),
                max_length=100,
            ),
        ),
        migrations.AlterField(
            model_name="ratepolicy",
            name="covered_areas",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Automatically populated from the selected property class. "
                    "To change these areas, edit the Property class master record."
                ),
                related_name="rate_policies",
                to="billing.communityarea",
            ),
        ),
        migrations.RunPython(
            copy_existing_rate_policy_classes,
            reverse_copy_existing_rate_policy_classes,
        ),
    ]
