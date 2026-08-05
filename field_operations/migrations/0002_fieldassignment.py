# Generated for PRMS field assignment workflow.
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("field_operations", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="FieldAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("assigned", "Assigned"), ("in_progress", "In Progress"), ("completed", "Completed"), ("rejected", "Rejected"), ("cancelled", "Cancelled")], default="assigned", max_length=20)),
                ("priority", models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")], default="medium", max_length=20)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("assigned_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("assembly", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="field_assignments", to="admins.assembly")),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="field_assignments_created", to=settings.AUTH_USER_MODEL)),
                ("officer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="field_assignments", to=settings.AUTH_USER_MODEL)),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="field_assignments", to="properties.property")),
            ],
            options={
                "ordering": ["-assigned_at", "-created_at"],
                "indexes": [
                    models.Index(fields=["assembly", "status"], name="field_opera_assembl_25c067_idx"),
                    models.Index(fields=["officer", "status"], name="field_opera_officer_85d403_idx"),
                    models.Index(fields=["property", "status"], name="field_opera_propert_6ec32e_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=Q(("status__in", ["assigned", "in_progress"])),
                        fields=("property", "officer"),
                        name="unique_active_assignment_per_property_officer",
                    )
                ],
            },
        ),
    ]