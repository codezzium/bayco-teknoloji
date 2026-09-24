from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db.models import ProtectedError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.catalog.models import Brand, Product
from apps.leads.models import ContactMessage, QuoteRequest, ServiceRequest
from apps.leads.utils import customer_wa
from apps.sitecore.models import FAQ, SiteSettings, Slider, Testimonial
from apps.stock.permissions import (
    access_required,
    deny,
    has_access,
    in_panel,
    panel_required,
)

from .forms import (
    BrandForm,
    FAQForm,
    ProductForm,
    SiteSettingsForm,
    SliderForm,
    TestimonialForm,
)
from .utils import safe_next, with_param

# Panel girişi is_staff'a DEĞİL grup üyeliğine bağlıdır: is_staff aynı zamanda
# /yonetim/ (Django admin) anahtarıdır ve Personel oradan Device list_display'i
# üzerinden alış fiyatını görebilirdi. Bkz. apps/stock/permissions.py.
staff_required = panel_required


# CRUD kayıt defteri: URL slug -> yapılandırma. `access`: bölümü açan
# Personel tiki (apps/staff/access.py). Markalar tiksizdir: stok kartlarının
# zorunlu üst kaydıdır ve TANIMLAR'da durur.
CRUD = {
    "duyurular": {
        "model": Slider, "form": SliderForm, "title": "Duyurular / Slaytlar",
        "access": "content",
        "singular": "Duyuru", "template": "dashboard/lists/slider.html",
        "toggles": ["is_active"],
    },
    "urunler": {
        "model": Product, "form": ProductForm, "title": "Ürünler",
        "access": "content",
        "singular": "Ürün", "template": "dashboard/lists/product.html",
        "toggles": ["is_active", "is_featured"],
        "select": ["brand", "source_device__device_model__brand"],
    },
    "yorumlar": {
        "model": Testimonial, "form": TestimonialForm, "title": "Müşteri Yorumları",
        "access": "content",
        "singular": "Yorum", "template": "dashboard/lists/testimonial.html",
        "toggles": ["is_active"],
    },
    "sss": {
        "model": FAQ, "form": FAQForm, "title": "Sık Sorulan Sorular",
        "access": "content",
        "singular": "Soru", "template": "dashboard/lists/faq.html",
        "toggles": ["is_active"],
    },
    "markalar": {
        "model": Brand, "form": BrandForm, "title": "Markalar",
        "singular": "Marka", "template": "dashboard/lists/brand.html",
        "toggles": [],
        # `?next=` ile gelen stok formuna dönerken yeni marka seçili kalsın.
        "param": "brand",
    },
}


def _cfg(key):
    cfg = CRUD.get(key)
    if not cfg:
        raise Http404("Bölüm bulunamadı")
    return cfg


def _allowed(request, cfg, *extra) -> bool:
    keys = ([cfg["access"]] if cfg.get("access") else []) + list(extra)
    return all(has_access(request.user, key) for key in keys)


# ---------- Auth ----------

