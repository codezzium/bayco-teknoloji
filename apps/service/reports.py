"""Teknik servis raporları — salt okunur.

Servis kârı mağaza satış kârına (apps/stock/reports.net_profit) EKLENMEZ;
Raporlar sayfasında kendi kartında durur. SQLite kuralları stok raporlarıyla
aynıdır: her Sum output_field + Coalesce taşır, sonuç money() ile yuvarlanır.
"""

from decimal import Decimal

from django.db.models import Case, Count, F, Q, Subquery, Sum, When
from django.db.models.functions import Coalesce

from apps.stock.models import DEC, ZERO, Payment
from apps.stock.utils import money

from .models import (
    RepairShop,
    RepairShopPayment,
    ServiceCost,
    ServiceOutsource,
    ServicePayment,
    ServiceTicket,
)

Status = ServiceTicket.Status
DONDU = ServiceOutsource.Status.DONDU


def closed_tickets(start, end):
    """Dönemde müşteriye geri verilen kayıtlar (teslim + tamirsiz iade)."""
    return ServiceTicket.objects.filter(status__in=ServiceTicket.CLOSED_STATUSES,
                                        closed_at__date__range=(start, end))


def service_profit(start, end) -> dict:
    """Dönem servis kârı.

    EŞLEŞTİRME İLKESİ (stok giderleriyle aynı): bir kaydın iç maliyeti ve
    teknik servis bedeli, kaydın KAPANDIĞI döneme yazılır — Mart'ta alınan parça,
    Nisan'da teslim edilen tamirin marjına aittir. Tamirsiz iadeler de dahildir:
    o işe harcanan parça/teknik servis parası boşa gitmiş bir maliyettir.
    """
    tickets = closed_tickets(start, end)
    ids = Subquery(tickets.values("pk"))
    totals = tickets.aggregate(
        revenue=Coalesce(Sum("final_price", output_field=DEC), ZERO),
        count=Count("id"),
        delivered=Count("id", filter=Q(status=Status.TESLIM)),
    )
    internal = ServiceCost.objects.filter(ticket_id__in=ids).aggregate(
        t=Coalesce(Sum("amount", output_field=DEC), ZERO))["t"]
    external = ServiceOutsource.objects.filter(ticket_id__in=ids, status=DONDU).aggregate(
        t=Coalesce(Sum("cost", output_field=DEC), ZERO))["t"]

    revenue, internal, external = money(totals["revenue"]), money(internal), money(external)
    cost = internal + external
    net = revenue - cost
    # Marj Python'da: SQLite sıfıra bölmede NULL döner, kutu boş kalırdı.
    margin = (net / revenue * 100) if revenue else Decimal("0")
    return {"count": totals["count"], "delivered": totals["delivered"],
            "revenue": revenue, "internal": internal, "external": external,
            "cost": cost, "net": net, "margin": margin}


def service_cash(start, end) -> Decimal:
    """Dönemde servis için fiilen tahsil edilen para (kapora dahil, iade düşülmüş)."""
    return money(ServicePayment.objects.filter(paid_at__date__range=(start, end)).aggregate(
        t=Coalesce(Sum(Case(When(kind=Payment.Kind.IADE, then=-F("amount")),
                            default=F("amount"), output_field=DEC)), ZERO))["t"])


def shop_paid(start, end) -> Decimal:
    return money(RepairShopPayment.objects.filter(paid_at__range=(start, end)).aggregate(
        t=Coalesce(Sum("amount", output_field=DEC), ZERO))["t"])


def service_receivables() -> Decimal:
    """Teslim edilmiş ama ücreti tam alınmamış kayıtların toplam alacağı."""
    return money(ServiceTicket.objects
                 .filter(status=Status.TESLIM, final_price__gt=F("paid_total"))
                 .aggregate(t=Coalesce(Sum(F("final_price") - F("paid_total"),
                                           output_field=DEC), ZERO))["t"])


# ---------------------------------------------------------------------------
# Teknik servis hesapları
# ---------------------------------------------------------------------------

def _debts():
    """{shop_id: borç}. Borç yalnızca dönen (status=dondu) işlerden yazılır."""
    return {r["shop"]: money(r["t"]) for r in (
        ServiceOutsource.objects.filter(status=DONDU).values("shop")
        .annotate(t=Coalesce(Sum("cost", output_field=DEC), ZERO)).order_by())}


def _payments():
    return {r["shop"]: money(r["t"]) for r in (
        RepairShopPayment.objects.values("shop")
        .annotate(t=Coalesce(Sum("amount", output_field=DEC), ZERO)).order_by())}


def shop_balances(shops=None) -> list[dict]:
    """Teknik servis başına borç, ödenen, bakiye ve şu an orada olan cihaz sayısı.

    İki ayrı gruplama: borç ve ödeme aynı join'de toplansaydı satırlar
    birbirini çarpar, rakamlar katlanırdı.
    """
    shops = list(shops if shops is not None else RepairShop.objects.all())
    debts, paid = _debts(), _payments()
    at_shop = dict(ServiceOutsource.objects
                   .filter(status=ServiceOutsource.Status.GONDERILDI)
                   .values_list("shop").annotate(n=Count("id")).order_by())
    zero = Decimal("0.00")
    return [{"shop": shop,
             "debt": debts.get(shop.pk, zero),
             "paid": paid.get(shop.pk, zero),
             "balance": debts.get(shop.pk, zero) - paid.get(shop.pk, zero),
             "at_shop": at_shop.get(shop.pk, 0)} for shop in shops]


def shop_debt_total() -> Decimal:
    """Tüm teknik servislere net borç (avans verilen teknik servis eksi bakiye taşır)."""
    return sum(_debts().values(), Decimal("0.00")) - sum(_payments().values(),
                                                         Decimal("0.00"))


def shop_statement(shop) -> list[dict]:
    """Teknik servis ekstresi: tarih sıralı borç/ödeme satırları ve yürüyen bakiye."""
    rows = []
    for job in (shop.jobs.filter(status=DONDU)
                .select_related("ticket__device_model__brand")):
        rows.append({"date": job.returned_at or job.sent_at, "order": job.created_at,
                     "kind": "is", "job": job, "debit": money(job.cost),
                     "credit": None})
    for payment in shop.payments.select_related("outsource__ticket"):
        rows.append({"date": payment.paid_at, "order": payment.created_at,
                     "kind": "odeme", "payment": payment, "debit": None,
                     "credit": payment.amount})
    rows.sort(key=lambda row: (row["date"], row["order"]))
    balance = Decimal("0.00")
    for row in rows:
        balance += (row["debit"] or 0) - (row["credit"] or 0)
        row["balance"] = balance
    return rows


def open_counts() -> dict:
    rows = dict(ServiceTicket.objects.filter(status__in=ServiceTicket.OPEN_STATUSES)
                .values_list("status").annotate(n=Count("id")).order_by())
    return {"open": sum(rows.values()),
            "ready": rows.get(Status.HAZIR, 0),
            "at_shop": rows.get(Status.DIS_SERVISTE, 0),
            "by_status": rows}


def report_widget(start, end) -> dict:
    """Raporlar sayfasındaki Teknik Servis kartının tüm verisi."""
    return {
        "profit": service_profit(start, end),
        "cash": service_cash(start, end),
        "shop_paid": shop_paid(start, end),
        "shop_debt": shop_debt_total(),
        "receivables": service_receivables(),
        "counts": open_counts(),
    }
