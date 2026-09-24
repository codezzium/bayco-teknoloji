"""View adı → hareket kaydındaki Türkçe etiket ve hedef kayıt.

Middleware her POST'u buradan etiketler. Burada olmayan bir view ham view
adıyla loglanır; bunu önlemek için apps/staff/tests.py her panel rotasının
ya LABELS'ta ya da READ_ONLY'de olduğunu doğrular. Yeni bir view
eklediğinizde birine eklemeniz gerekir.

"{singular}" içeren etiketler generic CRUD/tanım kayıt defterindeki tekil
addan kurulur ("Duyuru ekledi", "Model sildi").
"""

from dataclasses import dataclass

LABELS = {
    # --- Kasa ---
    "stock:cart_add": "Sepete ürün ekledi",
    "stock:sell_device": "Cihazı sepete ekledi",
    "stock:cart_remove": "Sepetten ürün çıkardı",
    "stock:cart_qty": "Sepette adet değiştirdi",
    "stock:cart_price": "Sepette fiyat/indirim değiştirdi",
    "stock:cart_clear": "Sepeti boşalttı",
    "stock:cart_customer": "Sepete müşteri seçti",
    "stock:cart_trade_in": "Sepette takas değiştirdi",
    "stock:checkout": "Satışı tamamladı",
    # --- Satışlar ---
    "stock:sale_payment": "Ödeme kaydetti",
    "stock:sale_void": "Satışı iptal etti",
    "stock:sale_item_return": "Ürün iadesi aldı",
    # --- Cihazlar ---
    "stock:device_create": "Cihaz ekledi",
    "stock:device_edit": "Cihazı düzenledi",
    "stock:device_status": "Cihaz durumunu değiştirdi",
    "stock:device_publish": "Cihazı sitede yayınladı/kaldırdı",
    "stock:device_delete": "Cihazı sildi",
    # --- Aksesuarlar ---
    "stock:accessory_create": "Aksesuar ekledi",
    "stock:accessory_edit": "Aksesuarı düzenledi",
    "stock:accessory_adjust": "Aksesuar stoğunu değiştirdi",
    # --- Tanımlar ---
    "stock:simple_create": "{singular} ekledi",
    "stock:simple_edit": "{singular} düzenledi",
    "stock:simple_delete": "{singular} sildi",
    # --- Cariler ---
    "stock:contact_create": "Cari ekledi",
    "stock:contact_edit": "Cariyi düzenledi",
    "stock:contact_delete": "Cariyi sildi",
    # --- Giderler ---
    "stock:expense_create": "Gider ekledi",
    "stock:expense_edit": "Gideri düzenledi",
    "stock:expense_delete": "Gideri sildi",
    # --- Tarama, stok girişi, sayım ---
    "stock:scan_resolve": "Barkod okuttu",
    "stock:intake_add": "Stok girişi yaptı",
    "stock:stocktake_mark": "Sayımda ürün okuttu",
    "stock:stocktake_finish": "Sayımı bitirdi",
    "stock:stocktake_clear": "Sayımı temizledi",
    # --- Site içeriği ---
    "dashboard:crud_create": "{singular} ekledi",
    "dashboard:crud_edit": "{singular} düzenledi",
    "dashboard:crud_delete": "{singular} sildi",
    "dashboard:crud_toggle": "{singular} durumunu değiştirdi",
    "dashboard:settings": "Site ayarlarını değiştirdi",
    "dashboard:lead_toggle": "Talebin durumunu değiştirdi",
    "dashboard:lead_delete": "Talebi sildi",
    # --- Personel ---
    "staff:create": "Personel ekledi",
    "staff:edit": "Personeli düzenledi",
    "staff:password": "Kendi şifresini değiştirdi",
}

#: Aynı view'ın POST'taki bir alana göre farklı iş yaptığı durumlar.
BY_PARAM = {
    "stock:scan_resolve": ("mode", {
        "lookup": "Barkod sorguladı",
        "sale": "Barkodla sepete ekledi",
        "intake": "Barkodla stok girişi yaptı",
        "count": "Sayımda barkod okuttu",
    }),
    "stock:accessory_adjust": ("mode", {
        "giris": "Aksesuar stok girişi yaptı",
        "sayim": "Aksesuar sayım düzeltmesi yaptı",
        "fire": "Aksesuar fire kaydetti",
    }),
}

