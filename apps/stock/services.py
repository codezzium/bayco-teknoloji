"""Stok mutasyonlarının TEK yeri.

Kural: aksesuar stok adedi, cihaz durumu ve fiş toplamları yalnızca buradan
değiştirilir. View'lar bu fonksiyonları çağırır, ORM'e doğrudan yazmaz.

Üç gerekçe: (1) create_sale_from_cart altı tabloya dokunur ve ya hep ya hiç
olmalıdır; (2) aynı işlem hem htmx tarama akışından hem panel formundan hem de
içe aktarma komutundan çağrılır — bir view komut satırından çağrılamaz;
(3) "stock_qty tek bir yerde yazılır" invariantının grep'lenebilir bir adresi
olmalıdır.
"""

from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import Product

from .models import (
    ALLOWED_TRANSITIONS,
    Accessory,
    Device,
    DeviceStatusLog,
    Expense,
    Payment,
    Sale,
    SaleItem,
    StockMovement,
    TradeIn,
)
from .utils import digits_only, money, next_code, normalize_scan


# ===========================================================================
# İstisnalar — view'lar StockError yakalayıp messages.error() basar
# ===========================================================================

class StockError(Exception):
    """Kullanıcıya gösterilebilir iş kuralı hatası."""


class DeviceNotAvailable(StockError):
    pass


class InsufficientStock(StockError):
    pass


class InvalidStatusTransition(StockError):
    pass


class CustomerRequired(StockError):
    pass


class TradeInNotReversible(StockError):
    pass


class PriceChanged(StockError):
    """Sepetteki fiyat ile güncel fiyat farklı. `changes` listesi UI'ya gider."""

    def __init__(self, changes):
        self.changes = changes
        super().__init__("Sepetteki bazı fiyatlar değişmiş.")


# ===========================================================================
# Tarama çözümlemesi
# ===========================================================================

def resolve_scan(raw_code: str):
    """Okutulan kodu bir Device veya Accessory nesnesine çözer.

    Sıra bilinçlidir ve cihaz her zaman önceliklidir: BYC- ön eki ile saf
    rakamdan oluşan EAN çakışamaz, ama sıralama yine de belirleyici olsun.
    """
    code = normalize_scan(raw_code)
    if not code:
        return None

    device = Device.objects.filter(stock_code__iexact=code).select_related(
        "device_model__brand").first()
    if device:
        return device

    digits = digits_only(code)
    if digits and len(digits) in (14, 15, 16, 17):
        device = Device.objects.filter(
            Q(imei1=digits) | Q(imei2=digits)
        ).select_related("device_model__brand").first()
        if device:
            return device

    accessory = Accessory.objects.filter(sku__iexact=code).first()
    if accessory:
        return accessory

    if digits:
        accessory = Accessory.objects.filter(barcode=digits).first()
        if accessory:
            return accessory

    # Seri no ile son bir deneme (IMEI'siz tabletler / saatler)
    return Device.objects.filter(serial_no__iexact=code).select_related(
        "device_model__brand").first()


# ===========================================================================
# Cihaz
# ===========================================================================

@transaction.atomic
def create_device(*, user=None, **fields) -> Device:
    device = Device(created_by=user, **fields)
    device.full_clean(exclude=["stock_code", "warranty_end", "search_blob"])
    device.save()
    DeviceStatusLog.objects.create(
        device=device, from_status="", to_status=device.status,
        note="Stok girişi", created_by=user,
    )
    return device


@transaction.atomic
def set_device_status(device: Device, new_status: str, *, user=None, note="",
                      sale=None, _from_sale=False) -> Device:
    """Cihaz durumunu geçiş grafiğine uyarak değiştirir ve loglar."""
    if device.status == new_status:
        return device

    allowed = ALLOWED_TRANSITIONS.get(device.status, set())
    if new_status not in allowed:
        raise InvalidStatusTransition(
            f"{device.get_status_display()} → "
            f"{Device.Status(new_status).label} geçişi yapılamaz."
        )
    # SATILDI / IADE yalnızca satış servislerinden atanabilir; elle
    # işaretlenirse fiş, stok hareketi ve tahsilat kaydı oluşmaz.
    if not _from_sale and new_status in (Device.Status.SATILDI, Device.Status.IADE):
        raise InvalidStatusTransition(
            "Satıldı / İade durumu yalnızca satış ekranından değiştirilebilir."
        )

    old = device.status
    device.status = new_status
    device.save(update_fields=["status", "updated_at"])
    DeviceStatusLog.objects.create(
        device=device, from_status=old, to_status=new_status,
        sale=sale, note=note, created_by=user,
    )
    return device


