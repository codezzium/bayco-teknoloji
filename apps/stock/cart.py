"""Kasa sepeti — Django oturumunda tutulur.

Neden taslak bir Sale satırı değil: patron gün boyu yalnızca bakmak için ürün
okutacak. Taslak satırlar satış tablosunu çöple doldurur, her ciro raporunu
kirletir ve gecelik temizlik işi gerektirir. Oturum sepeti sayfa yenilemeye
dayanır ve kendiliğinden buharlaşır.

Neden Alpine istemci durumu değil: telefonda yanlışlıkla sayfa yenilemek çok
kolay; ayrıca fiyat ve stok doğrulaması sunucuda yapılmalıdır.
"""

from decimal import Decimal

from django.utils import timezone

from .models import Accessory, Device, SaleItem
from .utils import money

SESSION_KEY = "stock_cart"
MAX_AGE_HOURS = 12


def empty_cart() -> dict:
    return {
        "ts": timezone.now().timestamp(),
        "customer_id": None,
        "note": "",
        "lines": [],
        "trade_ins": [],
    }


def get_cart(request) -> dict:
    cart = request.session.get(SESSION_KEY)
    if not isinstance(cart, dict) or "lines" not in cart:
        cart = empty_cart()
    elif (timezone.now().timestamp() - cart.get("ts", 0)) > MAX_AGE_HOURS * 3600:
        cart = empty_cart()          # unutulmuş sepet
    cart.setdefault("trade_ins", [])
    return cart


def save_cart(request, cart: dict) -> None:
    cart["ts"] = timezone.now().timestamp()
    request.session[SESSION_KEY] = cart
    # İç içe yapı değiştiğinde Django bunu KENDİ ALGILAMAZ; yalnızca üst
    # seviye anahtar atamasını izler.
    request.session.modified = True


def clear_cart(request) -> dict:
    cart = empty_cart()
    save_cart(request, cart)
    return cart


# ---------------------------------------------------------------------------
# Satır işlemleri
# ---------------------------------------------------------------------------

def add_item(cart: dict, obj, *, quantity=1) -> tuple[dict, str]:
    """Sepete cihaz veya aksesuar ekler. (cart, mesaj) döndürür."""
    if isinstance(obj, Device):
        lid = f"d-{obj.pk}"
        if any(line["lid"] == lid for line in cart["lines"]):
            return cart, f"{obj.stock_code} zaten sepette."
        if not obj.is_available:
            return cart, (f"{obj.stock_code} satışa uygun değil "
                          f"({obj.get_status_display()}).")
        cart["lines"].append({
            "lid": lid, "kind": SaleItem.Kind.CIHAZ, "id": obj.pk,
            "code": obj.stock_code, "name": obj.label, "imei": obj.imei1,
            "qty": 1,                       # seri takipli: her zaman 1
            "unit": str(money(obj.list_price if obj.list_price is not None else 0)),
            "cost": str(money(obj.purchase_price)),
            "discount": "0.00",
        })
        return cart, f"{obj.stock_code} sepete eklendi."

    if isinstance(obj, Accessory):
        lid = f"a-{obj.pk}"
        for line in cart["lines"]:
            if line["lid"] == lid:
                line["qty"] += quantity
                return cart, f"{obj.name}: {line['qty']} adet."
        cart["lines"].append({
            "lid": lid, "kind": SaleItem.Kind.AKSESUAR, "id": obj.pk,
            "code": obj.barcode or obj.sku, "name": str(obj), "imei": "",
            "qty": quantity,
            "unit": str(money(obj.price)),
            "cost": str(money(obj.cost)),
            "discount": "0.00",
        })
        return cart, f"{obj.name} sepete eklendi."

    return cart, "Bilinmeyen ürün türü."


def remove_line(cart: dict, lid: str) -> dict:
    cart["lines"] = [line for line in cart["lines"] if line["lid"] != lid]
    return cart


def set_quantity(cart: dict, lid: str, quantity: int) -> dict:
    for line in cart["lines"]:
        if line["lid"] != lid:
            continue
        if line["kind"] == SaleItem.Kind.CIHAZ:
            return cart                     # cihaz adedi değiştirilemez
        if quantity <= 0:
            return remove_line(cart, lid)
        line["qty"] = quantity
    return cart


def set_price(cart: dict, lid: str, price) -> dict:
    for line in cart["lines"]:
        if line["lid"] == lid:
            line["unit"] = str(money(price))
    return cart


def set_discount(cart: dict, lid: str, discount) -> dict:
    for line in cart["lines"]:
        if line["lid"] == lid:
            line["discount"] = str(max(money(discount), Decimal("0.00")))
    return cart


def add_trade_in(cart: dict, entry: dict) -> dict:
    entry = dict(entry)
    entry["tid"] = f"t-{len(cart['trade_ins']) + 1}"
    entry["amount"] = str(money(entry.get("amount", 0)))
    cart["trade_ins"].append(entry)
    return cart


def remove_trade_in(cart: dict, tid: str) -> dict:
    cart["trade_ins"] = [t for t in cart["trade_ins"] if t.get("tid") != tid]
    return cart


# ---------------------------------------------------------------------------
# Görüntüleme
# ---------------------------------------------------------------------------

def line_total(line) -> Decimal:
    return money(Decimal(line["unit"]) * line["qty"]
                 - Decimal(line.get("discount", "0")))


def line_cost(line) -> Decimal:
    return money(Decimal(line["cost"]) * line["qty"])


def summarize(cart: dict, *, with_money=True) -> dict:
    """Sepet toplamlarını sunucuda hesaplar. Tarayıcıda hiç aritmetik yapılmaz."""
    lines = []
    subtotal = Decimal("0.00")
    cost_total = Decimal("0.00")
    for line in cart["lines"]:
        item = dict(line)
        item["total"] = line_total(line)
        item["cost_total"] = line_cost(line)
        item["profit"] = item["total"] - item["cost_total"]
        subtotal += item["total"]
        cost_total += item["cost_total"]
        lines.append(item)

    trade_in_total = sum((money(t["amount"]) for t in cart["trade_ins"]),
                         Decimal("0.00"))
    return {
        "lines": lines,
        "trade_ins": cart["trade_ins"],
        # Cihaz varsa müşteri zorunlu — bu tamamen sepet içeriğinin bir
        # fonksiyonu olduğu için sunucuda hesaplanır, Alpine'a gerek yok.
        "has_device": any(l["kind"] == SaleItem.Kind.CIHAZ for l in cart["lines"]),
        "count": len(cart["lines"]),
        "subtotal": subtotal,                       # = ciro
        "trade_in_total": trade_in_total,
        "payable": subtotal - trade_in_total,       # = tahsil edilecek
        "cost_total": cost_total if with_money else None,
        "profit": (subtotal - cost_total) if with_money else None,
    }
