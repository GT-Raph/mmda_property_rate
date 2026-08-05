# Generated for PRMS verification workflow updates.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0002_alter_owner_linked_user"),
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
                    ("possible_duplicate", "Possible Duplicate"),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]