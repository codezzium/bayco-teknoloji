"""Gider ekranları. Tümü money_required — Personel giderleri göremez."""

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import ExpenseForm
from ..models import Device, Expense
from ..utils import money
from .base import money_required, paginate, pick_template, querystring


@money_required
def expense_list(request):
    kind = request.GET.get("tur", "")
    scope = request.GET.get("kapsam", "")

    expenses = Expense.objects.select_related("device__device_model__brand",
                                              "supplier")
    if kind:
        expenses = expenses.filter(kind=kind)
    if scope == "cihaz":
        expenses = expenses.filter(device__isnull=False)
    elif scope == "genel":
        expenses = expenses.filter(device__isnull=True)

    total = money(expenses.aggregate(t=Sum("amount"))["t"])
    page = paginate(expenses, request)
    return render(request, pick_template(request, "stock/partials/expense_rows.html",
                                         "stock/expense_list.html"), {
        "active": "giderler", "title": "Giderler", "singular": "Gider",
        "page": page, "total": page.paginator.count, "amount_total": total,
        "tur": kind, "kapsam": scope, "qs": querystring(request),
        "kinds": Expense.Kind.choices,
        "create_url": reverse("stock:expense_create"),
    })


@money_required
def expense_form(request, pk=None):
    instance = get_object_or_404(Expense, pk=pk) if pk else None
    device = None
    device_id = request.GET.get("cihaz") or request.POST.get("device")
    if device_id and instance is None:
        device = Device.objects.filter(pk=device_id).first()

    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=instance, user=request.user,
                           device=device)
        if form.is_valid():
            expense = form.save(commit=False)
            if instance is None:
                expense.created_by = request.user
            expense.save()
            messages.success(request, "Gider kaydedildi.")
            if expense.device_id:
                return redirect("stock:device_detail", pk=expense.device_id)
            return redirect("stock:expense_list")
    else:
        initial = {"spent_on": timezone.localdate()}
        form = ExpenseForm(instance=instance, user=request.user, device=device,
                           initial=initial)

    return render(request, "stock/form.html", {
        "active": "giderler", "form": form, "title": "Giderler",
        "singular": "Gider", "is_edit": instance is not None,
        "back_url": (reverse("stock:device_detail", kwargs={"pk": device.pk})
                     if device else reverse("stock:expense_list")),
    })


@money_required
@require_POST
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    device_id = expense.device_id
    expense.delete()
    messages.success(request, "Gider silindi.")
    if request.headers.get("HX-Request"):
        return HttpResponse("")
    if device_id:
        return redirect("stock:device_detail", pk=device_id)
    return redirect("stock:expense_list")
