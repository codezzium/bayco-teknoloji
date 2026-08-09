from django.contrib import admin

from .models import (
    Accessory,
    AccessoryCategory,
    Contact,
    Counter,
    Device,
    DeviceModel,
    DeviceStatusLog,
    Expense,
    Payment,
    Sale,
    SaleItem,
    StockMovement,
    TradeIn,
)


class MoneyGatedAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(DeviceModel)
class DeviceModelAdmin(admin.ModelAdmin):
    list_display = ("brand", "name", "kind", "is_active")
    list_editable = ("is_active",)
    list_filter = ("kind", "is_active", "brand")
    search_fields = ("name", "brand__name")


@admin.register(AccessoryCategory)
class AccessoryCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "company", "is_customer", "is_supplier")
    list_filter = ("is_customer", "is_supplier")
    search_fields = ("full_name", "phone", "phone_norm", "company", "tax_no")


@admin.register(Device)
class DeviceAdmin(MoneyGatedAdmin):
    list_display = ("stock_code", "device_model", "status", "imei1", "sold_at")
    list_filter = ("status", "condition", "acquisition", "device_model__brand")
    search_fields = ("stock_code", "imei1", "imei2", "serial_no")
    date_hierarchy = "purchase_date"
    readonly_fields = ("stock_code", "warranty_end", "days_in_stock", "search_blob")


@admin.register(Accessory)
class AccessoryAdmin(MoneyGatedAdmin):
    list_display = ("sku", "name", "variant", "stock_qty", "price", "is_active")
    list_filter = ("is_active", "category", "brand")
    search_fields = ("sku", "barcode", "name", "variant")
    readonly_fields = ("sku", "stock_qty", "search_blob")


@admin.register(StockMovement)
class StockMovementAdmin(MoneyGatedAdmin):
    list_display = ("created_at", "accessory", "quantity", "reason", "balance_after")
    list_filter = ("reason",)
    search_fields = ("accessory__name", "accessory__sku")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    readonly_fields = ("line_total", "line_cost")


@admin.register(Sale)
class SaleAdmin(MoneyGatedAdmin):
    list_display = ("receipt_no", "sold_at", "customer", "grand_total",
                    "payable_total", "paid_total", "status")
    list_filter = ("status", "sold_at")
    search_fields = ("receipt_no", "customer__full_name", "items__item_imei")
    date_hierarchy = "sold_at"
    inlines = [SaleItemInline]
    readonly_fields = ("receipt_no", "grand_total", "trade_in_total",
                       "payable_total", "paid_total")


@admin.register(Payment)
class PaymentAdmin(MoneyGatedAdmin):
    list_display = ("paid_at", "sale", "kind", "method", "amount")
    list_filter = ("kind", "method")


@admin.register(Expense)
class ExpenseAdmin(MoneyGatedAdmin):
    list_display = ("spent_on", "title", "kind", "amount", "device")
    list_filter = ("kind",)
    search_fields = ("title", "device__stock_code")
    date_hierarchy = "spent_on"


@admin.register(TradeIn)
class TradeInAdmin(MoneyGatedAdmin):
    list_display = ("sale", "device", "amount")


@admin.register(DeviceStatusLog)
class DeviceStatusLogAdmin(MoneyGatedAdmin):
    list_display = ("created_at", "device", "from_status", "to_status", "created_by")
    list_filter = ("to_status",)


@admin.register(Counter)
class CounterAdmin(MoneyGatedAdmin):
    list_display = ("key", "value")
