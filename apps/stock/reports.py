"""Rapor sorguları — salt okunur, hiçbir şey saklamaz.

SQLite notları (hepsi gerçek tuzak):
  * F() içeren her Sum açık output_field taşımalı, yoksa float sızar.
  * Her aggregate Coalesce ile sarılmalı; None bir KPI şablonda boş görünür
    ve bug sanılır.
  * Sonuçlar money() ile kuruşa yuvarlanmalı — Django aggregate sonucunu
    yuvarlamaz (bkz. utils.money docstring'i).
  * timezone.localdate() kullanılmalı, date.today() DEĞİL: sunucu UTC ise
    "bugünün cirosu" 3 saat kayar.
"""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, DecimalField, F, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from .models import Accessory, Device, Expense, Payment, Sale, SaleItem
from .utils import money

DEC = DecimalField(max_digits=14, decimal_places=2)
ZERO = Value(Decimal("0.00"), output_field=DEC)
IST = ZoneInfo("Europe/Istanbul")

#: Elde tutulan (parası bağlı) cihaz durumları
HELD_STATUSES = [Device.Status.STOKTA, Device.Status.REZERVE, Device.Status.SERVISTE]


def sold_lines(start=None, end=None):
    """Ciro/kâr hesabının TEK kaynağı.

    Sale.grand_total OKUNMAZ: o, basılan fişin üzerindeki rakamdır ve takas
    içeren fişlerde tahsil edilen tutardan farklıdır. Ciro her zaman satır
    kalemlerinden toplanır.
    """
    lines = SaleItem.objects.filter(sale__status=Sale.Status.TAMAMLANDI,
                                    returned_at__isnull=True)
    if start and end:
        lines = lines.filter(sale__sold_at__date__range=(start, end))
    return lines


# ---------------------------------------------------------------------------
# Ciro / kâr
# ---------------------------------------------------------------------------

def revenue_and_profit(start=None, end=None) -> dict:
    totals = sold_lines(start, end).aggregate(
        revenue=Coalesce(Sum("line_total", output_field=DEC), ZERO),
        cost=Coalesce(Sum("line_cost", output_field=DEC), ZERO),
        lines=Count("id"),
    )
    revenue = money(totals["revenue"])
    cost = money(totals["cost"])
    gross = revenue - cost
    # Marj Python'da hesaplanır: SQLite sıfıra bölmede hata değil NULL döner
    # ve KPI kutusu sessizce boşalırdı.
    margin = (gross / revenue * 100) if revenue else Decimal("0")
    return {
        "revenue": revenue, "cost": cost, "gross": gross,
        "margin": margin, "lines": totals["lines"],
    }


def expenses_for_period(start, end) -> dict:
    """Dönem giderleri.

    BİLİNÇLİ ASİMETRİ: cihaza bağlı giderler, cihazın SATILDIĞI döneme yazılır
    (eşleştirme ilkesi) — Mart'taki tamir, Nisan satışının marjına aittir.
    Genel giderler ise kendi harcama tarihine yazılır, çünkü hiçbir cihaza
    bağlı değildir.

    Burayı "düzelten" biri net kâr rakamını sessizce bozar.
    """
    sold_device_ids = sold_lines(start, end).filter(
        kind=SaleItem.Kind.CIHAZ).values("device_id")
    device_expense = Expense.objects.filter(
        # Subquery kullanılır: literal IN listesi yoğun bir aydan sonra
        # SQLITE_MAX_VARIABLE_NUMBER (999) sınırına çarpar.
        device_id__in=Subquery(sold_device_ids)
    ).aggregate(t=Coalesce(Sum("amount", output_field=DEC), ZERO))["t"]

    overhead = Expense.objects.filter(
        device__isnull=True, spent_on__range=(start, end)
    ).aggregate(t=Coalesce(Sum("amount", output_field=DEC), ZERO))["t"]

    return {"device": money(device_expense), "overhead": money(overhead),
            "total": money(device_expense) + money(overhead)}


def net_profit(start, end) -> dict:
    base = revenue_and_profit(start, end)
    costs = expenses_for_period(start, end)
    net = base["gross"] - costs["total"]
    net_margin = (net / base["revenue"] * 100) if base["revenue"] else Decimal("0")
    return {**base, "expenses": costs, "net": net, "net_margin": net_margin}


# ---------------------------------------------------------------------------
# Stok
# ---------------------------------------------------------------------------

def stock_counts() -> dict:
    device_count = Device.objects.filter(status=Device.Status.STOKTA).count()
    accessory_units = Accessory.objects.filter(
        is_active=True, stock_qty__gt=0
    ).aggregate(t=Coalesce(Sum("stock_qty"), Value(0)))["t"]
    return {"devices": device_count, "accessory_units": accessory_units}


