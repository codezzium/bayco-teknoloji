from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("giris/", views.login_view, name="login"),
    path("cikis/", views.logout_view, name="logout"),
    path("", views.home, name="home"),

    # Ayarlar & talepler (generic <key>'den ÖNCE)
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("ayarlar/", views.settings_view, name="settings"),
    path("talepler/", views.leads, name="leads"),
    path("talep/<str:tip>/<int:pk>/durum/", views.lead_toggle, name="lead_toggle"),
    path("talep/<str:tip>/<int:pk>/sil/", views.lead_delete, name="lead_delete"),

    # Generic CRUD
    path("<str:key>/", views.crud_list, name="crud_list"),
    path("<str:key>/ekle/", views.crud_form, name="crud_create"),
    path("<str:key>/<int:pk>/duzenle/", views.crud_form, name="crud_edit"),
    path("<str:key>/<int:pk>/sil/", views.crud_delete, name="crud_delete"),
    path("<str:key>/<int:pk>/toggle/<str:field>/", views.crud_toggle, name="crud_toggle"),
]
