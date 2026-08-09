from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse

from apps.catalog.models import Product


class StaticSitemap(Sitemap):
    """Sabit sayfalar.

    changefreq sayfa başına ayrışır: ürün listesi stok girildikçe değişir,
    iletişim sayfası neredeyse hiç değişmez. Google'a hepsi için "weekly"
    demek tarama bütçesini boşa harcatır.

    `protocol` bilerek ayarlanmadı: Django o zaman request.scheme kullanır ve
    SECURE_PROXY_SSL_HEADER sayesinde üretimde https, geliştirmede http üretir.
    Sabit "https" yazmak yerel sitemap.xml'i kullanılamaz hale getirirdi.
    """

    _PAGES = {
        # ad: (öncelik, değişim sıklığı)
        "home": (1.0, "daily"),
        "products": (0.9, "daily"),
        "service": (0.8, "monthly"),
        "quote": (0.8, "monthly"),
        "contact": (0.6, "yearly"),
    }

    def items(self):
        return list(self._PAGES)

    def location(self, item):
        return reverse(f"website:{item}")

    def priority(self, item):
        return self._PAGES[item][0]

    def changefreq(self, item):
        return self._PAGES[item][1]

    def lastmod(self, item):
        # Ana sayfa ve liste vitrini ürünlerle birlikte tazelenir; Google
        # değişmeyen bir lastmod gördüğü sayfayı daha seyrek tarar.
        if item in ("home", "products"):
            return Product.objects.filter(is_active=True).aggregate(
                m=Max("created_at")
            )["m"]
        return None


class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7
    limit = 5000

    def items(self):
        return Product.objects.filter(is_active=True).order_by("-created_at")

    def lastmod(self, obj):
        return obj.created_at
