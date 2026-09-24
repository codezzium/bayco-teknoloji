from django.apps import AppConfig


class StaffConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.staff"
    verbose_name = "Personel"

    def ready(self):
        from . import signals  # noqa: F401  (giriş/çıkış logları)