# ===========================================================================
# Aksesuar stoğu
# ===========================================================================

def _current_balance(accessory: Accessory) -> int:
    return accessory.movements.aggregate(
        t=Coalesce(Sum("quantity"), Value(0)))["t"]


def _resync_accessory_qty(accessory: Accessory) -> int:
    """Accessory.stock_qty'nin TEK yazarı.

    Defterden yeniden toplar — asla artırımlı çalışmaz. Bu sayede önbellek
    kendi kendini onarır; kaçırılmış bir azaltma diye bir hata sınıfı kalmaz.
    """
    balance = _current_balance(accessory)
    if accessory.stock_qty != balance:
        accessory.stock_qty = balance
        accessory.save(update_fields=["stock_qty", "updated_at"])
    return balance


@transaction.atomic
def _record_movement(accessory: Accessory, quantity: int, reason: str, *,
                     user=None, unit_cost=None, sale_item=None,
                     note="") -> StockMovement:
    if quantity == 0:
        raise StockError("Miktar sıfır olamaz.")
    balance = _current_balance(accessory) + quantity
    movement = StockMovement.objects.create(
        accessory=accessory, quantity=quantity, reason=reason,
        unit_cost=unit_cost, sale_item=sale_item, balance_after=balance,
        note=note, created_by=user,
    )
    _resync_accessory_qty(accessory)
    return movement


@transaction.atomic
def receive_accessory_stock(accessory: Accessory, quantity: int, *, user=None,
                            unit_cost=None, note="",
                            opening=False) -> StockMovement:
    if quantity <= 0:
        raise StockError("Giriş miktarı pozitif olmalıdır.")
    reason = (StockMovement.Reason.ACILIS if opening
              else StockMovement.Reason.GIRIS)
    movement = _record_movement(accessory, quantity, reason, user=user,
                                unit_cost=unit_cost, note=note)
    # Yeni parti alış fiyatı girildiyse kartın maliyetini güncelle. Geçmiş
    # satırlar unit_cost snapshot'ı taşıdığı için eski kâr rakamları bozulmaz.
    if unit_cost is not None and unit_cost != accessory.cost:
        accessory.cost = unit_cost
        accessory.save(update_fields=["cost", "updated_at"])
    return movement


@transaction.atomic
def adjust_accessory_stock(accessory: Accessory, counted_qty: int, *, user=None,
                           note="") -> StockMovement | None:
    """Sayım sonucu. Doğrudan set etmez, FARK kadar hareket yazar."""
    diff = counted_qty - _current_balance(accessory)
    if diff == 0:
        return None
    return _record_movement(accessory, diff, StockMovement.Reason.SAYIM,
                            user=user, note=note or f"Sayım: {counted_qty} adet")


@transaction.atomic
def write_off_accessory(accessory: Accessory, quantity: int, *, user=None,
                        note="") -> StockMovement:
    if quantity <= 0:
        raise StockError("Fire miktarı pozitif olmalıdır.")
    return _record_movement(accessory, -quantity, StockMovement.Reason.FIRE,
                            user=user, note=note)


# ===========================================================================
# Satış
# ===========================================================================

def _q(value) -> Decimal:
    return money(value)


