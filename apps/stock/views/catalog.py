"""Cihaz ve aksesuar listeleri, detayları ve formları."""

from django.contrib import messages
from django.db import transaction
from django.db.models import F, ProtectedError, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.catalog.models import Brand

from .. import services
from ..forms import (
    AccessoryCategoryForm,
    AccessoryForm,
    DeviceForm,
    DeviceModelForm,
    StockIntakeForm,
    StocktakeForm,
)
from ..labels import LABEL_FORMATS
from ..models import Accessory, AccessoryCategory, Device, DeviceModel
from ..utils import trfold
from .base import (
    can_see_money,
    paginate,
    panel_required,
    pick_template,
    preselected,
    querystring,
    safe_next,
    with_param,
)

DEVICE_ORDERING = {
    "-updated_at": "Son İşlem",
    "-created_at": "Son Eklenen",
    "purchase_date": "Alış Tarihi (eski→yeni)",
    "-purchase_date": "Alış Tarihi (yeni→eski)",
    "device_model__name": "Model",
}
DEFAULT_ORDERING = "-updated_at"


# ===========================================================================
# Cihazlar
# ===========================================================================

@panel_required
def device_list(request):
    status = request.GET.get("durum", "")
    brand_slug = request.GET.get("marka", "")
    query = request.GET.get("q", "").strip()
    ordering = request.GET.get("sirala", DEFAULT_ORDERING)

    devices = Device.objects.select_related("device_model__brand", "sold_to")
    if status in Device.Status.values:
        devices = devices.filter(status=status)
    if brand_slug:
        devices = devices.filter(device_model__brand__slug=brand_slug)
    if query:
        # search_blob Türkçe katlanmış ASCII tutar; sorgu da aynı tablodan
        # geçer. __icontains kullanılsaydı SQLite'ın ASCII-only upper()'ı
        # yüzünden "sarj" -> "Şarj" eşleşmezdi.
        devices = devices.filter(search_blob__contains=trfold(query))
    if ordering not in DEVICE_ORDERING:
        ordering = DEFAULT_ORDERING
    devices = devices.order_by(ordering, "-id")

    if not can_see_money(request.user):
        # Maliyet veritabanından hiç çıkmasın: htmx parçasından da sızamaz
        devices = devices.defer("purchase_price", "sold_price")

    page = paginate(devices, request)
    context = {
        "active": "cihazlar", "title": "Cihazlar", "singular": "Cihaz",
        "page": page, "total": page.paginator.count,
        "q": query, "durum": status, "marka": brand_slug, "sirala": ordering,
        "qs": querystring(request),
        "status_choices": Device.Status.choices,
        "orderings": DEVICE_ORDERING,
        "brands": Brand.objects.all(),
        "formats": LABEL_FORMATS,
        "create_url": reverse("stock:device_create"),
    }
    return render(request, pick_template(request, "stock/partials/device_rows.html",
                                         "stock/device_list.html"), context)


@panel_required
def device_detail(request, pk):
    device = get_object_or_404(
        Device.objects.select_related("device_model__brand", "supplier", "sold_to",
                                      "published_product"),
        pk=pk,
    )
    return render(request, "stock/device_detail.html", {
        "active": "cihazlar",
        "device": device,
        "logs": device.status_logs.select_related("created_by")[:20],
        "expenses": device.expenses.all() if can_see_money(request.user) else [],
        "sale_items": device.sale_items.select_related("sale__customer"),
        "formats": LABEL_FORMATS,
        # Satıldı/İade elle atanamaz (fiş, stok hareketi ve tahsilat oluşmaz),
        # bu yüzden seçeneklerden çıkarılır.
        "next_statuses": [
            (value, Device.Status(value).label)
            for value in services.ALLOWED_TRANSITIONS.get(device.status, set())
            if value not in (Device.Status.SATILDI, Device.Status.IADE)
        ],
    })


@panel_required
def device_by_code(request, stock_code):
    device = get_object_or_404(Device, stock_code__iexact=stock_code)
    return redirect("stock:device_detail", pk=device.pk)


