from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    """Salt okunur: hareket kaydı elle düzenlenebilseydi kanıt değeri kalmazdı."""

    list_display = ("at", "username", "kind", "action", "target", "ip")
    list_filter = ("kind",)
    search_fields = ("username", "action", "target")
    date_hierarchy = "at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
