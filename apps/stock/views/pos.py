"""Kasa (POS), satış listesi, fiş ve tahsilat ekranları."""

from django.contrib import messages
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .. import cart as cart_utils
from .. import services
from ..forms import PaymentForm
from ..models import Contact, Device, DeviceModel, Payment, Sale, SaleItem
from ..utils import parse_money, trfold
from .base import (
    can_see_money,
    paginate,
    panel_required,
    patron_required,
    pick_template,
    querystring,
)


def cart_context(request, cart=None) -> dict:
    cart = cart if cart is not None else cart_utils.get_cart(request)
    show_money = can_see_money(request.user)
    summary = cart_utils.summarize(cart, with_money=show_money)
    customer = None
    if cart.get("customer_id"):
        customer = Contact.objects.filter(pk=cart["customer_id"]).first()
    return {
        "cart": summary,
        "customer": customer,
        "note": cart.get("note", ""),
        "show_money": show_money,
        "payment_methods": Payment.Method.choices,
        # Takas formu sepetin içinde render edilir; sepet her mutasyonda
        # yeniden çizildiği için model listesi de bu bağlamda olmalıdır.
        "device_models": (DeviceModel.objects.filter(is_active=True)
                          .select_related("brand")
                          if summary["has_device"] or summary["trade_ins"] else []),
    }


# ===========================================================================
# Kasa
# ===========================================================================

@panel_required
def pos(request):
    return render(request, "stock/pos.html", {
        "active": "satis",
        **cart_context(request),
    })


def _render_cart(request, cart, flash=""):
    cart_utils.save_cart(request, cart)
    context = cart_context(request, cart)
    context["flash"] = flash
    return render(request, "stock/partials/cart.html", context)


@panel_required
@require_POST
def cart_add(request):
    """Elle ürün ekleme (arama sonucundan). Barkodla ekleme scan_resolve'da."""
    cart = cart_utils.get_cart(request)
    kind = request.POST.get("kind")
    try:
        quantity = max(int(request.POST.get("qty") or 1), 1)
    except ValueError:
        quantity = 1

    if kind == "cihaz":
        obj = Device.objects.filter(pk=request.POST.get("id")).first()
    else:
        from ..models import Accessory
        obj = Accessory.objects.filter(pk=request.POST.get("id")).first()

    if obj is None:
        return _render_cart(request, cart, "Ürün bulunamadı.")
    cart, message = cart_utils.add_item(cart, obj, quantity=quantity)
    return _render_cart(request, cart, message)


@panel_required
@require_POST
def sell_device(request, pk):
    device = get_object_or_404(
        Device.objects.select_related("device_model__brand"), pk=pk)
    if not device.is_available:
        messages.error(
            request,
            f"{device.stock_code} satışa uygun değil ({device.get_status_display()}).")
        return redirect("stock:device_detail", pk=pk)

    cart = cart_utils.get_cart(request)
    cart, message = cart_utils.add_item(cart, device)
    cart_utils.save_cart(request, cart)
    messages.success(request, message)
    return redirect("stock:pos")


@panel_required
@require_POST
def cart_remove(request, lid):
    cart = cart_utils.remove_line(cart_utils.get_cart(request), lid)
    return _render_cart(request, cart)


@panel_required
@require_POST
def cart_qty(request, lid):
    try:
        quantity = int(request.POST.get("qty") or 1)
    except ValueError:
        quantity = 1
    cart = cart_utils.set_quantity(cart_utils.get_cart(request), lid, quantity)
    return _render_cart(request, cart)


@panel_required
@require_POST
def cart_price(request, lid):
    cart = cart_utils.get_cart(request)
    price = parse_money(request.POST.get("price"))
    if price is None:
        return _render_cart(request, cart, "Geçersiz fiyat.")
    cart = cart_utils.set_price(cart, lid, price)
    if request.POST.get("discount") is not None:
        discount = parse_money(request.POST.get("discount"))
        if discount is not None:
            cart = cart_utils.set_discount(cart, lid, discount)
    return _render_cart(request, cart)


