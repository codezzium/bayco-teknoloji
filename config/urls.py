from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.dashboard import views as dashboard_views
from apps.website import views as website_views
from apps.website.sitemaps import ProductSitemap, StaticSitemap

admin.site.site_header = "Bayço Teknoloji Yönetimi"
admin.site.site_title = "Bayço Teknoloji"
admin.site.index_title = "Yönetim"

sitemaps = {"static": StaticSitemap, "products": ProductSitemap}

urlpatterns = [
    path("yonetim/", admin.site.urls),
    # SIRA KRİTİK: apps/dashboard/urls.py bir `<str:key>/` yakalayıcısıyla biter.
    # `panel/stok/` bu satırdan sonra gelirse tek segmentli /panel/stok/ isteği
    # crud_list(key="stok") ile eşleşip "Bölüm bulunamadı" 404'ü döner.
    # `panel/personel/` için de aynısı geçerli.
    path("panel/stok/", include("apps.stock.urls")),
    path("panel/personel/", include("apps.staff.urls")),
    path("panel/", include("apps.dashboard.urls")),
    # KÖKTE olmak ZORUNDA: service worker yalnızca kendi yolunun altını
    # denetleyebilir; /panel/sw.js olsaydı kapsam /panel/ ile sınırlı kalırdı —
    # bu örnekte yeterdi ama kayıt sırasında verilen kapsamı daraltmak da
    # mümkün, tersi değil. Kökte durması ileride vitrin sitesini de
    # kapsayabilmesini açık bırakır.
    path("sw.js", dashboard_views.service_worker, name="service_worker"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", website_views.robots_txt, name="robots"),
    path("", include("apps.website.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