def stock_capital() -> dict:
    """Bağlı sermaye — üç kalem.

    Ortadaki kalem (satılmamış cihazların tamir giderleri) unutulursa bağlı
    para olduğundan az görünür; o giderler stoğa kapitalize edilmiş maliyettir.
    """
    devices = Device.objects.filter(status__in=HELD_STATUSES).aggregate(
        t=Coalesce(Sum("purchase_price", output_field=DEC), ZERO))["t"]
    device_expenses = Expense.objects.filter(
        device__status__in=HELD_STATUSES
    ).aggregate(t=Coalesce(Sum("amount", output_field=DEC), ZERO))["t"]
    accessories = Accessory.objects.filter(stock_qty__gt=0).aggregate(
        t=Coalesce(Sum(F("stock_qty") * F("cost"), output_field=DEC), ZERO))["t"]

    devices, device_expenses, accessories = (money(devices),
                                             money(device_expenses),
                                             money(accessories))
    return {"devices": devices, "device_expenses": device_expenses,
            "accessories": accessories,
            "total": devices + device_expenses + accessories}


def turnover(start, end) -> dict:
    """Ortalama stokta kalma ve devir hızı.

    days_in_stock satış anında dondurulduğu için basit bir Avg yeterlidir.
    Join ile hesaplamak SQLite'ta DateField/DateTimeField karışımı üretirdi.
    """
    avg_days = Device.objects.filter(
        sold_at__range=(start, end), days_in_stock__isnull=False
    ).aggregate(a=Avg("days_in_stock"))["a"]

    sold_count = Device.objects.filter(sold_at__range=(start, end)).count()
    on_hand = (_units_on_hand(start) + _units_on_hand(end)) / 2 or 1
    return {
        "avg_days": round(avg_days) if avg_days is not None else None,
        "sold_count": sold_count,
        "ratio": round(sold_count / on_hand, 2),
    }


def _units_on_hand(day) -> int:
    return (Device.objects
            .filter(purchase_date__lte=day)
            .exclude(sold_at__lt=day)
            .exclude(status=Device.Status.KAYIP)
            .count())


def aging_buckets() -> list[dict]:
    """Stoktaki cihazların yaş dağılımı — hangi sermaye ne kadardır dönmüyor."""
    today = timezone.localdate()
    buckets = [("0-30 gün", 0, 30), ("31-60 gün", 31, 60),
               ("61-90 gün", 61, 90), ("90+ gün", 91, None)]
    rows = []
    for label, lo, hi in buckets:
        query = Device.objects.filter(status=Device.Status.STOKTA)
        query = query.filter(purchase_date__lte=today - timedelta(days=lo))
        if hi is not None:
            query = query.filter(purchase_date__gte=today - timedelta(days=hi))
        totals = query.aggregate(
            n=Count("id"),
            value=Coalesce(Sum("purchase_price", output_field=DEC), ZERO))
        rows.append({"label": label, "count": totals["n"],
                     "value": money(totals["value"])})
    return rows


# ---------------------------------------------------------------------------
# Satış kırılımları
# ---------------------------------------------------------------------------

def top_models(start=None, end=None, limit=10) -> list[dict]:
    """DeviceModel tablosunun asıl gerekçesi olan sorgu.

    Model adı serbest metin olsaydı "iphone 13", "İphone13" ve "IPHONE 13 "
    üç ayrı ürün olarak dönerdi.
    """
    rows = (sold_lines(start, end)
            .filter(kind=SaleItem.Kind.CIHAZ)
            .values("device__device_model__brand__name",
                    "device__device_model__name")
            .annotate(count=Count("id"),
                      revenue=Coalesce(Sum("line_total", output_field=DEC), ZERO),
                      profit=Coalesce(
                          Sum(F("line_total") - F("line_cost"), output_field=DEC),
                          ZERO))
            .order_by("-count")[:limit])
    return [{
        "brand": r["device__device_model__brand__name"] or "—",
        "model": r["device__device_model__name"] or "—",
        "count": r["count"],
        "revenue": money(r["revenue"]),
        "profit": money(r["profit"]),
    } for r in rows]