@panel_required
def device_form(request, pk=None):
    instance = get_object_or_404(Device, pk=pk) if pk else None
    # Alan altındaki "yeni model ekle" kısayolu buraya geri döner.
    back = request.get_full_path()
    if request.method == "POST":
        form = DeviceForm(request.POST, instance=instance, user=request.user,
                          back_url=back)
        if form.is_valid():
            device = form.save(commit=False)
            if instance is None:
                device.created_by = request.user
            try:
                device.full_clean(exclude=["stock_code", "warranty_end",
                                           "search_blob", "created_by"])
            except Exception as exc:  # ValidationError -> forma taşı
                form.add_error(None, exc)
            else:
                device.save()
                messages.success(
                    request,
                    f"{device.stock_code} kaydedildi." if instance is None
                    else f"{device.stock_code} güncellendi.",
                )
                return redirect("stock:device_detail", pk=device.pk)
    else:
        initial = {}
        scanned = request.GET.get("imei", "").strip()
        if scanned and instance is None:
            initial["imei1"] = "".join(ch for ch in scanned if ch.isdigit())
        if instance is None:
            # "Yeni model ekle"den dönüş: az önce açılan model seçili gelir.
            initial.update(preselected(request, "device_model"))
        form = DeviceForm(instance=instance, user=request.user, initial=initial,
                          back_url=back)

    return render(request, "stock/form.html", {
        "active": "cihazlar", "form": form, "title": "Cihazlar",
        "singular": "Cihaz", "is_edit": instance is not None,
        "back_url": (reverse("stock:device_detail", kwargs={"pk": instance.pk})
                     if instance else reverse("stock:device_list")),
    })


@panel_required
@require_POST
def device_status(request, pk):
    device = get_object_or_404(Device, pk=pk)
    try:
        services.set_device_status(device, request.POST.get("status", ""),
                                   user=request.user,
                                   note=request.POST.get("note", ""))
        messages.success(request, f"{device.stock_code}: {device.get_status_display()}")
    except services.StockError as exc:
        messages.error(request, str(exc))
    return redirect("stock:device_detail", pk=device.pk)


@panel_required
@require_POST
def device_publish(request, pk):
    device = get_object_or_404(Device, pk=pk)
    try:
        if device.published_product and device.published_product.is_active:
            services.unpublish_device(device)
            messages.success(request, "İlan sitede pasife alındı.")
        else:
            product = services.publish_device_to_site(device, user=request.user)
            messages.success(
                request,
                f"Cihaz sitede yayınlandı: {product.name} — {product.price_display}. "
                "(Site üzerinden satış yapılmaz, ilan WhatsApp'a yönlendirir.)",
            )
    except services.StockError as exc:
        messages.error(request, str(exc))
    return redirect("stock:device_detail", pk=device.pk)


@panel_required
@require_POST
def device_delete(request, pk):
    device = get_object_or_404(Device, pk=pk)
    if device.sale_items.exists():
        messages.error(request, "Satışı olan cihaz silinemez. Durumunu değiştirin.")
        return redirect("stock:device_detail", pk=pk)
    code = device.stock_code
    try:
        with transaction.atomic():
            device.status_logs.all().delete()
            device.delete()
    except ProtectedError:
        messages.error(request, "Bu cihaza bağlı gider veya takas kaydı var; silinemez. "
                                "Durumunu değiştirin.")
        return redirect("stock:device_detail", pk=pk)
    messages.success(request, f"{code} silindi.")
    if request.headers.get("HX-Request"):
        return HttpResponse("")
    return redirect("stock:device_list")


# ===========================================================================
# Aksesuarlar
# ===========================================================================

