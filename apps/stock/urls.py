from django.urls import path

from .views import catalog, contacts, expenses, labels, pos, reports, scan

app_name = "stock"

# DİKKAT: apps/dashboard/urls.py bir `<str:key>/` yakalayıcısıyla biter ve
# config/urls.py'de `panel/stok/` ondan ÖNCE monte edilmiştir. Buradaki boş yol
# ("") tanımı ZORUNLUDUR — aksi halde /panel/stok/ isteği dashboard'un generic
# CRUD listesine düşer ve "Bölüm bulunamadı" 404'ü döner.
urlpatterns = [
    path("", reports.overview, name="overview"),

    # --- Tarama ---
    path("tara/", scan.scan_page, name="scan"),
    path("tara/coz/", scan.scan_resolve, name="scan_resolve"),

    # --- Cihazlar ---
    path("cihazlar/", catalog.device_list, name="device_list"),
    path("cihazlar/ekle/", catalog.device_form, name="device_create"),
    path("cihaz/kod/<str:stock_code>/", catalog.device_by_code, name="device_by_code"),
    path("cihaz/<int:pk>/", catalog.device_detail, name="device_detail"),
    path("cihaz/<int:pk>/duzenle/", catalog.device_form, name="device_edit"),
    path("cihaz/<int:pk>/durum/", catalog.device_status, name="device_status"),
    path("cihaz/<int:pk>/yayinla/", catalog.device_publish, name="device_publish"),
    path("cihaz/<int:pk>/sil/", catalog.device_delete, name="device_delete"),

    # --- Aksesuarlar ---
    path("aksesuarlar/", catalog.accessory_list, name="accessory_list"),
    path("aksesuarlar/ekle/", catalog.accessory_form, name="accessory_create"),
    path("aksesuar/<int:pk>/", catalog.accessory_detail, name="accessory_detail"),
    path("aksesuar/<int:pk>/duzenle/", catalog.accessory_form, name="accessory_edit"),
    path("aksesuar/<int:pk>/stok/", catalog.accessory_adjust, name="accessory_adjust"),

    # --- Model kataloğu & kategoriler ---
    path("tanim/<str:key>/", catalog.simple_list, name="simple_list"),
    path("tanim/<str:key>/ekle/", catalog.simple_form, name="simple_create"),
    path("tanim/<str:key>/<int:pk>/duzenle/", catalog.simple_form, name="simple_edit"),
    path("tanim/<str:key>/<int:pk>/sil/", catalog.simple_delete, name="simple_delete"),

    # --- Kasa ---
    path("satis/", pos.pos, name="pos"),
    path("satis/ara/", pos.product_search, name="product_search"),
    path("satis/cari-ara/", pos.contact_search, name="contact_search"),
    path("satis/sepet/ekle/", pos.cart_add, name="cart_add"),
    path("satis/cihaz/<int:pk>/sat/", pos.sell_device, name="sell_device"),
    path("satis/sepet/temizle/", pos.cart_clear, name="cart_clear"),
    path("satis/sepet/musteri/", pos.cart_customer, name="cart_customer"),
    path("satis/sepet/takas/", pos.cart_trade_in, name="cart_trade_in"),
    path("satis/sepet/<str:lid>/sil/", pos.cart_remove, name="cart_remove"),
    path("satis/sepet/<str:lid>/adet/", pos.cart_qty, name="cart_qty"),
    path("satis/sepet/<str:lid>/fiyat/", pos.cart_price, name="cart_price"),
    path("satis/tamamla/", pos.checkout, name="checkout"),

    # --- Satışlar ---
    path("satislar/", pos.sale_list, name="sale_list"),
    path("satislar/<int:pk>/", pos.sale_detail, name="sale_detail"),
    path("satislar/<int:pk>/fis/", pos.receipt, name="receipt"),
    path("satislar/<int:pk>/odeme/", pos.sale_payment, name="sale_payment"),
    path("satislar/<int:pk>/iptal/", pos.sale_void, name="sale_void"),
    path("satislar/<int:pk>/kalem/<int:item_id>/iade/", pos.sale_item_return,
         name="sale_item_return"),

    # --- Cariler ---
    path("cariler/", contacts.contact_list, name="contact_list"),
    path("cariler/ekle/", contacts.contact_form, name="contact_create"),
    path("cari/<int:pk>/", contacts.contact_detail, name="contact_detail"),
    path("cari/<int:pk>/duzenle/", contacts.contact_form, name="contact_edit"),
    path("cari/<int:pk>/sil/", contacts.contact_delete, name="contact_delete"),

    # --- Giderler ---
    path("giderler/", expenses.expense_list, name="expense_list"),
    path("giderler/ekle/", expenses.expense_form, name="expense_create"),
    path("gider/<int:pk>/duzenle/", expenses.expense_form, name="expense_edit"),
    path("gider/<int:pk>/sil/", expenses.expense_delete, name="expense_delete"),

    # --- Stok girişi & sayım ---
    path("giris/", scan.intake, name="intake"),
    path("giris/ekle/", scan.intake_add, name="intake_add"),
    path("sayim/", scan.stocktake, name="stocktake"),
    path("sayim/isaretle/", scan.stocktake_mark, name="stocktake_mark"),
    path("sayim/bitir/", scan.stocktake_finish, name="stocktake_finish"),
    path("sayim/temizle/", scan.stocktake_clear, name="stocktake_clear"),

    # --- Etiket ---
    path("etiket/", labels.label_print, name="label_print"),

    # --- Rapor ---
    path("rapor/", reports.reports, name="reports"),
]
