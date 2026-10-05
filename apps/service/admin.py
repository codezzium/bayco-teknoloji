"""Teknik servis admin'i — yalnızca superuser (para ve ekran kilidi içerir)."""

from django.contrib import admin

from apps.stock.admin import MoneyGatedAdmin

from .models import (
    RepairShop,
    RepairShopPayment,
    ServiceCost,
    ServiceOutsource,
    ServicePayment,
    ServiceStatusLog,
    ServiceTicket,
)


class PaymentInline(admin.TabularInline):
    model = ServicePayment
    extra = 0


class CostInline(admin.TabularInline):
    model = ServiceCost
    extra = 0


class OutsourceInline(admin.TabularInline):
    model = ServiceOutsource
    extra = 0


@admin.register(ServiceTicket)
class ServiceTicketAdmin(MoneyGatedAdmin):
    list_display = ("ticket_no", "customer", "device_model", "status", "received_at",
                    "final_price", "paid_total")
    list_filter = ("status",)
    search_fields = ("ticket_no", "imei", "serial_no", "customer__full_name",
                     "customer__phone")
    raw_id_fields = ("customer", "device_model")
    readonly_fields = ("ticket_no", "paid_total", "closed_at")
    inlines = [PaymentInline, CostInline, OutsourceInline]


@admin.register(ServiceStatusLog)
class ServiceStatusLogAdmin(MoneyGatedAdmin):
    list_display = ("ticket", "from_status", "to_status", "created_by", "created_at")


@admin.register(RepairShop)
class RepairShopAdmin(MoneyGatedAdmin):
    list_display = ("name", "contact_name", "phone", "is_active")
    search_fields = ("name", "contact_name", "phone")


@admin.register(RepairShopPayment)
class RepairShopPaymentAdmin(MoneyGatedAdmin):
    list_display = ("shop", "amount", "method", "paid_at")
    list_filter = ("shop",)