def revenue_series(months=12) -> dict:
    """Aylık ciro/kâr serisi (Chart.js için)."""
    today = timezone.localdate()
    first = (today.replace(day=1)
             - timedelta(days=31 * (months - 1))).replace(day=1)

    rows = (sold_lines()
            .filter(sale__sold_at__date__gte=first)
            # tzinfo AÇIKÇA verilir: sistem tz veritabanı yoksa Django sessizce
            # UTC'ye düşer ve 21:00 sonrası satışlar yanlış aya yazılır.
            .annotate(month=TruncMonth("sale__sold_at", tzinfo=IST))
            .values("month")
            .annotate(revenue=Coalesce(Sum("line_total", output_field=DEC), ZERO),
                      profit=Coalesce(
                          Sum(F("line_total") - F("line_cost"), output_field=DEC),
                          ZERO))
            .order_by("month"))

    by_month = {}
    for row in rows:
        if row["month"] is None:
            continue
        key = (row["month"].year, row["month"].month)
        by_month[key] = (money(row["revenue"]), money(row["profit"]))

    # Boş ayları doldur; eksik ay ekseni koparır
    labels, revenue, profit = [], [], []
    names = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
             "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
    year, month = first.year, first.month
    for _ in range(months):
        rev, prof = by_month.get((year, month), (Decimal("0"), Decimal("0")))
        labels.append(f"{names[month - 1]} {str(year)[2:]}")
        # DjangoJSONEncoder Decimal'ı STRING yapar, Chart.js sayı ister
        revenue.append(float(rev))
        profit.append(float(prof))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return {"labels": labels, "revenue": revenue, "profit": profit}


def cash_by_method(start, end) -> list[dict]:
    """Kasa dökümü — ciro değil, gerçekten tahsil edilen para."""
    from django.db.models import Case, When

    rows = (Payment.objects
            .filter(paid_at__date__range=(start, end))
            .values("method")
            .annotate(total=Coalesce(Sum(Case(
                When(kind=Payment.Kind.IADE, then=-F("amount")),
                default=F("amount"), output_field=DEC)), ZERO))
            .order_by("-total"))
    labels = dict(Payment.Method.choices)
    return [{"method": labels.get(r["method"], r["method"]),
             "total": money(r["total"])} for r in rows]


# ---------------------------------------------------------------------------
# Uyarı listeleri
# ---------------------------------------------------------------------------

def receivables():
    """Açık bakiyeler.

    Filtre SAKLANAN sütunlar üzerinden yapılır (indekslenebilir); annotate
    alias'ına filtre uygulamak tam tablo taraması yaptırırdı.

    `balance` diye annotate EDİLMEZ: Sale üzerinde aynı adda bir property var
    ve Django "property 'balance' has no setter" hatası verir. Şablonlar zaten
    property'yi kullanır.
    """
    return (Sale.objects
            .filter(status=Sale.Status.TAMAMLANDI, payable_total__gt=F("paid_total"))
            .select_related("customer")
            .order_by(F("due_date").asc(nulls_last=True)))


def receivables_total() -> Decimal:
    return money(receivables().aggregate(t=Coalesce(
        Sum(F("payable_total") - F("paid_total"), output_field=DEC), ZERO))["t"])


def overdue_receivables():
    return receivables().filter(due_date__lt=timezone.localdate())


def low_stock():
    return (Accessory.objects
            .filter(is_active=True, stock_qty__lte=F("min_stock_level"))
            .order_by("stock_qty", "name"))


def negative_stock():
    """Eksiye düşmüş aksesuarlar — düzeltilmesi gereken kayıtlar."""
    return Accessory.objects.filter(stock_qty__lt=0).order_by("stock_qty")


def expiring_warranty(days=30):
    today = timezone.localdate()
    return (Device.objects
            .filter(status=Device.Status.SATILDI,
                    warranty_end__range=(today, today + timedelta(days=days)))
            .select_related("device_model__brand", "sold_to")
            .order_by("warranty_end"))


# ---------------------------------------------------------------------------
# Panel özeti
# ---------------------------------------------------------------------------

def dashboard_kpis(user=None) -> dict:
    """Genel bakış kartları. Para gerektiren alanlar can_see_money'e bağlıdır."""
    from .permissions import can_see_money

    today = timezone.localdate()
    month_start = today.replace(day=1)
    counts = stock_counts()

    data = {
        "devices_in_stock": counts["devices"],
        "accessory_units": counts["accessory_units"],
        "low_stock_count": low_stock().count(),
        "negative_stock_count": negative_stock().count(),
        "sales_today": Sale.objects.filter(status=Sale.Status.TAMAMLANDI,
                                           sold_at__date=today).count(),
        "expiring_warranty_count": expiring_warranty().count(),
    }
    if not can_see_money(user):
        return data

    today_totals = revenue_and_profit(today, today)
    month_totals = net_profit(month_start, today)
    capital = stock_capital()
    data.update({
        "revenue_today": today_totals["revenue"],
        "profit_today": today_totals["gross"],
        "revenue_month": month_totals["revenue"],
        "gross_month": month_totals["gross"],
        "net_month": month_totals["net"],
        "margin_month": month_totals["net_margin"],
        "capital": capital["total"],
        "receivables": receivables_total(),
        "overdue_count": overdue_receivables().count(),
    })
    return data