def login_view(request):
    if in_panel(request.user):
        return redirect("dashboard:home")
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = None
        if "\x00" not in username + password:
            user = authenticate(request, username=username, password=password)
        if user and in_panel(user):
            login(request, user)
            nxt = request.GET.get("next", "")
            # ?next= doğrulanmadan kullanılırsa açık yönlendirme (open redirect)
            # açığı olur: saldırgan panel giriş bağlantısıyla kullanıcıyı kendi
            # sitesine düşürebilir.
            if nxt and url_has_allowed_host_and_scheme(
                nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(nxt)
            return redirect("dashboard:home")
        if user is not None:
            # Şifre doğru ama panel grubunda değil: signal'ler bunu "başarılı"
            # sayar ve hiç loglamaz, çünkü login() hiç çağrılmaz.
            from apps.staff.audit import record
            from apps.staff.models import ActivityLog
            record(kind=ActivityLog.Kind.YETKISIZ, request=request, user=user,
                   action="Panel yetkisi olmayan hesapla giriş denemesi")
        error = "Kullanıcı adı veya şifre hatalı ya da yetkiniz yok."
    return render(request, "dashboard/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("dashboard:login")


# ---------- Overview ----------

@staff_required
def home(request):
    from apps.stock import reports as stock_reports

    user = request.user
    show_leads = has_access(user, "leads")
    ctx = {
        "active": "home",
        "stats": {
            "quotes_new": QuoteRequest.objects.filter(is_handled=False).count(),
            "services_new": ServiceRequest.objects.filter(is_handled=False).count(),
            "messages_new": ContactMessage.objects.filter(is_handled=False).count(),
            "products": Product.objects.count(),
            "sliders": Slider.objects.filter(is_active=True).count(),
            "testimonials": Testimonial.objects.count(),
        },
        "stock": stock_reports.dashboard_kpis(user),
        "recent_products": stock_reports.recent_products(),
        "recent_quotes": QuoteRequest.objects.all()[:6] if show_leads else [],
        "recent_services": ServiceRequest.objects.all()[:4] if show_leads else [],
    }
    return render(request, "dashboard/home.html", ctx)


# ---------- Generic CRUD ----------

@staff_required
def crud_list(request, key):
    cfg = _cfg(key)
    if not _allowed(request, cfg):
        return deny(request)
    items = cfg["model"].objects.all()
    if cfg.get("select"):
        items = items.select_related(*cfg["select"])
    return render(request, cfg["template"], {
        "active": key, "items": items, "key": key,
        "title": cfg["title"], "singular": cfg["singular"],
    })


@staff_required
def crud_form(request, key, pk=None):
    cfg = _cfg(key)
    if not _allowed(request, cfg):
        return deny(request)
    instance = get_object_or_404(cfg["model"], pk=pk) if pk else None
    next_url = safe_next(request) if cfg.get("param") else ""
    if request.method == "POST":
        form = cfg["form"](request.POST, request.FILES, instance=instance)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"{cfg['singular']} kaydedildi.")
            if next_url:
                return redirect(with_param(next_url, cfg["param"], obj.pk))
            return redirect("dashboard:crud_list", key=key)
    else:
        form = cfg["form"](instance=instance)
    return render(request, "dashboard/form.html", {
        "active": key, "form": form, "key": key,
        "title": cfg["title"], "singular": cfg["singular"],
        "is_edit": instance is not None,
        "next_url": next_url,
    })


@staff_required
@require_POST
def crud_delete(request, key, pk):
    cfg = _cfg(key)
    if not _allowed(request, cfg, "delete"):
        return deny(request)
    obj = get_object_or_404(cfg["model"], pk=pk)
    try:
        obj.delete()
    except ProtectedError:
        messages.error(request, f"{cfg['singular']} stokta kullanıldığı için silinemez.")
        if request.headers.get("HX-Request"):
            return HttpResponse(status=204, headers={"HX-Refresh": "true"})
        return redirect("dashboard:crud_list", key=key)
    if request.headers.get("HX-Request"):
        return HttpResponse("")  # satırı DOM'dan kaldır
    messages.success(request, f"{cfg['singular']} silindi.")
    return redirect("dashboard:crud_list", key=key)


@staff_required
@require_POST
def crud_toggle(request, key, pk, field):
    cfg = _cfg(key)
    if not _allowed(request, cfg):
        return deny(request)
    if field not in cfg["toggles"]:
        raise Http404("Geçersiz alan")
    obj = get_object_or_404(cfg["model"], pk=pk)
    setattr(obj, field, not getattr(obj, field))
    obj.save(update_fields=[field])
    return render(request, "dashboard/partials/toggle.html", {
        "obj": obj, "key": key, "field": field, "value": getattr(obj, field),
    })


# ---------- Talepler (leads) ----------

@access_required("leads")
def leads(request):
    quotes = QuoteRequest.objects.all()[:100]
    services = ServiceRequest.objects.all()[:100]
    msgs = ContactMessage.objects.all()[:100]
    for q in quotes:
        q.wa = customer_wa(q.phone)
    for s in services:
        s.wa = customer_wa(s.phone)
    for m in msgs:
        m.wa = customer_wa(m.phone) if m.phone else None
    return render(request, "dashboard/leads.html", {
        "active": "talepler",
        "quotes": quotes, "services": services, "messages_list": msgs,
        "tab": request.GET.get("tab", "quote"),
    })


LEAD_MODELS = {"quote": QuoteRequest, "service": ServiceRequest, "contact": ContactMessage}


@access_required("leads")
@require_POST
def lead_toggle(request, tip, pk):
    model = LEAD_MODELS.get(tip)
    if not model:
        raise Http404
    obj = get_object_or_404(model, pk=pk)
    obj.is_handled = not obj.is_handled
    obj.save(update_fields=["is_handled"])
    return render(request, "dashboard/partials/lead_handled.html", {
        "obj": obj, "tip": tip,
    })


@access_required("leads", "delete")
@require_POST
def lead_delete(request, tip, pk):
    model = LEAD_MODELS.get(tip)
    if not model:
        raise Http404
    get_object_or_404(model, pk=pk).delete()
    return HttpResponse("")


# ---------- Site Ayarları ----------

@access_required("content")
def settings_view(request):
    obj = SiteSettings.load()
    if request.method == "POST":
        form = SiteSettingsForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Site ayarları güncellendi.")
            return redirect("dashboard:settings")
    else:
        form = SiteSettingsForm(instance=obj)
    return render(request, "dashboard/settings.html", {"active": "ayarlar", "form": form})


# ---------- Uygulama olarak yükleme (PWA) ----------
#
# İkisi de GİRİŞ İSTEMEZ ve bu bilinçlidir: tarayıcı bildirimi ve service
# worker'ı sayfadan bağımsız, bazen kimlik bilgisi olmadan çeker. Giriş
# duvarının arkasına konursa istek login'e yönlenir ve "Uygulama Olarak Yükle"
# düğmesi hiçbir hata vermeden ölür. İçlerinde marka adı ve ikonlardan başka
# bir şey yok — ikisi de sitede zaten açık.

def manifest(request):
    """PWA bildirimi. Kısayolun adı, simgesi ve açılış adresi buradan gelir."""
    site = SiteSettings.load()
    brand = site.brand_name.strip() or "Panel"
    icon = static("img/icon-192.png")

    return JsonResponse({
        # `id` sabit tutulmalı: değişirse tarayıcı kurulu uygulamayı tanımaz ve
        # ikinci bir kopya kurar.
        "id": "/panel/",
        "name": f"{brand} Yönetim Paneli",
        # Ana ekranda simgenin altına sığması için kısa ad ~12 karakteri geçmemeli.
        "short_name": f"{brand.split()[0]} Panel",
        "description": "Stok, kasa ve barkod işlemleri.",
        "lang": "tr",
        "dir": "ltr",
        "start_url": reverse("dashboard:home"),
        # Kapsam /panel/ ile sınırlı: "↗ Siteyi Gör" bağlantısı uygulama
        # penceresini vitrin sitesine götürmesin, normal tarayıcıda açılsın.
        "scope": "/panel/",
        "display": "standalone",
        "background_color": "#150c22",
        "theme_color": "#150c22",
        "icons": [
            {"src": icon, "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("img/icon-512.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            # Android ikonu daireye/squircle'a kırpar; ayrı bir maskable şart,
            # yoksa logonun kenarları kesilir.
            {"src": static("img/icon-maskable-512.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        # Simgeye uzun basınca çıkan kısayollar.
        "shortcuts": [
            {"name": "Satış Yap", "url": reverse("stock:pos"),
             "icons": [{"src": icon, "sizes": "192x192"}]},
            {"name": "Barkod Tara", "url": reverse("stock:scan"),
             "icons": [{"src": icon, "sizes": "192x192"}]},
        ],
    }, content_type="application/manifest+json")


def service_worker(request):
    """/sw.js — kök dizinden servis edilir.

    Konum pazarlık konusu değil: bir service worker yalnızca KENDİ yolunun
    altını denetleyebilir. /static/js/sw.js olsaydı kapsamı /static/js/ olurdu
    ve /panel/ hiç denetlenmezdi; Chrome da uygulamayı kurulabilir saymazdı.
    """
    response = render(request, "dashboard/sw.js",
                      content_type="text/javascript; charset=utf-8")
    # Tarayıcı sw.js'i zaten HTTP önbelleğini atlayarak tazeler, ama araya giren
    # bir vekil sunucu eski sürümü günlerce servis edebilir.
    response["Cache-Control"] = "no-cache"
    return response
