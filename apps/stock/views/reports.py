"""Stok genel bakışı ve raporlar."""

from datetime import timedelta

from django.shortcuts import render
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
        "cash": rpt.cash_by_method(start, end),
        "receivables_total": rpt.receivables_total(),
        "overdue": rpt.overdue_receivables().select_related("customer")[:10],
        "chart": rpt.revenue_series(12),
        "show_money": True,
    })
