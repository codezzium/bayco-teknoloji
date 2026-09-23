"""Tarama akışları: hızlı arama, stok girişi ve sayım.

Dört akış da aynı bileşeni (templates/stock/partials/scanner.html) kullanır;
farkı yalnızca `mode` parametresidir.
"""

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import cart as cart_utils
from .. import services
from ..models import Accessory, Device
from ..utils import MAX_QTY
from .base import can_see_money, panel_required
from .pos import cart_context

COUNT_KEY = "stock_count"


def _scanned_code(request) -> str:
    return (request.POST.get("code") or request.POST.get("manual") or "").strip()


def _rendered(request, template, context, *, ok=None):
    """render() + HX-Trigger. django.shortcuts.render `headers` kabul etmez."""
    response = render(request, template, context)
    if ok is not None:
        response["HX-Trigger"] = (
            '{"bayco:scanned":{"ok":true}}' if ok else '{"bayco:scanned":{"ok":false}}'
        )
    return response


# ===========================================================================
# Hızlı arama
# ===========================================================================

@panel_required
def scan_page(request):
    return render(request, "stock/scan.html", {"active": "tara"})


@panel_required
@require_POST
def scan_resolve(request):
    """Okutulan kodu çözer ve moda göre yanıt döner.

    Tüm modlar POST'tur: IMEI yarı-kişisel veridir, tarayıcı geçmişine ve
    sunucu erişim kaydına düşmemelidir.

    BULUNAMADI durumunda 404 DEĞİL 200 döner — htmx 1.9 2xx dışındaki
    yanıtları swap etmez ve kullanıcı ekranda hiçbir şey olmadığını görür.
    """
    mode = request.POST.get("mode", "lookup")
    code = _scanned_code(request)
    obj = services.resolve_scan(code) if code else None

    if obj is None:
        return _rendered(request, "stock/partials/scan_result.html", {
            "code": code, "found": False, "mode": mode,
        }, ok=False)

    if mode == "sale":
        return _scan_into_cart(request, obj)
    if mode == "intake":
        return _scan_into_intake(request, obj)
    if mode == "count":
        return _scan_into_count(request, obj)

    # lookup: doğrudan detay sayfasına götür
    url = (reverse("stock:device_detail", kwargs={"pk": obj.pk})
           if isinstance(obj, Device)
           else reverse("stock:accessory_detail", kwargs={"pk": obj.pk}))
    return HttpResponse(status=204, headers={"HX-Redirect": url})


def _scan_into_cart(request, obj):
    cart = cart_utils.get_cart(request)
    cart, message = cart_utils.add_item(cart, obj)
    cart_utils.save_cart(request, cart)
    context = cart_context(request, cart)
    context["flash"] = message
    return _rendered(request, "stock/partials/cart.html", context, ok=True)


# ===========================================================================
# Stok girişi
# ===========================================================================

@panel_required
def intake(request):
    return render(request, "stock/intake.html", {
        "active": "giris",
        "recent": _recent_intake(request),
    })


def _recent_intake(request):
    ids = request.session.get("stock_intake_recent", [])
    accessories = {a.pk: a for a in Accessory.objects.filter(pk__in=ids)}
    return [accessories[i] for i in ids if i in accessories]


def _scan_into_intake(request, obj):
    """Okutulan aksesuarın stoğunu 1 artırır; cihazlar için detaya yönlendirir."""
    if isinstance(obj, Device):
        return render(request, "stock/partials/scan_result.html", {
            "code": obj.stock_code, "found": True, "mode": "intake",
            "device": obj,
            "message": "Bu bir cihaz kaydı. Cihazlar tek tek eklenir, "
                       "adet artırılmaz.",
        })

    services.receive_accessory_stock(obj, 1, user=request.user,
                                     note="Barkodla giriş")
    obj.refresh_from_db()
    recent = [obj.pk] + [i for i in request.session.get("stock_intake_recent", [])
                         if i != obj.pk]
    request.session["stock_intake_recent"] = recent[:20]
    request.session.modified = True
    return _rendered(request, "stock/partials/intake_result.html", {
        "recent": _recent_intake(request),
        "flash": f"{obj.name}: stok {obj.stock_qty} adet.",
    }, ok=True)