def check_cart_prices(cart: dict) -> list[dict]:
    """Sepetteki fiyatlar ile güncel fiyatları karşılaştırır.

    Satışı kesmez — fark varsa UI'da onay istenir. Maliyet karşılaştırılmaz;
    maliyet zaten kasada güncel değerden okunur.
    """
    changes = []
    for line in cart.get("lines", []):
        cart_price = _q(line.get("unit"))
        if line["kind"] == SaleItem.Kind.CIHAZ:
            device = Device.objects.filter(pk=line["id"]).first()
            current = device.list_price if device and device.list_price else None
        else:
            accessory = Accessory.objects.filter(pk=line["id"]).first()
            current = accessory.price if accessory else None
        if current is not None and _q(current) != cart_price:
            changes.append({
                "lid": line["lid"], "name": line["name"],
                "old": cart_price, "new": _q(current),
            })
    return changes


@transaction.atomic
def create_sale_from_cart(cart: dict, *, user, payments=None, due_date=None,
                          note="", confirm_prices=False) -> Sale:
    """Oturumdaki sepeti tek atomik işlemde fişe dönüştürür.

    Hiçbir şey değiştirilmeden ÖNCE tüm doğrulamalar yapılır; aksi halde yarım
    kalan bir satış cihazı "satıldı" bırakıp stok hareketini yazmayabilir.
    """
    lines = cart.get("lines") or []
    trade_ins = cart.get("trade_ins") or []
    if not lines and not trade_ins:
        raise StockError("Sepet boş.")

    # --- 1. Müşteri kuralı: yalnızca sepette cihaz varsa zorunlu -------------
    has_device = any(l["kind"] == SaleItem.Kind.CIHAZ for l in lines)
    customer = None
    if cart.get("customer_id"):
        from .models import Contact
        customer = Contact.objects.filter(pk=cart["customer_id"]).first()
    if (has_device or trade_ins) and customer is None:
        raise CustomerRequired(
            "Cihaz satışında müşteri seçilmesi zorunludur. "
            "(Aksesuar satışında gerekmez.)"
        )

    # --- 2. Fiyat kayması ---------------------------------------------------
    if not confirm_prices:
        changes = check_cart_prices(cart)
        if changes:
            raise PriceChanged(changes)

    # --- 3. Cihazları kilitle ve uygunluk doğrula ---------------------------
    device_ids = [l["id"] for l in lines if l["kind"] == SaleItem.Kind.CIHAZ]
    devices = {}
    if device_ids:
        locked = (Device.objects.select_for_update()
                  .select_related("device_model__brand")
                  .filter(pk__in=device_ids))
        devices = {d.pk: d for d in locked}
        missing = set(device_ids) - set(devices)
        if missing:
            raise StockError("Sepetteki bazı cihazlar artık kayıtlı değil.")
        for device in devices.values():
            if not device.is_available:
                raise DeviceNotAvailable(
                    f"{device.stock_code} artık satışa uygun değil "
                    f"({device.get_status_display()})."
                )

    # --- 4. Aksesuar stoğunu doğrula ----------------------------------------
    accessory_ids = [l["id"] for l in lines if l["kind"] == SaleItem.Kind.AKSESUAR]
    accessories = {a.pk: a for a in
                   Accessory.objects.select_for_update().filter(pk__in=accessory_ids)}
    for line in lines:
        if line["kind"] != SaleItem.Kind.AKSESUAR:
            continue
        accessory = accessories.get(line["id"])
        if accessory is None:
            raise StockError("Sepetteki bazı aksesuarlar artık kayıtlı değil.")
        if not line.get("allow_negative") and accessory.stock_qty < line["qty"]:
            raise InsufficientStock(
                f"{accessory.name}: stokta {accessory.stock_qty} adet var, "
                f"{line['qty']} adet satılmaya çalışılıyor."
            )

    # --- 5. Fiş başlığı -----------------------------------------------------
    now = timezone.now()
    sale = Sale.objects.create(
        customer=customer, status=Sale.Status.TAMAMLANDI, sold_at=now,
        due_date=due_date, note=note or cart.get("note", ""), cashier=user,
        receipt_no=next_code("sale", "BYC-S"),
    )

    # --- 6. Satır kalemleri -------------------------------------------------
    for line in lines:
        if line["kind"] == SaleItem.Kind.CIHAZ:
            device = devices[line["id"]]
            item = SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.CIHAZ, device=device,
                item_name=device.label, item_code=device.stock_code,
                item_imei=device.imei1, quantity=1,
                unit_price=_q(line["unit"]),
                # Maliyet kasada güncel değerden okunur; sepet snapshot'ı
                # yalnızca sepet ekranında kâr göstermek içindir.
                unit_cost=_q(device.purchase_price),
                line_discount=_q(line.get("discount", 0)),
            )
            # GeneratedField create() sonrası Python nesnesinde DOLU DEĞİLDİR.
            item.refresh_from_db(fields=["line_total", "line_cost"])
            _sell_device(device, sale=sale, item=item, user=user)
        else:
            accessory = accessories[line["id"]]
            item = SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.AKSESUAR, accessory=accessory,
                item_name=str(accessory), item_code=accessory.barcode or accessory.sku,
                quantity=line["qty"], unit_price=_q(line["unit"]),
                unit_cost=_q(accessory.cost),
                line_discount=_q(line.get("discount", 0)),
            )
            _record_movement(accessory, -line["qty"], StockMovement.Reason.SATIS,
                             user=user, sale_item=item,
                             note=f"Fiş {sale.receipt_no}")

    # --- 7. Takas: gelen cihaz maliyetiyle stoğa girer ----------------------
    for entry in trade_ins:
        _create_trade_in(sale, entry, user=user, customer=customer)

    # --- 8. Toplamlar ve tahsilat -------------------------------------------
    sale.recalculate()
    for payment in (payments or []):
        record_payment(sale, payment["amount"], method=payment.get("method", "nakit"),
                       user=user, note=payment.get("note", ""))
    sale.refresh_from_db()
    return sale


