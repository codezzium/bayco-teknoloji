from django.contrib import admin

from .models import QuoteRequest, ServiceRequest, ContactMessage


@admin.register(QuoteRequest)
class QuoteRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "brand", "model", "phone", "is_handled", "created_at")
    list_filter = ("kind", "is_handled", "created_at")
    list_editable = ("is_handled",)
    search_fields = ("name", "phone", "model")


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "device", "issue", "phone", "is_handled", "created_at")
    list_filter = ("is_handled", "created_at")
    list_editable = ("is_handled",)
    search_fields = ("name", "phone", "device")


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "is_handled", "created_at")
    list_filter = ("is_handled", "created_at")
    list_editable = ("is_handled",)
    search_fields = ("name", "phone", "email")
