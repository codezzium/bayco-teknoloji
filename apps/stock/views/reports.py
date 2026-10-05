"""Stok genel bakışı ve raporlar."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .. import reports as rpt
from .base import access_required, can_see_money, has_access, panel_required

PERIODS = {
    "bugun": ("Bugün", 0),
    "7g": ("Son 7 Gün", 6),
    "30g": ("Son 30 Gün", 29),
    "ay": ("Bu Ay", None),
    "yil": ("Bu Yıl", None),
}


def _period(request):
    key = request.GET.get("donem", "30g")
    today = timezone.localdate()
    if key == "ay":
        return key, today.replace(day=1), today
    if key == "yil":
        return key, today.replace(month=1, day=1), today
    label, days = PERIODS.get(key, PERIODS["30g"])
    return key, today - timedelta(days=days), today


def _report_people():
    """Personel seçimindeki kişiler: panel ekibi (pasifler dahil) ve satışı
    olan herkes — ayrılmış personelin geçmiş satışları da raporlanabilsin."""
    from apps.staff.notify import panel_members

    return (get_user_model().objects
            .filter(Q(pk__in=panel_members().values("pk")) | Q(sales__isnull=False))
            .distinct()
            .order_by("-is_active", "first_name", "username"))


@panel_required
def overview(request):
    user = request.user
    context = {
        "active": "stok",
        "kpis": rpt.dashboard_kpis(user),
        "show_money": can_see_money(user),
        "low_stock": rpt.low_stock()[:6],
        "negative_stock": rpt.negative_stock()[:6],
        "expiring": rpt.expiring_warranty()[:6],
    }
    if context["show_money"]:
        context["chart"] = rpt.revenue_series(12)
    if has_access(user, "receivables"):
        context["overdue"] = rpt.overdue_receivables().select_related("customer")[:6]
    return render(request, "stock/overview.html", context)


@access_required("reports")
def reports(request):
    from apps.service import reports as service_rpt

    key, start, end = _period(request)
    return render(request, "stock/reports.html", {
        "active": "rapor",
        "period": key,
        "periods": PERIODS,
        "start": start, "end": end,
        "totals": rpt.net_profit(start, end),
        "capital": rpt.stock_capital(),
        "turnover": rpt.turnover(start, end),
        "aging": rpt.aging_buckets(),
        "top_models": rpt.top_models(start, end),
        "staff_sales": rpt.sales_by_staff(start, end),
        "people": _report_people(),
        "cash": rpt.cash_by_method(start, end),
        "receivables_total": rpt.receivables_total(),
        "overdue": rpt.overdue_receivables().select_related("customer")[:10],
        "chart": rpt.revenue_series(12),
        # Teknik servis kârı mağaza Net Kârı'na EKLENMEZ; kendi kartında durur.
        "service": service_rpt.report_widget(start, end),
        "show_money": True,
    })


@access_required("reports")
def staff_report(request, pk):
    """Tek personelin satış raporu: cihaz/aksesuar kırılımı, iadeler, grafik.

    Raporlar tikine bağlıdır (Raporlar sayfasındaki Personel Satışları
    tablosundan açılır); Patron'a Personel sayfasından da bağlantı verilir.
    """
    person = get_object_or_404(get_user_model(), pk=pk)
    key, start, end = _period(request)
    return render(request, "stock/staff_report.html", {
        "active": "rapor",
        "person": person,
        "people": _report_people(),
        "period": key, "periods": PERIODS,
        "start": start, "end": end,
        "summary": rpt.staff_sales_summary(start, end, person),
        "breakdown": rpt.staff_breakdown(start, end, person),
        "top_models": rpt.top_models(start, end, cashier=person),
        "chart": rpt.revenue_series(12, cashier=person),
    })
