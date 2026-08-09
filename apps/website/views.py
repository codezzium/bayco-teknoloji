from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Brand, Product
from apps.leads.models import ContactMessage, QuoteRequest, ServiceRequest
from apps.leads.utils import (
    contact_message,
    quote_message,
    service_message,
    wa_link,
)
from apps.sitecore.models import FAQ, SiteSettings, Slider, Testimonial


def robots_txt(request):
    host = request.get_host()
    scheme = request.scheme
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /panel/",
        "Disallow: /yonetim/",
        # Filtreli listeler (/urunler/?marka=...) BİLEREK engellenmiyor.
        # Taraması engellenen sayfanın noindex etiketi Google tarafından hiç
        # okunamaz ve URL yine de dizine "açıklama yok" olarak düşebilir.
        # Taranmalarına izin verip kanonik + noindex ile temiz şekilde
        # eleniyorlar; bu ölçekte tarama bütçesi zaten sorun değil.
        # Form gönderim uçları: içerik döndürmez, dizine girmemeli.
        "Disallow: /teklif/gonder/",
        "Disallow: /servis/gonder/",
        "Disallow: /iletisim/gonder/",
        "",
        "User-agent: Googlebot-Image",
        "Allow: /media/",
        "",
        f"Sitemap: {scheme}://{host}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def _crumbs(request, *pairs):
    """BreadcrumbList JSON-LD için (ad, yol) çiftlerini mutlak URL'ye çevirir.

    Google gezinti izini yalnızca mutlak adreslerle eşler; şablonda
    request.scheme//host birleştirmesi her sayfada tekrarlanmasın diye burada.
    """
    origin = f"{request.scheme}://{request.get_host()}"
    return [{"name": name, "url": f"{origin}{path}"} for name, path in pairs]


def home(request):
    ctx = {
        "sliders": Slider.objects.filter(is_active=True),
        "featured": Product.objects.filter(is_active=True, is_featured=True).select_related("brand")[:8],
        "latest_second_hand": Product.objects.filter(
            is_active=True, condition=Product.Condition.IKINCI_EL
        ).select_related("brand")[:4],
        "testimonials": Testimonial.objects.filter(is_active=True),
        "faqs": FAQ.objects.filter(is_active=True),
        "brands": Brand.objects.filter(is_public=True),
    }
    return render(request, "website/home.html", ctx)


# ---------- Ürünler ----------

def _filtered_products(request):
    qs = Product.objects.filter(is_active=True).select_related("brand")
    durum = request.GET.get("durum", "")
    marka = request.GET.get("marka", "")
    q = request.GET.get("q", "").strip()
    if durum in (Product.Condition.SIFIR, Product.Condition.IKINCI_EL):
        qs = qs.filter(condition=durum)
    if marka:
        qs = qs.filter(brand__slug=marka)
    if q:
        qs = qs.filter(name__icontains=q)
    return qs, durum, marka, q


def products(request):
    qs, durum, marka, q = _filtered_products(request)

    # Filtreli görünümler kanonik olarak /urunler/'e işaret ediyor; ayrıca
    # noindex veriyoruz ki Google "iPhone + ikinci el + arama" gibi yüzlerce
    # neredeyse-aynı sayfayı dizine alıp asıl listeyi zayıflatmasın.
    # follow açık kalır: bu sayfalardaki ürün linkleri yine taranır.
    is_filtered = bool(durum or marka or q)

    label = {"sifir": "Sıfır", "ikinci_el": "İkinci El"}.get(durum, "")
    brand_obj = Brand.objects.filter(slug=marka).first() if marka else None
    parts = [p for p in (brand_obj.name if brand_obj else "", label) if p]
    if parts:
        title = f"Eskişehir {' '.join(parts)} Telefon Fiyatları | Bayço Teknoloji"
        description = (
            f"Eskişehir'de {' '.join(parts).lower()} telefon modelleri ve güncel fiyatları. "
            "Bayço Teknoloji'de garantili, faturalı cihazlar; takas ve WhatsApp'tan hızlı teklif."
        )
    else:
        title = "Eskişehir Sıfır & İkinci El Telefon Fiyatları | Bayço Teknoloji"
        description = (
            "Eskişehir Bayço Teknoloji ürünleri: sıfır ve garantili ikinci el iPhone, Samsung, "
            "Xiaomi telefonlar. Eskişehir'de uygun fiyat, taksit ve WhatsApp'tan hızlı teklif."
        )

    ctx = {
        "products": qs,
        "brands": Brand.objects.filter(is_public=True),
        "durum": durum,
        "marka": marka,
        "q": q,
        "seo_title": title,
        "seo_description": description,
        "seo_noindex": is_filtered,
        "breadcrumbs": _crumbs(
            request,
            ("Ana Sayfa", reverse("website:home")),
            ("Ürünler", reverse("website:products")),
        ),
    }
    return render(request, "website/products.html", ctx)


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("brand").prefetch_related("images"),
        slug=slug, is_active=True,
    )
    site = SiteSettings.load()
    ask_text = (
        f"Merhaba, aşağıdaki ürün hakkında bilgi almak istiyorum:\n\n"
        f"📱 {product.name}\n"
        f"{'Marka: ' + product.brand.name if product.brand else ''}\n"
        f"Durum: {product.get_condition_display()}\n"
        f"Fiyat: {product.price_display}"
    )
    related = Product.objects.filter(
        is_active=True, brand=product.brand
    ).exclude(pk=product.pk).select_related("brand")[:4]

    bits = " ".join(p for p in (product.name, product.storage,
                                product.get_condition_display()) if p)
    ctx = {
        "product": product,
        "wa_ask": wa_link(site.whatsapp_number, ask_text),
        "related": related,
        "seo_title": f"{bits} Fiyatı | Eskişehir Bayço Teknoloji"[:70],
        "seo_description": (
            f"{bits} – Eskişehir Bayço Teknoloji'de {product.price_display}. "
            f"{product.short_desc} Garantili, faturalı; WhatsApp'tan hemen teklif alın."
        ).strip(),
        "seo_keywords": (
            f"{product.name}, Eskişehir {product.name} fiyatı, "
            f"{product.name} {product.get_condition_display().lower()}, Eskişehir telefon"
        ),
        # Boş ImageField'de .url ValueError fırlatır; şablonda değil burada koru.
        "og_image": product.cover.url if product.cover else "",
        # Google, priceValidUntil geçmişte kalırsa teklifi "süresi dolmuş" sayıp
        # zengin sonucu düşürür. Her istekte bugünden 1 yıl ileri veriyoruz.
        "price_valid_until": (timezone.localdate() + timedelta(days=365)).isoformat(),
        "breadcrumbs": _crumbs(
            request,
            ("Ana Sayfa", reverse("website:home")),
            ("Ürünler", reverse("website:products")),
            (product.name, product.get_absolute_url()),
        ),
    }
    return render(request, "website/product_detail.html", ctx)


