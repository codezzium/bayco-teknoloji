from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.catalog.models import Brand, Product
from apps.leads.models import ContactMessage, QuoteRequest, ServiceRequest
from apps.leads.utils import customer_wa
from apps.sitecore.models import FAQ, SiteSettings, Slider, Testimonial
from apps.stock.permissions import can_see_money, in_panel, panel_required

from .forms import (
    BrandForm,
    FAQForm,
    ProductForm,
    SiteSettingsForm,
    SliderForm,
    TestimonialForm,
)

# Panel girişi is_staff'a DEĞİL grup üyeliğine bağlıdır: is_staff aynı zamanda
# /yonetim/ (Django admin) anahtarıdır ve Personel oradan Device list_display'i
# üzerinden alış fiyatını görebilirdi. Bkz. apps/stock/permissions.py.
staff_required = panel_required


# CRUD kayıt defteri: URL slug -> yapılandırma
CRUD = {
    "duyurular": {
        "model": Slider, "form": SliderForm, "title": "Duyurular / Slaytlar",
        "singular": "Duyuru", "template": "dashboard/lists/slider.html",
        "toggles": ["is_active"],
    },
    "urunler": {
        "model": Product, "form": ProductForm, "title": "Ürünler",
        "singular": "Ürün", "template": "dashboard/lists/product.html",
        "toggles": ["is_active", "is_featured"],
        "select": ["brand", "source_device__device_model__brand"],
    },
    "yorumlar": {
        "model": Testimonial, "form": TestimonialForm, "title": "Müşteri Yorumları",
        "singular": "Yorum", "template": "dashboard/lists/testimonial.html",
        "toggles": ["is_active"],
    },
    "sss": {
        "model": FAQ, "form": FAQForm, "title": "Sık Sorulan Sorular",
        "singular": "Soru", "template": "dashboard/lists/faq.html",
        "toggles": ["is_active"],
    },
    "markalar": {
        "model": Brand, "form": BrandForm, "title": "Markalar",
        "singular": "Marka", "template": "dashboard/lists/brand.html",
        "toggles": [],
    },
}


def _cfg(key):
    cfg = CRUD.get(key)
    if not cfg:
        raise Http404("Bölüm bulunamadı")
    return cfg


# ---------- Auth ----------

def login_view(request):
    if in_panel(request.user):
        return redirect("dashboard:home")
    error = None
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", "").strip(),
            password=request.POST.get("password", ""),
        )
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
        error = "Kullanıcı adı veya şifre hatalı ya da yetkiniz yok."
    return render(request, "dashboard/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("dashboard:login")


# ---------- Overview ----------

@staff_required
def home(request):
    from apps.stock import reports as stock_reports

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
        "stock": stock_reports.dashboard_kpis(request.user),
        "show_money": can_see_money(request.user),
        "recent_quotes": QuoteRequest.objects.all()[:6],
        "recent_services": ServiceRequest.objects.all()[:4],
    }
    return render(request, "dashboard/home.html", ctx)


# ---------- Generic CRUD ----------

@staff_required
def crud_list(request, key):
    cfg = _cfg(key)
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
    instance = get_object_or_404(cfg["model"], pk=pk) if pk else None
    if request.method == "POST":
        form = cfg["form"](request.POST, request.FILES, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, f"{cfg['singular']} kaydedildi.")
            return redirect("dashboard:crud_list", key=key)
    else:
        form = cfg["form"](instance=instance)
    return render(request, "dashboard/form.html", {
        "active": key, "form": form, "key": key,
        "title": cfg["title"], "singular": cfg["singular"],
        "is_edit": instance is not None,
    })


@staff_required
@require_POST
def crud_delete(request, key, pk):
    cfg = _cfg(key)
    obj = get_object_or_404(cfg["model"], pk=pk)
    obj.delete()
    if request.headers.get("HX-Request"):
        return HttpResponse("")  # satırı DOM'dan kaldır
    messages.success(request, f"{cfg['singular']} silindi.")
    return redirect("dashboard:crud_list", key=key)


@staff_required
@require_POST
def crud_toggle(request, key, pk, field):
    cfg = _cfg(key)
    if field not in cfg["toggles"]:
        raise Http404("Geçersiz alan")
    obj = get_object_or_404(cfg["model"], pk=pk)
    setattr(obj, field, not getattr(obj, field))
    obj.save(update_fields=[field])
    return render(request, "dashboard/partials/toggle.html", {
        "obj": obj, "key": key, "field": field, "value": getattr(obj, field),
    })


# ---------- Talepler (leads) ----------

@staff_required
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


@staff_required
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


@staff_required
@require_POST
def lead_delete(request, tip, pk):
    model = LEAD_MODELS.get(tip)
    if not model:
        raise Http404
    get_object_or_404(model, pk=pk).delete()
    return HttpResponse("")


# ---------- Site Ayarları ----------

@staff_required
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
