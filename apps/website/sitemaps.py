from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.catalog.models import Product


class StaticSitemap(Sitemap):
    changefreq = "weekly"

    def items(self):
        return ["home", "products", "quote", "service", "contact"]

    def location(self, item):
        return reverse(f"website:{item}")

    def priority(self, item):
        return 1.0 if item == "home" else 0.8


class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Product.objects.filter(is_active=True)

    def lastmod(self, obj):
        return obj.created_at