def _sell_device(device: Device, *, sale: Sale, item: SaleItem, user) -> None:
    """Cihazı satıldı işaretler ve denormalize satış alanlarını doldurur."""
    sold_date = timezone.localdate()
    device.sold_to = sale.customer
    device.sold_at = sold_date
    device.sold_price = item.line_total if item.line_total is not None else _q(
        item.unit_price - item.line_discount)
    device.days_in_stock = max((sold_date - device.purchase_date).days, 0)
    # Garanti başlangıcı girilmemişse satış günü sayılır. İkinci elde üreticinin
    # kalan garantisi devrediliyorsa kullanıcı daha erken bir tarih girmiştir ve
    # o tarihe dokunulmaz.
    if device.warranty_months and not device.warranty_start:
        device.warranty_start = sold_date
    device.status = Device.Status.SATILDI
    device.save(update_fields=["sold_to", "sold_at", "sold_price", "days_in_stock",
                               "warranty_start", "warranty_end", "status",
                               "search_blob", "updated_at"])
    DeviceStatusLog.objects.create(
        device=device, from_status=Device.Status.STOKTA,
        to_status=Device.Status.SATILDI, sale=sale,
        note=f"Fiş {sale.receipt_no}", created_by=user,
    )
    unpublish_device(device)


def _create_trade_in(sale: Sale, entry: dict, *, user, customer) -> TradeIn:
    """Takasla gelen cihazı stoğa alır ve fişe bağlar.

    TradeIn.amount ile Device.purchase_price aynı değeri taşır ve bu
    BİLİNÇLİDİR: fişteki takas bedeli dondurulur, cihazın maliyet tabanı ise
    sonradan düzeltilebilir veya giderle desteklenebilir.
    """
    from .models import DeviceModel

    amount = _q(entry["amount"])
    device = Device.objects.create(
        device_model=DeviceModel.objects.get(pk=entry["device_model_id"]),
        condition=entry.get("condition", Device.Condition.IKINCI_EL),
        status=Device.Status.STOKTA,
        imei1=digits_only(entry.get("imei1", "")),
        color=entry.get("color", ""),
        storage=entry.get("storage", ""),
        defect_note=entry.get("note", ""),
        supplier=customer,
        purchase_date=timezone.localdate(),
        purchase_price=amount,
        acquisition=Device.Acquisition.TAKAS,
        created_by=user,
    )
    DeviceStatusLog.objects.create(
        device=device, from_status="", to_status=Device.Status.STOKTA,
        sale=sale, note=f"Takas girişi — fiş {sale.receipt_no}", created_by=user,
    )
    return TradeIn.objects.create(sale=sale, device=device, amount=amount,
                                  note=entry.get("note", ""))