#: Yalnızca okuma yapan (ya da loglanmaması bilinçli) rotalar. Yetkisiz
#: denemelerde başlık olarak kullanılır.
READ_ONLY = {
    "dashboard:home": "Genel Bakış",
    "dashboard:login": "Giriş",           # signal'ler loglar
    "dashboard:logout": "Çıkış",          # signal'ler loglar
    "dashboard:manifest": "Uygulama bildirimi",
    "dashboard:leads": "Talepler",
    "dashboard:crud_list": "{title}",
    "stock:overview": "Stok özeti",
    "stock:scan": "Barkod Tara",
    "stock:device_list": "Cihazlar",
    "stock:device_by_code": "Cihaz",
    "stock:device_detail": "Cihaz",
    "stock:accessory_list": "Aksesuarlar",
    "stock:accessory_detail": "Aksesuar",
    "stock:simple_list": "{title}",
    "stock:pos": "Kasa",
    "stock:product_search": "Kasa ürün arama",
    "stock:contact_search": "Kasa müşteri arama",
    "stock:sale_list": "Satışlar",
    "stock:sale_detail": "Satış",
    "stock:receipt": "Fiş",
    "stock:contact_list": "Cariler",
    "stock:contact_detail": "Cari",
    "stock:expense_list": "Giderler",
    "stock:intake": "Stok Girişi",
    "stock:stocktake": "Sayım",
    "stock:label_print": "Etiket",
    "stock:niimbot_png": "Etiket görseli",
    "stock:reports": "Raporlar",
    "staff:list": "Personel",
    "staff:logs": "Hareket Kayıtları",
}

#: POST'u olan ama ekrana karşılık gelen GET'i de olan form view'ları: GET'te
#: yetkisiz denemenin başlığı. (POST etiketi LABELS'tan gelir.)
FORM_PAGES = {
    "stock:device_create": "Cihaz ekleme", "stock:device_edit": "Cihaz düzenleme",
    "stock:accessory_create": "Aksesuar ekleme",
    "stock:accessory_edit": "Aksesuar düzenleme",
    "stock:simple_create": "{title}", "stock:simple_edit": "{title}",
    "stock:contact_create": "Cari ekleme", "stock:contact_edit": "Cari düzenleme",
    "stock:expense_create": "Gider ekleme", "stock:expense_edit": "Gider düzenleme",
    "dashboard:crud_create": "{title}", "dashboard:crud_edit": "{title}",
    "dashboard:settings": "Site Ayarları",
    "staff:create": "Personel ekleme", "staff:edit": "Personel düzenleme",
    "staff:password": "Şifre değiştirme",
}


@dataclass
class Described:
    view_name: str
    label: str
    target: str = ""


def _registry(view_name, kwargs):
    """Generic CRUD / tanım rotalarının yapılandırması (singular, title, model)."""
    if view_name.startswith("dashboard:crud_"):
        from apps.dashboard.views import CRUD
        return CRUD.get(kwargs.get("key"))
    if view_name.startswith("stock:simple_"):
        from apps.stock.views.catalog import SIMPLE
        return SIMPLE.get(kwargs.get("key"))
    return None


def _target_model(view_name, kwargs):
    from django.contrib.auth import get_user_model

    from apps.stock.models import Accessory, Contact, Device, Expense, Sale

    cfg = _registry(view_name, kwargs)
    if cfg:
        return cfg["model"]
    if view_name.startswith("dashboard:lead_"):
        from apps.dashboard.views import LEAD_MODELS
        return LEAD_MODELS.get(kwargs.get("tip"))
    name = view_name.split(":", 1)[-1]
    if view_name == "staff:edit":
        return get_user_model()
    for prefix, model in (("device_", Device), ("sell_device", Device),
                          ("accessory_", Accessory), ("sale_", Sale),
                          ("receipt", Sale), ("contact_", Contact),
                          ("expense_", Expense)):
        if name.startswith(prefix):
            return model
    return None


