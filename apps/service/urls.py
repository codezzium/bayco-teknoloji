from django.urls import path

from . import views

app_name = "service"

# config/urls.py'de `panel/servis/` dashboard'un `<str:key>/` yakalayıcısından
# ÖNCE monte edilir; boş yol ("") tanımı bu yüzden zorunludur (bkz. stock/urls.py).
urlpatterns = [
    # --- Servis kayıtları ---
    path("", views.ticket_list, name="ticket_list"),
    path("yeni/", views.ticket_form, name="ticket_create"),
    path("<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("<int:pk>/duzenle/", views.ticket_form, name="ticket_edit"),
    path("<int:pk>/durum/", views.ticket_status, name="ticket_status"),
    path("<int:pk>/odeme/", views.ticket_payment, name="ticket_payment"),
    path("<int:pk>/kapat/", views.ticket_close, name="ticket_close"),
    path("<int:pk>/yeniden-ac/", views.ticket_reopen, name="ticket_reopen"),
    path("<int:pk>/sil/", views.ticket_delete, name="ticket_delete"),

    # --- Belgeler ---
    path("<int:pk>/kabul.pdf", views.ticket_pdf, name="ticket_pdf"),
    path("<int:pk>/fis/", views.ticket_slip, name="ticket_slip"),
    path("<int:pk>/fis.png", views.ticket_slip_png, name="ticket_slip_png"),

    # --- İç maliyet ---
    path("<int:pk>/maliyet/", views.cost_add, name="cost_add"),
    path("maliyet/<int:pk>/sil/", views.cost_delete, name="cost_delete"),

    # --- Teknik servise gönderme ---
    path("<int:pk>/teknik-servise-gonder/", views.outsource_send, name="outsource_send"),
    path("gonderim/<int:pk>/donus/", views.outsource_return, name="outsource_return"),
    path("gonderim/<int:pk>/bedel/", views.outsource_cost, name="outsource_cost"),
    path("gonderim/<int:pk>/iptal/", views.outsource_cancel, name="outsource_cancel"),

    # --- Teknik Servisler ---
    path("teknik-servisler/", views.shop_list, name="shop_list"),
    path("teknik-servisler/ekle/", views.shop_form, name="shop_create"),
    path("teknik-servis/<int:pk>/", views.shop_detail, name="shop_detail"),
    path("teknik-servis/<int:pk>/duzenle/", views.shop_form, name="shop_edit"),
    path("teknik-servis/<int:pk>/odeme/", views.shop_payment, name="shop_payment"),
    path("teknik-servis-odeme/<int:pk>/sil/", views.shop_payment_delete,
         name="shop_payment_delete"),
]