@transaction.atomic
def record_historical_sale(device: Device, *, customer, sold_on, price, user=None,
                           paid=True) -> Sale:
    if device.status == Device.Status.SATILDI:
        raise DeviceNotAvailable(f"{device.stock_code} zaten satılmış.")
    price = _q(price)
    sold_at = timezone.make_aware(datetime.combine(sold_on, time(12, 0)))

    sale = Sale.objects.create(
        customer=customer, status=Sale.Status.TAMAMLANDI, sold_at=sold_at,
        cashier=user, note="Excel'den aktarıldı",
        receipt_no=next_code("sale", "BYC-S"),
    )
    item = SaleItem.objects.create(
        sale=sale, kind=SaleItem.Kind.CIHAZ, device=device,
        item_name=device.label, item_code=device.stock_code,
        item_imei=device.imei1, quantity=1,
        unit_price=price, unit_cost=_q(device.purchase_price),
    )
    item.refresh_from_db(fields=["line_total", "line_cost"])
    _sell_device(device, sale=sale, item=item, user=user)
    if device.sold_at != sold_on:
        device.sold_at = sold_on
        device.days_in_stock = max((sold_on - device.purchase_date).days, 0)
        device.save(update_fields=["sold_at", "days_in_stock", "updated_at"])
    sale.recalculate()
    if paid:
        record_payment(sale, price, method=Payment.Method.NAKIT, user=user,
                       paid_at=sale.sold_at, note="Excel'den aktarıldı")
    sale.refresh_from_db()
    return sale


@transaction.atomic
def record_payment(sale: Sale, amount, *, method="nakit", user=None,
                   kind=Payment.Kind.TAHSILAT, paid_at=None, note="") -> Payment:
    amount = _q(amount)
    if amount <= 0:
        raise StockError("Ödeme tutarı pozitif olmalıdır.")
    payment = Payment.objects.create(
        sale=sale, kind=kind, method=method, amount=amount,
        paid_at=paid_at or timezone.now(), note=note, created_by=user,
    )
    sale.recalculate()
    return payment


@transaction.atomic
def return_sale_item(item: SaleItem, *, user=None, reason="", refund=True) -> SaleItem:
    """Tek bir satır kalemini iade eder.

    returned_at, "bu satır artık ürününü tutmuyor" bilgisinin tek kaynağıdır;
    kısmi tekil indeks bunu okuduğu için cihaz otomatik olarak yeniden
    satılabilir hale gelir.
    """
    if item.returned_at:
        raise StockError("Bu kalem zaten iade edilmiş.")

    refund_amount = item.line_total
    item.returned_at = timezone.now()
    item.return_reason = reason
    item.save(update_fields=["returned_at", "return_reason"])

    if item.kind == SaleItem.Kind.CIHAZ and item.device_id:
        device = Device.objects.select_for_update().get(pk=item.device_id)
        device.status = Device.Status.STOKTA
        device.sold_to = None
        device.sold_at = None
        device.sold_price = None
        device.days_in_stock = None
        device.save(update_fields=["status", "sold_to", "sold_at", "sold_price",
                                   "days_in_stock", "updated_at"])
        DeviceStatusLog.objects.create(
            device=device, from_status=Device.Status.SATILDI,
            to_status=Device.Status.STOKTA, sale=item.sale,
            note=f"İade: {reason}"[:200], created_by=user,
        )
    elif item.accessory_id:
        accessory = Accessory.objects.select_for_update().get(pk=item.accessory_id)
        _record_movement(accessory, item.quantity, StockMovement.Reason.IADE,
                         user=user, sale_item=item,
                         note=f"İade — fiş {item.sale.receipt_no}")

    sale = item.sale
    if refund and refund_amount and refund_amount > 0:
        Payment.objects.create(
            sale=sale, kind=Payment.Kind.IADE, method=Payment.Method.NAKIT,
            amount=_q(refund_amount), paid_at=timezone.now(),
            note=f"İade: {item.item_name}"[:200], created_by=user,
        )
    sale.recalculate()
    return item


