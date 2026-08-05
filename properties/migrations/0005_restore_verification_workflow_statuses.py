from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "properties",
            "0004_alter_property_verification_status",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="property",
            name="verification_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("under_review", "Under Review"),
                    ("verified", "Verified"),
                    ("flagged", "Flagged"),
                    (
                        "possible_duplicate",
                        "Possible Duplicate",
                    ),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]