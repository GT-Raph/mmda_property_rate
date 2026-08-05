from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError
from django.utils import timezone


def close_duplicate_active_assignments(
    apps,
    schema_editor,
):
    FieldAssignment = apps.get_model(
        "field_operations",
        "FieldAssignment",
    )

    active_statuses = [
        "assigned",
        "in_progress",
    ]

    property_ids = (
        FieldAssignment.objects
        .filter(status__in=active_statuses)
        .values_list("property_id", flat=True)
        .distinct()
    )

    for property_id in property_ids.iterator():
        active_ids = list(
            FieldAssignment.objects
            .filter(
                property_id=property_id,
                status__in=active_statuses,
            )
            .order_by(
                "-assigned_at",
                "-id",
            )
            .values_list("id", flat=True)
        )

        if len(active_ids) <= 1:
            continue

        FieldAssignment.objects.filter(
            id__in=active_ids[1:]
        ).update(
            status="cancelled",
            completed_at=timezone.now(),
        )


def cannot_restore_duplicate_active_assignments(
    apps,
    schema_editor,
):
    raise IrreversibleError(
        (
            "This migration cannot be reversed because "
            "cancelled duplicate assignments cannot be "
            "reconstructed automatically."
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            "field_operations",
            (
                "0003_rename_field_opera_assembl_25c067_idx_"
                "field_opera_assembl_294127_idx_and_more"
            ),
        ),
    ]

    operations = [
        migrations.RunPython(
            close_duplicate_active_assignments,
            cannot_restore_duplicate_active_assignments,
        ),
        migrations.RemoveConstraint(
            model_name="fieldassignment",
            name=(
                "unique_active_assignment_per_property_officer"
            ),
        ),
        migrations.AddConstraint(
            model_name="fieldassignment",
            constraint=models.UniqueConstraint(
                fields=("property",),
                condition=models.Q(
                    status__in=[
                        "assigned",
                        "in_progress",
                    ]
                ),
                name=(
                    "unique_active_assignment_per_property"
                ),
            ),
        ),
    ]