@panel_required
def accessory_list(request):
    query = request.GET.get("q", "").strip()
    category = request.GET.get("kategori", "")
    only = request.GET.get("filtre", "")

    accessories = Accessory.objects.select_related("brand", "category")
    if query:
        accessories = accessories.filter(search_blob__contains=trfold(query))
    if category:
        accessories = accessories.filter(category_id=category)
    if only == "kritik":
        accessories = accessories.filter(is_active=True,
                                         stock_qty__lte=F("min_stock_level"))
    elif only == "eksi":
        accessories = accessories.filter(stock_qty__lt=0)
    elif only == "pasif":
        accessories = accessories.filter(is_active=False)
    else:
        accessories = accessories.filter(is_active=True)

    if not can_see_money(request.user):
        accessories = accessories.defer("cost")

    page = paginate(accessories, request)
    context = {
        "active": "aksesuarlar", "title": "Aksesuarlar", "singular": "Aksesuar",
        "page": page, "total": page.paginator.count,
        "q": query, "kategori": category, "filtre": only,
        "qs": querystring(request),
        "categories": AccessoryCategory.objects.all(),
        "formats": LABEL_FORMATS,
        "create_url": reverse("stock:accessory_create"),
    }
    return render(request, pick_template(request, "stock/partials/accessory_rows.html",
                                         "stock/accessory_list.html"), context)


@panel_required
def accessory_detail(request, pk):
    accessory = get_object_or_404(
        Accessory.objects.select_related("brand", "category"), pk=pk)
    return render(request, "stock/accessory_detail.html", {
        "active": "aksesuarlar",
        "accessory": accessory,
        "movements": accessory.movements.select_related("created_by")[:30],
        "intake_form": StockIntakeForm(user=request.user),
        "count_form": StocktakeForm(initial={"counted_qty": accessory.stock_qty}),
        "formats": LABEL_FORMATS,
    })


@panel_required
def accessory_form(request, pk=None):
    instance = get_object_or_404(Accessory, pk=pk) if pk else None
    back = request.get_full_path()
    if request.method == "POST":
        form = AccessoryForm(request.POST, instance=instance, user=request.user,
                             back_url=back)
        if form.is_valid():
            accessory = form.save()
            opening = form.cleaned_data.get("opening_qty") or 0
            if instance is None and opening > 0:
                services.receive_accessory_stock(
                    accessory, opening, user=request.user,
                    unit_cost=accessory.cost or None, opening=True,
                    note="Kart açılışı",
                )
            messages.success(request, f"{accessory} kaydedildi.")
            return redirect("stock:accessory_detail", pk=accessory.pk)
    else:
        initial = {}
        scanned = request.GET.get("barkod", "").strip()
        if scanned and instance is None:
            initial["barcode"] = "".join(ch for ch in scanned if ch.isdigit())
        if instance is None:
            initial.update(preselected(request, "category", "brand"))
        form = AccessoryForm(instance=instance, user=request.user, initial=initial,
                             back_url=back)

    return render(request, "stock/form.html", {
        "active": "aksesuarlar", "form": form, "title": "Aksesuarlar",
        "singular": "Aksesuar", "is_edit": instance is not None,
        "back_url": (reverse("stock:accessory_detail", kwargs={"pk": instance.pk})
                     if instance else reverse("stock:accessory_list")),
    })


