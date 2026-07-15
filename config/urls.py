from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Bayço Teknoloji Yönetimi"
admin.site.site_title = "Bayço Teknoloji"
admin.site.index_title = "Yönetim"

urlpatterns = [
    path("yonetim/", admin.site.urls),
    path("panel/", include("apps.dashboard.urls")),
    path("", include("apps.website.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