@transaction.atomic
def void_sale(sale: Sale, *, user=None, reason: str = "") -> Sale:
    """Fişi iptal eder: tüm kalemler iade edilir, tahsilat geri ödenir."""
    if sale.status == Sale.Status.IPTAL:
        raise StockError("Bu fiş zaten iptal edilmiş.")

    # Takas geri alınabilir mi? Gelen cihaza gider yazılmış ya da satılmışsa
    # kayıtları bozmadan geri alınamaz — kullanıcı elle çözmelidir.
    for trade_in in sale.trade_ins.select_related("device"):
        device = trade_in.device
        if device.expenses.exists() or device.sale_items.exists():
            raise TradeInNotReversible(
                f"{device.stock_code} takasla girmiş ve üzerinde gider/satış "
                f"kaydı var. Fişi iptal etmeden önce bu kaydı elle çözün."
            )

    for item in sale.items.filter(returned_at__isnull=True):
        return_sale_item(item, user=user, reason=reason or "Fiş iptali",
                         refund=False)

    sale.refresh_from_db()
    if sale.paid_total and sale.paid_total > 0:
        Payment.objects.create(
            sale=sale, kind=Payment.Kind.IADE, method=Payment.Method.NAKIT,
            amount=_q(sale.paid_total), paid_at=timezone.now(),
            note="Fiş iptali", created_by=user,
        )

    for trade_in in sale.trade_ins.select_related("device"):
        device = trade_in.device
        trade_in.delete()
        device.status_logs.all().delete()
        device.delete()

    sale.status = Sale.Status.IPTAL
    sale.voided_at = timezone.now()
    sale.voided_by = user
    sale.void_reason = reason[:200]
    sale.save(update_fields=["status", "voided_at", "voided_by", "void_reason",
                             "updated_at"])
    sale.recalculate()
    return sale


# ===========================================================================
# Giderler
# ===========================================================================

@transaction.atomic
def add_device_expense(device: Device, amount, *, kind, title, user=None,
                       spent_on=None, note="") -> Expense:
    if kind not in Expense.DEVICE_KINDS:
        raise StockError(
            "Bu gider türü bir cihaza bağlanamaz (genel işletme gideridir)."
        )
    return Expense.objects.create(
        device=device, kind=kind, title=title, amount=_q(amount),
        spent_on=spent_on or timezone.localdate(), note=note, created_by=user,
    )


# ===========================================================================
# Site vitrini
# ===========================================================================

@transaction.atomic
def publish_device_to_site(device: Device, *, user=None) -> Product:
    """Cihazı sitedeki vitrine ilan olarak çıkarır.

    ONLINE SATIŞ DEĞİLDİR: üretilen kayıt mevcut catalog.Product ilanlarıyla
    birebir aynıdır (fiyat + WhatsApp butonu). Site üzerinden sipariş/ödeme
    alınmaz.

    catalog.Product fiyatı decimal_places=0 olduğu için burada bir yuvarlama
    sınırı vardır — 24.999,90 ₺ sitede 25.000 ₺ görünür.
    """
    if device.status != Device.Status.STOKTA:
        raise StockError("Yalnızca stoktaki cihazlar siteye çıkarılabilir.")

    product = device.published_product or Product()
    product.name = device.label
    product.brand = device.device_model.brand
    product.condition = (Product.Condition.SIFIR
                         if device.condition == Device.Condition.SIFIR
                         else Product.Condition.IKINCI_EL)
    if device.list_price is not None:
        product.price = Decimal(device.list_price).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
    product.storage = device.storage
    product.color = device.color
    product.warranty = device.warranty_label
    if device.battery_health:
        product.condition_grade = f"Pil sağlığı %{device.battery_health}"
    product.is_active = True
    product.save()

    if device.published_product_id != product.pk:
        device.published_product = product
        device.save(update_fields=["published_product", "updated_at"])
    return product


def unpublish_device(device: Device) -> None:
    """Site ilanını pasife alır. Ürün kaydı silinmez — SEO/geçmiş korunur."""
    product = device.published_product
    if product and product.is_active:
        product.is_active = False
        product.save(update_fields=["is_active"])