@panel_required
@require_POST
def intake_add(request):
    """Listedeki bir satıra elle adet ekler/çıkarır."""
    accessory = Accessory.objects.filter(pk=request.POST.get("accessory")).first()
    delta = int(request.POST.get("delta") or 0)
    if accessory and delta:
        try:
            if delta > 0:
                services.receive_accessory_stock(accessory, delta, user=request.user,
                                                 note="Elle giriş")
            else:
                services.write_off_accessory(accessory, -delta, user=request.user,
                                             note="Giriş düzeltmesi")
        except services.StockError as exc:
            messages.error(request, str(exc))
    return render(request, "stock/partials/intake_result.html",
                  {"recent": _recent_intake(request)})


# ===========================================================================
# Sayım
# ===========================================================================

@panel_required
def stocktake(request):
    return render(request, "stock/stocktake.html", {
        "active": "sayim",
        **_count_context(request),
    })


def _count_context(request):
    counted = request.session.get(COUNT_KEY, {})
    accessories = {a.pk: a for a in
                   Accessory.objects.filter(pk__in=[int(k) for k in counted])}
    rows = []
    for key, qty in counted.items():
        accessory = accessories.get(int(key))
        if not accessory:
            continue
        rows.append({
            "accessory": accessory,
            "counted": qty,
            "system": accessory.stock_qty,
            "diff": qty - accessory.stock_qty,
        })
    rows.sort(key=lambda r: abs(r["diff"]), reverse=True)
    return {"rows": rows, "total_counted": len(rows),
            "diff_count": sum(1 for r in rows if r["diff"])}


def _scan_into_count(request, obj):
    if isinstance(obj, Device):
        return render(request, "stock/partials/count_result.html", {
            **_count_context(request),
            "flash": "Sayım yalnızca aksesuarlar içindir; cihazlar seri "
                     "takiplidir ve durum üzerinden izlenir.",
        })
    counted = request.session.get(COUNT_KEY, {})
    key = str(obj.pk)
    counted[key] = counted.get(key, 0) + 1
    request.session[COUNT_KEY] = counted
    request.session.modified = True
    return _rendered(request, "stock/partials/count_result.html", {
        **_count_context(request),
        "flash": f"{obj.name}: {counted[key]} adet sayıldı.",
    }, ok=True)


@panel_required
@require_POST
def stocktake_mark(request):
    """Bir satırın sayılan adedini elle düzeltir."""
    counted = request.session.get(COUNT_KEY, {})
    key = request.POST.get("accessory") or ""
    try:
        quantity = int(request.POST.get("counted") or 0)
    except ValueError:
        quantity = 0
    if not key.isdecimal() or quantity > MAX_QTY:
        return render(request, "stock/partials/count_result.html", {
            **_count_context(request), "flash": "Geçersiz adet.",
        })
    if request.POST.get("remove"):
        counted.pop(key, None)
    else:
        counted[key] = max(quantity, 0)
    request.session[COUNT_KEY] = counted
    request.session.modified = True
    return render(request, "stock/partials/count_result.html", _count_context(request))


@panel_required
@require_POST
def stocktake_finish(request):
    """Sayımı stoğa uygular — fark kadar SAYIM hareketi yazılır."""
    context = _count_context(request)
    applied = 0
    for row in context["rows"]:
        movement = services.adjust_accessory_stock(
            row["accessory"], row["counted"], user=request.user,
            note="Sayım oturumu")
        if movement:
            applied += 1
    request.session[COUNT_KEY] = {}
    request.session.modified = True
    messages.success(
        request,
        f"{context['total_counted']} ürün sayıldı, {applied} üründe düzeltme yapıldı."
        if applied else f"{context['total_counted']} ürün sayıldı, fark yok.",
    )
    return redirect("stock:stocktake")


@panel_required
@require_POST
def stocktake_clear(request):
    request.session[COUNT_KEY] = {}
    request.session.modified = True
    return render(request, "stock/partials/count_result.html", _count_context(request))
