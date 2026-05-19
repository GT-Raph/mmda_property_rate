from django.apps import AppConfig


class CitizensConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "citizens"

    def ready(self):
        import citizens.signals