@panel_required
@require_POST
def cart_customer(request):
    cart = cart_utils.get_cart(request)
    contact_id = request.POST.get("customer") or None
    cart["customer_id"] = int(contact_id) if contact_id else None
    cart["note"] = request.POST.get("note", cart.get("note", ""))
    return _render_cart(request, cart)


@panel_required
@require_POST
def cart_clear(request):
    return _render_cart(request, cart_utils.clear_cart(request), "Sepet temizlendi.")


@panel_required
@require_POST
def cart_trade_in(request):
    """Takas cihazını sepete ekler; asıl Device kaydı satış anında yaratılır."""
    cart = cart_utils.get_cart(request)
    if request.POST.get("remove"):
        cart = cart_utils.remove_trade_in(cart, request.POST["remove"])
        return _render_cart(request, cart)

    model = DeviceModel.objects.filter(pk=request.POST.get("device_model")).first()
    if model is None:
        return _render_cart(request, cart, "Takas için model seçilmelidir.")
    amount = parse_money(request.POST.get("amount"))
    if amount is None:
        return _render_cart(request, cart, "Geçersiz takas bedeli.")
    if amount <= 0:
        return _render_cart(request, cart, "Takas bedeli pozitif olmalıdır.")

    cart = cart_utils.add_trade_in(cart, {
        "device_model_id": model.pk,
        "label": str(model),
        "amount": amount,
        "imei1": request.POST.get("imei1", ""),
        "color": request.POST.get("color", ""),
        "storage": request.POST.get("storage", ""),
        "note": request.POST.get("note", ""),
    })
    return _render_cart(request, cart, f"Takas eklendi: {model} — {amount} ₺")


@panel_required
@require_POST
def checkout(request):
    cart = cart_utils.get_cart(request)
    payable = cart_utils.summarize(cart, with_money=False)["payable"]

    amount_raw = (request.POST.get("paid_amount") or "").strip()
    if amount_raw:
        paid = parse_money(amount_raw)
        if paid is None:
            return _render_cart(request, cart, "Geçersiz tahsilat tutarı.")
    else:
        paid = payable

    method = request.POST.get("payment_method", "nakit")
    if method not in Payment.Method.values:
        method = Payment.Method.NAKIT
    payments = []
    if paid > 0:
        payments.append({"amount": paid, "method": method})

    due_raw = (request.POST.get("due_date") or "").strip()
    try:
        due_date = parse_date(due_raw) if due_raw else None
    except ValueError:
        due_date = None
    if due_raw and due_date is None:
        return _render_cart(request, cart, "Geçersiz vade tarihi.")
    try:
        sale = services.create_sale_from_cart(
            cart, user=request.user, payments=payments, due_date=due_date,
            note=cart.get("note", ""),
            confirm_prices=bool(request.POST.get("confirm_prices")),
        )
    except services.PriceChanged as exc:
        context = cart_context(request, cart)
        context["price_changes"] = exc.changes
        return render(request, "stock/partials/cart.html", context)
    except services.StockError as exc:
        return _render_cart(request, cart, str(exc))

    cart_utils.clear_cart(request)
    messages.success(request, f"{sale.receipt_no} oluşturuldu.")
    return render(request, "stock/partials/cart.html", {
        **cart_context(request),
        "completed_sale": sale,
    })


# ===========================================================================
# Satışlar
# ===========================================================================

@panel_required
def sale_list(request):
    query = request.GET.get("q", "").strip()
    only = request.GET.get("filtre", "")

    sales = Sale.objects.select_related("customer", "cashier").prefetch_related("items")
    if only == "acik":
        sales = sales.filter(status=Sale.Status.TAMAMLANDI,
                             payable_total__gt=F("paid_total"))
    elif only == "vadesi":
        sales = sales.filter(status=Sale.Status.TAMAMLANDI,
                             payable_total__gt=F("paid_total"),
                             due_date__lt=timezone.localdate())
    elif only == "iptal":
        sales = sales.filter(status=Sale.Status.IPTAL)

    if query:
        folded = trfold(query)
        sales = sales.filter(
            Q(receipt_no__icontains=query)
            | Q(customer__search_blob__contains=folded)
            | Q(items__item_code__icontains=query)
            | Q(items__item_imei__icontains=query)
        ).distinct()

    page = paginate(sales, request)
    return render(request, pick_template(request, "stock/partials/sale_rows.html",
                                         "stock/sale_list.html"), {
        "active": "satislar", "title": "Satışlar", "page": page,
        "total": page.paginator.count, "q": query, "filtre": only,
        "qs": querystring(request),
        "filter_options": [
            ("", "Tümü"), ("acik", "Açık bakiye"),
            ("vadesi", "Vadesi geçen"), ("iptal", "İptal"),
        ],
        "show_money": can_see_money(request.user),
    })


