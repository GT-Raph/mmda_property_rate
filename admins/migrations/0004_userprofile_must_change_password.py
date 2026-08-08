from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "admins",
            (
                "0003_alter_userprofile_"
                "allowed_assemblies_and_more"
            ),
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
            ),
        ),
    ]