def _format_target(obj) -> str:
    title = getattr(obj, "title", None)
    if title and obj.__class__.__name__ == "Expense":
        return f"{obj.get_kind_display()} · {title}"
    if hasattr(obj, "get_username") and callable(obj.get_username):
        return obj.get_username()
    return str(obj)


def _post_target(view_name, post):
    """Kaydı URL'de değil POST'ta taşıyan kasa/sayım işlemleri: (model, pk)."""
    from apps.stock.models import Accessory, Contact, Device

    if post is None:
        return None, None
    if view_name == "stock:cart_add":
        return (Device if post.get("kind") == "cihaz" else Accessory), post.get("id")
    if view_name in ("stock:intake_add", "stock:stocktake_mark"):
        return Accessory, post.get("accessory")
    if view_name == "stock:cart_customer":
        return Contact, post.get("customer")
    return None, None


def resolve_target(view_name, kwargs, post=None) -> str:
    """İşlemin dokunduğu kaydın adı ("Fiş S-000123", "BYC-0042 · …").

    View ÇALIŞMADAN önce çağrılır ki silinen kaydın adı da loga geçsin.
    """
    pk = kwargs.get("pk")
    model = _target_model(view_name, kwargs) if pk is not None else None
    if model is None:
        model, pk = _post_target(view_name, post)
    if model is None or not str(pk or "").isdigit():
        return ""
    obj = model._default_manager.filter(pk=pk).first()
    return _format_target(obj) if obj is not None else f"#{pk}"


def label_for(view_name, kwargs, method="POST", post=None) -> str:
    cfg = _registry(view_name, kwargs) or {}
    if method == "POST" and view_name in BY_PARAM and post is not None:
        field, choices = BY_PARAM[view_name]
        label = choices.get(post.get(field, ""))
        if label:
            return label
    if method == "POST" and view_name in LABELS:
        template = LABELS[view_name]
    else:
        template = FORM_PAGES.get(view_name) or READ_ONLY.get(view_name)
        if template is None:
            return view_name or "?"
    return template.format(singular=cfg.get("singular", "Kayıt"),
                           title=cfg.get("title", "Kayıt"))


def describe(request) -> Described:
    """İsteğin etiketini ve hedef kaydını çıkarır (rota bulunamazsa yol)."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return Described(view_name="", label=request.path)
    view_name = match.view_name
    post = request.POST if request.method == "POST" else None
    try:
        target = resolve_target(view_name, match.kwargs, post)
    except Exception:  # noqa: BLE001 — geçersiz pk vs.; log yine yazılsın
        target = ""
    return Described(view_name=view_name,
                     label=label_for(view_name, match.kwargs, request.method, post),
                     target=target)


#: Log ekranında ve CSV'de POST alan adlarının Türkçesi. Burada olmayan alan
#: kendi adıyla (ör. "shelf") gösterilir.
FIELD_LABELS = {
    "id": "Kayıt no", "kind": "Tür", "qty": "Adet", "quantity": "Adet",
    "delta": "Adet değişimi", "price": "Fiyat", "discount": "İndirim",
    "amount": "Tutar", "paid_amount": "Tahsil edilen", "payment_method": "Ödeme şekli",
    "method": "Ödeme şekli", "due_date": "Vade", "paid_at": "Ödeme zamanı",
    "customer": "Müşteri", "remove": "Çıkarılan", "note": "Not", "reason": "Sebep",
    "refund": "Para iadesi", "status": "Durum", "mode": "Mod", "code": "Okutulan kod",
    "manual": "Elle girilen kod", "counted": "Sayılan", "counted_qty": "Sayılan adet",
    "confirm_prices": "Fiyat değişikliği onayı", "device_model": "Model",
    "accessory": "Aksesuar", "role": "Rol", "next": "Dönüş adresi",
    "unit_cost": "Birim alış", "list_price": "Satış fiyatı",
    "purchase_price": "Alış fiyatı", "cost": "Alış fiyatı",
    "imei1": "IMEI 1", "imei2": "IMEI 2", "storage": "Hafıza", "color": "Renk",
}


def field_label(key: str) -> str:
    if key.startswith("perm_"):
        from .access import ACCESS
        item = ACCESS.get(key[5:])
        if item:
            return f"Yetki: {item.label}"
    return FIELD_LABELS.get(key, key)
