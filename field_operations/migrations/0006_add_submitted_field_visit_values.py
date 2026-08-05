from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "field_operations",
            "0005_align_field_visit_choices",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldvisit",
            name="submitted_verification_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("property_verification", "Property Verification"),
                    ("site_assessment", "Site Assessment"),
                    ("payment_verification", "Payment Verification"),
                    ("dispute_investigation", "Dispute Investigation"),
                    ("follow_up", "Follow Up Visit"),
                ],
                default="",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="fieldvisit",
            name="submitted_verification_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "Pending"),
                    ("under_review", "Under Review"),
                    ("verified", "Verified"),
                    ("flagged", "Flagged"),
                    ("possible_duplicate", "Possible Duplicate"),
                    ("rejected", "Rejected"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