# ---------- Teklif Al ----------

def quote(request):
    prefill_product = None
    urun_id = request.GET.get("urun")
    if urun_id:
        prefill_product = Product.objects.filter(pk=urun_id, is_active=True).first()
    ctx = {
        "brands": Brand.objects.filter(is_public=True),
        "prefill_product": prefill_product,
        "default_kind": request.GET.get("mod", "sat"),
        "breadcrumbs": _crumbs(
            request,
            ("Ana Sayfa", reverse("website:home")),
            ("Teklif Al", reverse("website:quote")),
        ),
    }
    return render(request, "website/quote.html", ctx)


def quote_submit(request):
    if request.method != "POST":
        return redirect("website:quote")
    kind = request.POST.get("kind", "sat")
    if kind not in ("sat", "al"):
        kind = "sat"
    product = None
    pid = request.POST.get("product_id")
    if pid:
        product = Product.objects.filter(pk=pid).first()
    qr = QuoteRequest.objects.create(
        kind=kind,
        name=request.POST.get("name", "").strip(),
        phone=request.POST.get("phone", "").strip(),
        brand=request.POST.get("brand", "").strip(),
        model=request.POST.get("model", "").strip(),
        year=request.POST.get("year", "").strip(),
        storage=request.POST.get("storage", "").strip(),
        condition=request.POST.get("condition", "").strip(),
        note=request.POST.get("note", "").strip(),
        product=product,
    )
    site = SiteSettings.load()
    link = wa_link(site.whatsapp_number, quote_message(qr))
    return render(request, "website/partials/lead_success.html", {
        "wa": link,
        "title": "Teklif talebiniz oluşturuldu!",
        "desc": "WhatsApp otomatik açılıyor. Açılmazsa aşağıdaki butona dokunun.",
    })


# ---------- Servis ----------

def service(request):
    return render(request, "website/service.html", {
        "breadcrumbs": _crumbs(
            request,
            ("Ana Sayfa", reverse("website:home")),
            ("Teknik Servis", reverse("website:service")),
        ),
    })


def service_submit(request):
    if request.method != "POST":
        return redirect("website:service")
    sr = ServiceRequest.objects.create(
        name=request.POST.get("name", "").strip(),
        phone=request.POST.get("phone", "").strip(),
        device=request.POST.get("device", "").strip(),
        issue=request.POST.get("issue", "").strip(),
        note=request.POST.get("note", "").strip(),
    )
    site = SiteSettings.load()
    link = wa_link(site.whatsapp_number, service_message(sr))
    return render(request, "website/partials/lead_success.html", {
        "wa": link,
        "title": "Servis talebiniz alındı!",
        "desc": "WhatsApp otomatik açılıyor. Açılmazsa aşağıdaki butona dokunun.",
    })


# ---------- İletişim ----------

def contact(request):
    return render(request, "website/contact.html", {
        "breadcrumbs": _crumbs(
            request,
            ("Ana Sayfa", reverse("website:home")),
            ("İletişim", reverse("website:contact")),
        ),
    })


def contact_submit(request):
    if request.method != "POST":
        return redirect("website:contact")
    cm = ContactMessage.objects.create(
        name=request.POST.get("name", "").strip(),
        phone=request.POST.get("phone", "").strip(),
        email=request.POST.get("email", "").strip(),
        message=request.POST.get("message", "").strip(),
    )
    site = SiteSettings.load()
    link = wa_link(site.whatsapp_number, contact_message(cm))
    return render(request, "website/partials/lead_success.html", {
        "wa": link,
        "title": "Mesajınız alındı!",
        "desc": "Dilerseniz WhatsApp üzerinden de hızlıca ulaşabilirsiniz.",
    })
