from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "field_operations",
            "0004_one_active_assignment_per_property",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="fieldvisit",
            name="visit_type",
            field=models.CharField(
                choices=[
                    (
                        "verification",
                        "Property Verification",
                    ),
                    (
                        "enforcement",
                        "Enforcement",
                    ),
                    (
                        "follow_up",
                        "Follow Up",
                    ),
                ],
                max_length=20,
            ),
        ),
    ]