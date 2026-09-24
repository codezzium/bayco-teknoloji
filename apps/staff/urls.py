from django.urls import path

from . import views

app_name = "staff"

# config/urls.py'de `panel/`den ÖNCE monte edilir; boş yol ZORUNLU (bkz.
# apps/stock/urls.py'deki not — aksi halde dashboard'un <str:key>/ yakalayıcısı).
urlpatterns = [
    path("", views.staff_list, name="list"),
    path("ekle/", views.staff_form, name="create"),
    path("<int:pk>/duzenle/", views.staff_form, name="edit"),
    path("sifre/", views.password_change, name="password"),
    path("loglar/", views.log_list, name="logs"),
]
