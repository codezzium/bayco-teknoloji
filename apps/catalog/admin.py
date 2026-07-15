from django.contrib import admin

from .models import Brand, Product, ProductImage


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("name",)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 3


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "condition", "price", "is_featured", "is_active", "order")
    list_editable = ("is_featured", "is_active", "order")
    list_filter = ("condition", "brand", "is_featured", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline]