@panel_required
@require_POST
def accessory_adjust(request, pk):
    """Tek aksesuar için mal girişi veya sayım düzeltmesi."""
    accessory = get_object_or_404(Accessory, pk=pk)
    mode = request.POST.get("mode", "giris")
    try:
        if mode == "sayim":
            form = StocktakeForm(request.POST)
            if not form.is_valid():
                raise services.StockError("Sayılan adet geçersiz.")
            movement = services.adjust_accessory_stock(
                accessory, form.cleaned_data["counted_qty"], user=request.user,
                note=form.cleaned_data.get("note", ""))
            messages.success(
                request,
                "Sayım farkı yok." if movement is None
                else f"Sayım düzeltmesi: {movement.quantity:+d} adet.")
        elif mode == "fire":
            qty = int(request.POST.get("quantity") or 0)
            services.write_off_accessory(accessory, qty, user=request.user,
                                         note=request.POST.get("note", ""))
            messages.success(request, f"{qty} adet fire kaydedildi.")
        else:
            form = StockIntakeForm(request.POST, user=request.user)
            if not form.is_valid():
                raise services.StockError("Giriş bilgileri geçersiz.")
            services.receive_accessory_stock(
                accessory, form.cleaned_data["quantity"], user=request.user,
                unit_cost=form.cleaned_data.get("unit_cost"),
                note=form.cleaned_data.get("note", ""))
            messages.success(request,
                             f"{form.cleaned_data['quantity']} adet giriş yapıldı.")
    except (services.StockError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("stock:accessory_detail", pk=accessory.pk)


# ===========================================================================
# Model kataloğu & kategoriler (küçük destek listeleri)
# ===========================================================================

#: `param`, `?next=` ile çağıran formun bu kaydı hangi query parametresiyle
#: seçili göstereceğidir (cihaz formu ?device_model=, aksesuar formu ?category=).
SIMPLE = {
    "modeller": {
        "model": DeviceModel, "form": DeviceModelForm, "title": "Cihaz Modelleri",
        "singular": "Model", "param": "device_model",
        "select": ("brand",), "order": ("brand__name", "name"),
    },
    "kategoriler": {
        "model": AccessoryCategory, "form": AccessoryCategoryForm,
        "title": "Aksesuar Kategorileri", "singular": "Kategori",
        "param": "category", "select": (), "order": ("order", "name"),
    },
}


def _simple_cfg(key):
    cfg = SIMPLE.get(key)
    if not cfg:
        raise Http404("Bölüm bulunamadı")
    return cfg


@panel_required
def simple_list(request, key):
    cfg = _simple_cfg(key)
    items = cfg["model"].objects.all()
    if cfg["select"]:
        items = items.select_related(*cfg["select"])
    items = items.order_by(*cfg["order"])
    return render(request, "stock/simple_list.html", {
        # Yan menüde kendi maddesi vardır: "cihazlar"ı işaretlemek, tanım
        # sayfasındayken cihaz listesindeymiş gibi görünmeye yol açardı.
        "active": key, "items": items, "key": key,
        "title": cfg["title"], "singular": cfg["singular"],
        "total": items.count(),
        "create_url": reverse("stock:simple_create", kwargs={"key": key}),
    })


@panel_required
def simple_form(request, key, pk=None):
    cfg = _simple_cfg(key)
    instance = get_object_or_404(cfg["model"], pk=pk) if pk else None
    next_url = safe_next(request)
    # Model formundaki "yeni marka ekle" kısayolu buraya döner; adres kendi
    # `?next=`ini taşıdığı için cihaz -> model -> marka zinciri korunur.
    back = request.get_full_path()
    if request.method == "POST":
        form = cfg["form"](request.POST, instance=instance, user=request.user,
                           back_url=back)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"{cfg['singular']} kaydedildi.")
            if next_url:
                return redirect(with_param(next_url, cfg["param"], obj.pk))
            return redirect("stock:simple_list", key=key)
    else:
        # "Yeni marka ekle"den dönüş (yalnızca cihaz modelinde üst kayıt var).
        initial = preselected(request, "brand") if instance is None else {}
        form = cfg["form"](instance=instance, user=request.user, back_url=back,
                           initial=initial)
    return render(request, "stock/form.html", {
        "active": key, "form": form, "title": cfg["title"],
        "singular": cfg["singular"], "is_edit": instance is not None,
        "next_url": next_url,
        "back_url": next_url or reverse("stock:simple_list", kwargs={"key": key}),
    })


@panel_required
@require_POST
def simple_delete(request, key, pk):
    cfg = _simple_cfg(key)
    obj = get_object_or_404(cfg["model"], pk=pk)
    try:
        obj.delete()
        messages.success(request, f"{cfg['singular']} silindi.")
    except Exception:
        messages.error(request,
                       "Bu kayıt kullanımda olduğu için silinemez (PROTECT).")
        if request.headers.get("HX-Request"):
            return HttpResponse(status=204, headers={"HX-Refresh": "true"})
    if request.headers.get("HX-Request"):
        return HttpResponse("")
    return redirect("stock:simple_list", key=key)
