from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.website import views as website_views
from apps.website.sitemaps import ProductSitemap, StaticSitemap

admin.site.site_header = "Bayço Teknoloji Yönetimi"
admin.site.site_title = "Bayço Teknoloji"
admin.site.index_title = "Yönetim"

sitemaps = {"static": StaticSitemap, "products": ProductSitemap}

urlpatterns = [
    path("yonetim/", admin.site.urls),
    path("panel/", include("apps.dashboard.urls")),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", website_views.robots_txt, name="robots"),
    path("", include("apps.website.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