@panel_required
def sale_detail(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related("customer", "cashier", "voided_by"), pk=pk)
    return render(request, "stock/sale_detail.html", {
        "active": "satislar",
        "sale": sale,
        "items": sale.items.select_related("device", "accessory"),
        "trade_ins": sale.trade_ins.select_related("device__device_model__brand"),
        "payments": sale.payments.select_related("created_by"),
        "payment_form": PaymentForm(user=request.user),
        "show_money": can_see_money(request.user),
    })


@panel_required
def receipt(request, pk):
    sale = get_object_or_404(Sale.objects.select_related("customer"), pk=pk)
    return render(request, "stock/receipt.html", {
        "sale": sale,
        "items": sale.items.filter(returned_at__isnull=True),
        "trade_ins": sale.trade_ins.all(),
        "payments": sale.payments.all(),
        "auto": request.GET.get("auto") == "1",
    })


@panel_required
@require_POST
def sale_payment(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    form = PaymentForm(request.POST, user=request.user)
    if form.is_valid():
        try:
            services.record_payment(
                sale, form.cleaned_data["amount"],
                method=form.cleaned_data["method"], user=request.user,
                kind=form.cleaned_data["kind"],
                paid_at=form.cleaned_data.get("paid_at"),
                note=form.cleaned_data.get("note", ""))
            messages.success(request, "Ödeme kaydedildi.")
        except services.StockError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Ödeme bilgileri geçersiz.")
    return redirect("stock:sale_detail", pk=pk)


@panel_required
@require_POST
def sale_item_return(request, pk, item_id):
    sale = get_object_or_404(Sale, pk=pk)
    item = get_object_or_404(SaleItem, pk=item_id, sale=sale)
    try:
        services.return_sale_item(
            item, user=request.user, reason=request.POST.get("reason", ""),
            refund=bool(request.POST.get("refund")))
        messages.success(request, f"{item.item_name} iade edildi.")
    except services.StockError as exc:
        messages.error(request, str(exc))
    return redirect("stock:sale_detail", pk=pk)


@patron_required
@require_POST
def sale_void(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    try:
        services.void_sale(sale, user=request.user,
                           reason=request.POST.get("reason", "") or "Elle iptal")
        messages.success(request, f"{sale.receipt_no} iptal edildi.")
    except services.StockError as exc:
        messages.error(request, str(exc))
    return redirect("stock:sale_detail", pk=pk)


@panel_required
def product_search(request):
    """Kasada barkodsuz ürünü adıyla bulmak için canlı arama."""
    from ..models import Accessory

    query = request.GET.get("q", "").strip()
    devices, accessories = [], []
    if len(query) >= 2:
        folded = trfold(query)
        devices = (Device.objects
                   .filter(search_blob__contains=folded,
                           status__in=[Device.Status.STOKTA, Device.Status.REZERVE])
                   .select_related("device_model__brand")[:8])
        accessories = (Accessory.objects
                       .filter(search_blob__contains=folded, is_active=True)[:8])
    return render(request, "stock/partials/product_search.html", {
        "q": query, "devices": devices, "accessories": accessories,
    })


@panel_required
def contact_search(request):
    query = request.GET.get("q", "").strip()
    contacts = []
    if len(query) >= 2:
        contacts = Contact.objects.filter(
            search_blob__contains=trfold(query), is_customer=True)[:8]
    return render(request, "stock/partials/contact_search.html",
                  {"q": query, "contacts": contacts})
