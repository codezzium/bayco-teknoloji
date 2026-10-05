"""Teknik servis ekranları.

Tümü "Teknik Servis" tikine bağlıdır. İç maliyet, teknik servis bedeli, kâr ve
teknik servis ekstresi ayrıca "Maliyet ve kâr" tikini ister; silme/yeniden açma
"Silme, iptal, iade" tikini.
"""

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.sitecore.models import SiteSettings
from apps.stock.models import Contact
from apps.stock.niimbot import to_png
from apps.stock.pos58 import height_mm
from apps.stock.utils import money, trfold
from apps.stock.views.base import (
    access_required,
    can_see_money,
    paginate,
    pick_template,
    querystring,
    safe_next,
)

from . import reports as rpt
from . import services
from .forms import (
    CloseForm,
    CostForm,
    JobCostForm,
    ReturnForm,
    SendForm,
    ServicePaymentForm,
    ShopForm,
    ShopPaymentForm,
    StatusForm,
    TicketForm,
    pattern_dots,
)
from .models import (
    RepairShop,
    RepairShopPayment,
    ServiceCost,
    ServiceOutsource,
    ServiceTicket,
)
from .pdf import intake_pdf
from .slip import slip_image

Status = ServiceTicket.Status

#: Liste filtreleri: ?durum=<anahtar>. Varsayılan "acik".
FILTERS = {
    "acik": ("Açık", ServiceTicket.OPEN_STATUSES),
    Status.KABUL.value: (Status.KABUL.label, [Status.KABUL]),
    Status.INCELEME.value: (Status.INCELEME.label, [Status.INCELEME]),
    Status.ONAY.value: ("Onay Bekliyor", [Status.ONAY]),
    Status.TAMIRDE.value: (Status.TAMIRDE.label, [Status.TAMIRDE]),
    Status.DIS_SERVISTE.value: (Status.DIS_SERVISTE.label, [Status.DIS_SERVISTE]),
    Status.HAZIR.value: (Status.HAZIR.label, [Status.HAZIR]),
    "kapali": ("Kapanan", ServiceTicket.CLOSED_STATUSES),
    "tumu": ("Tümü", None),
}


def _detail(ticket):
    return redirect("service:ticket_detail", pk=ticket.pk)


def _form_errors(request, form, fallback="Bilgiler geçersiz."):
    errors = [str(e) for errs in form.errors.values() for e in errs]
    messages.error(request, errors[0] if errors else fallback)


def whatsapp_url(ticket, site) -> str:
    """Müşteriye WhatsApp bilgilendirmesi (hazır ise teslim çağrısı)."""
    from urllib.parse import quote

    from apps.leads.utils import customer_wa
    from apps.stock.templatetags.stock_extras import tl

    if not ticket.customer.phone:
        return ""
    name = ticket.customer.full_name.split()[0] if ticket.customer.full_name else ""
    if ticket.status == Status.HAZIR:
        text = (f"Merhaba {name}, {ticket.ticket_no} numaralı servis kaydınızdaki "
                f"{ticket.device_model} cihazınız teslime hazırdır.")
        price = ticket.final_price if ticket.final_price is not None else ticket.estimated_price
        if price is not None:
            text += f" Servis ücreti: {tl(price)}."
        text += " Servis fişinizle mağazamızdan teslim alabilirsiniz."
    else:
        text = (f"Merhaba {name}, {ticket.ticket_no} numaralı servis kaydınızdaki "
                f"{ticket.device_model} cihazınızın durumu: {ticket.get_status_display()}.")
    text += f" — {site.brand_name}"
    return f"{customer_wa(ticket.customer.phone)}?text={quote(text)}"


def pattern_preview(points) -> dict:
    """Detay sayfasındaki salt okunur desen (pattern_input.html ile aynı ızgara)."""
    dots = pattern_dots()
    for dot in dots:
        dot["order"] = points.index(dot["n"]) + 1 if dot["n"] in points else None
    line = " ".join(f"{dots[n - 1]['x']},{dots[n - 1]['y']}" for n in points)
    return {"dots": dots, "line": line, "start": dots[points[0] - 1] if points else None}


# ===========================================================================
# Servis kayıtları
# ===========================================================================

@access_required("service")
def ticket_list(request):
    query = request.GET.get("q", "").strip()
    state = request.GET.get("durum", "acik")
    if state not in FILTERS:
        state = "acik"

    tickets = ServiceTicket.objects.select_related("customer", "device_model__brand",
                                                   "technician")
    statuses = FILTERS[state][1]
    if statuses is not None:
        tickets = tickets.filter(status__in=statuses)
    if query:
        folded = trfold(query)
        tickets = tickets.filter(Q(search_blob__contains=folded)
                                 | Q(customer__search_blob__contains=folded))

    page = paginate(tickets, request)
    counts = rpt.open_counts()
    chips = [{"key": key, "label": label,
              "count": counts["open"] if key == "acik" else counts["by_status"].get(key)}
             for key, (label, _) in FILTERS.items()]
    return render(request, pick_template(request, "service/partials/ticket_rows.html",
                                         "service/ticket_list.html"), {
        "active": "servis", "title": "Servis Kayıtları", "singular": "Servis Kaydı",
        "page": page, "total": page.paginator.count, "q": query, "durum": state,
        "chips": chips, "counts": counts, "qs": querystring(request),
        "today": timezone.localdate(),
        "create_url": reverse("service:ticket_create"),
    })


@access_required("service")
def ticket_form(request, pk=None):
    instance = get_object_or_404(ServiceTicket, pk=pk) if pk else None

    if request.method == "POST":
        form = TicketForm(request.POST, instance=instance, user=request.user)
        if form.is_valid():
            ticket = form.save(commit=False)
            # Tedarikçi olarak açılmış biri tamire cihaz getirdiyse artık müşteridir.
            Contact.objects.filter(pk=ticket.customer_id, is_customer=False).update(
                is_customer=True)
            if instance is None:
                services.create_ticket(
                    ticket, user=request.user,
                    deposit=form.cleaned_data.get("deposit"),
                    deposit_method=form.cleaned_data.get("deposit_method") or "nakit")
                messages.success(request, f"{ticket.ticket_no} açıldı. Kabul formunu "
                                          "ve servis fişini yazdırabilirsiniz.")
                url = reverse("service:ticket_detail", kwargs={"pk": ticket.pk})
                return redirect(f"{url}?yeni=1")
            ticket.save()
            messages.success(request, f"{ticket.ticket_no} güncellendi.")
            return _detail(ticket)
    else:
        form = TicketForm(instance=instance, user=request.user)

    return render(request, "stock/form.html", {
        "active": "servis", "form": form, "title": "Servis Kayıtları",
        "singular": "Servis Kaydı", "is_edit": instance is not None, "guard": True,
        "back_url": (reverse("service:ticket_detail", kwargs={"pk": instance.pk})
                     if instance else reverse("service:ticket_list")),
    })


@access_required("service")
def ticket_detail(request, pk):
    ticket = get_object_or_404(
        ServiceTicket.objects.select_related("customer", "device_model__brand",
                                             "technician", "created_by"), pk=pk)
    user = request.user
    show_money = can_see_money(user)
    jobs = list(ticket.outsources.select_related("shop").order_by("sent_at", "id"))
    active_job = next((job for job in jobs
                       if job.status == ServiceOutsource.Status.GONDERILDI), None)
    today = timezone.localdate()

    close_price = ticket.final_price if ticket.final_price is not None else ticket.estimated_price
    close_due = (close_price - ticket.paid_total) if close_price is not None else None

    context = {
        "active": "servis",
        "ticket": ticket,
        "logs": ticket.status_logs.select_related("created_by"),
        "payments": ticket.payments.select_related("created_by").order_by("paid_at", "id"),
        "jobs": jobs,
        "active_job": active_job,
        "pattern": pattern_preview(ticket.pattern_points),
        "show_money": show_money,
        "is_new": request.GET.get("yeni") == "1",
        "status_form": StatusForm(initial={
            "status": ticket.status if ticket.status in ServiceTicket.MANUAL_STATUSES
            else Status.TAMIRDE}),
        # Tutar önceden doldurulmaz: kapora/ara ödeme kasada elle girilir; dolu
        # gelen alan yanlışlıkla bütün kalanın tahsil edilmesine yol açardı.
        "payment_form": ServicePaymentForm(user=user),
        "close_form": CloseForm(initial={
            "outcome": Status.TESLIM, "final_price": close_price,
            "payment": close_due if close_due and close_due > 0 else None}),
        "send_form": SendForm(user=user, initial={"sent_at": today}),
        "return_form": ReturnForm(user=user, initial={
            "returned_at": today, "next_status": Status.HAZIR,
            "cost": active_job.cost if active_job else None}),
        "has_shops": RepairShop.objects.filter(is_active=True).exists(),
        "wa_url": whatsapp_url(ticket, SiteSettings.load()),
    }
    if show_money:
        internal, external = ticket.internal_cost, ticket.external_cost
        context.update({
            "costs": ticket.costs.select_related("created_by"),
            "cost_form": CostForm(user=user, initial={"spent_on": today}),
            "internal_cost": internal,
            "external_cost": external,
            "profit": (ticket.final_price - internal - external
                       if ticket.final_price is not None else None),
        })
    return render(request, "service/ticket_detail.html", context)


@access_required("service")
@require_POST
def ticket_status(request, pk):
    ticket = get_object_or_404(ServiceTicket, pk=pk)
    form = StatusForm(request.POST)
    if form.is_valid():
        try:
            services.set_status(ticket, form.cleaned_data["status"], user=request.user,
                                note=form.cleaned_data["note"])
            messages.success(request, "Durum güncellendi.")
        except services.ServiceError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form)
    return _detail(ticket)


@access_required("service")
@require_POST
def ticket_payment(request, pk):
    ticket = get_object_or_404(ServiceTicket, pk=pk)
    form = ServicePaymentForm(request.POST, user=request.user)
    if form.is_valid():
        data = form.cleaned_data
        try:
            services.record_payment(ticket, data["amount"], method=data["method"],
                                    kind=data["kind"], user=request.user,
                                    note=data.get("note", ""))
            messages.success(request, "Ödeme kaydedildi.")
        except services.ServiceError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form, "Ödeme bilgileri geçersiz.")
    return _detail(ticket)


@access_required("service")
@require_POST
def ticket_close(request, pk):
    ticket = get_object_or_404(ServiceTicket, pk=pk)
    form = CloseForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            services.close_ticket(ticket, outcome=data["outcome"],
                                  final_price=data.get("final_price"),
                                  payment=data.get("payment"), method=data["method"],
                                  user=request.user, note=data.get("note", ""))
            messages.success(request, f"{ticket.ticket_no} kapatıldı. Teslim fişini "
                                      "yazdırabilirsiniz.")
        except services.ServiceError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form)
    return _detail(ticket)


@access_required("service", "delete")
@require_POST
def ticket_reopen(request, pk):
    ticket = get_object_or_404(ServiceTicket, pk=pk)
    try:
        services.reopen_ticket(ticket, user=request.user,
                               note=request.POST.get("note", ""))
        messages.success(request, "Kayıt yeniden açıldı (Teslime Hazır).")
    except services.ServiceError as exc:
        messages.error(request, str(exc))
    return _detail(ticket)


@access_required("service", "delete")
@require_POST
def ticket_delete(request, pk):
    ticket = get_object_or_404(ServiceTicket, pk=pk)
    number = ticket.ticket_no
    try:
        services.delete_ticket(ticket)
    except services.ServiceError as exc:
        messages.error(request, str(exc))
        return _detail(ticket)
    messages.success(request, f"{number} silindi.")
    return redirect("service:ticket_list")


# ---------------------------------------------------------------------------
# Belgeler
# ---------------------------------------------------------------------------

@access_required("service")
def ticket_pdf(request, pk):
    ticket = get_object_or_404(
        ServiceTicket.objects.select_related("customer", "device_model__brand",
                                             "created_by"), pk=pk)
    response = HttpResponse(intake_pdf(ticket), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{ticket.ticket_no}.pdf"'
    # Servis nüshasında ekran parolası var: tarayıcı/vekil önbelleğinde kalmasın.
    response["Cache-Control"] = "no-store"
    return response


@access_required("service")
def ticket_slip(request, pk):
    ticket = get_object_or_404(ServiceTicket.objects.select_related("customer"), pk=pk)
    return render(request, "stock/receipt.html", {
        "doc_title": f"Servis Fişi {ticket.ticket_no}",
        "png_url": reverse("service:ticket_slip_png", kwargs={"pk": ticket.pk}),
        "back_url": reverse("service:ticket_detail", kwargs={"pk": ticket.pk}),
        "height_mm": f"{height_mm(slip_image(ticket)):.1f}",
        "auto": request.GET.get("auto") == "1",
    })


@access_required("service")
def ticket_slip_png(request, pk):
    ticket = get_object_or_404(ServiceTicket.objects.select_related("customer"), pk=pk)
    return HttpResponse(to_png(slip_image(ticket)), content_type="image/png")


# ---------------------------------------------------------------------------
# İç maliyet
# ---------------------------------------------------------------------------

@access_required("service", "money")
@require_POST
def cost_add(request, pk):
    ticket = get_object_or_404(ServiceTicket, pk=pk)
    form = CostForm(request.POST, user=request.user)
    if form.is_valid():
        services.add_cost(ticket, form.save(commit=False), user=request.user)
        messages.success(request, "Maliyet eklendi.")
    else:
        _form_errors(request, form, "Maliyet bilgileri geçersiz.")
    return _detail(ticket)


@access_required("service", "money", "delete")
@require_POST
def cost_delete(request, pk):
    cost = get_object_or_404(ServiceCost, pk=pk)
    ticket = cost.ticket
    cost.delete()
    messages.success(request, "Maliyet silindi.")
    return _detail(ticket)


# ---------------------------------------------------------------------------
# Teknik servise gönderme / dönüş
# ---------------------------------------------------------------------------

@access_required("service")
@require_POST
def outsource_send(request, pk):
    ticket = get_object_or_404(ServiceTicket, pk=pk)
    form = SendForm(request.POST, user=request.user)
    if form.is_valid():
        try:
            job = services.send_to_shop(ticket, form.save(commit=False), user=request.user)
            messages.success(request, f"Cihaz {job.shop} teknik servisine gönderildi.")
        except services.ServiceError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form, "Gönderim bilgileri geçersiz.")
    return _detail(ticket)


@access_required("service")
@require_POST
def outsource_return(request, pk):
    job = get_object_or_404(ServiceOutsource.objects.select_related("ticket", "shop"), pk=pk)
    form = ReturnForm(request.POST, user=request.user)
    if form.is_valid():
        data = form.cleaned_data
        try:
            services.return_from_shop(job, next_status=data["next_status"],
                                      cost=data.get("cost"),
                                      update_cost="cost" in form.fields,
                                      returned_at=data["returned_at"], user=request.user,
                                      note=data.get("note", ""))
            messages.success(request, f"Cihazın {job.shop} teknik servisinden dönüşü kaydedildi.")
        except services.ServiceError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form, "Dönüş bilgileri geçersiz.")
    return _detail(job.ticket)


@access_required("service", "money")
@require_POST
def outsource_cost(request, pk):
    job = get_object_or_404(ServiceOutsource.objects.select_related("ticket"), pk=pk)
    form = JobCostForm(request.POST)
    if form.is_valid():
        try:
            services.set_job_cost(job, form.cleaned_data.get("cost"))
            messages.success(request, "Teknik servis bedeli güncellendi.")
        except services.ServiceError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form)
    return redirect(safe_next(request) or reverse("service:ticket_detail",
                                                  kwargs={"pk": job.ticket_id}))


@access_required("service")
@require_POST
def outsource_cancel(request, pk):
    job = get_object_or_404(ServiceOutsource.objects.select_related("ticket", "shop"), pk=pk)
    try:
        services.cancel_outsource(job, user=request.user)
        messages.success(request, "Teknik servis gönderimi iptal edildi; cihaz Tamirde.")
    except services.ServiceError as exc:
        messages.error(request, str(exc))
    return _detail(job.ticket)


# ===========================================================================
# Teknik Servisler
# ===========================================================================

@access_required("service", "money")
def shop_list(request):
    rows = rpt.shop_balances(RepairShop.objects.all())
    return render(request, "service/shop_list.html", {
        "active": "teknik_servisler", "title": "Teknik Servisler", "singular": "Teknik Servis",
        "rows": rows, "total": len(rows),
        "debt_total": sum((row["balance"] for row in rows), money(0)),
        "create_url": reverse("service:shop_create"),
    })


@access_required("service")
def shop_form(request, pk=None):
    """Teknik servis ekle/düzenle. Maliyet tiki olmayan personel de ekleyebilir
    (cihazı göndereceği yer listede yoksa); ekstreyi göremez."""
    instance = get_object_or_404(RepairShop, pk=pk) if pk else None
    next_url = safe_next(request)
    show_money = can_see_money(request.user)

    if request.method == "POST":
        form = ShopForm(request.POST, instance=instance, user=request.user)
        if form.is_valid():
            shop = form.save()
            messages.success(request, f"{shop.name} kaydedildi.")
            if next_url:
                return redirect(next_url)
            if show_money:
                return redirect("service:shop_detail", pk=shop.pk)
            return redirect("service:ticket_list")
    else:
        form = ShopForm(instance=instance, user=request.user)

    if next_url:
        back = next_url
    elif instance and show_money:
        back = reverse("service:shop_detail", kwargs={"pk": instance.pk})
    else:
        back = reverse("service:shop_list" if show_money else "service:ticket_list")
    return render(request, "stock/form.html", {
        "active": "teknik_servisler", "form": form, "title": "Teknik Servisler",
        "singular": "Teknik Servis", "is_edit": instance is not None,
        "next_url": next_url, "back_url": back,
    })


@access_required("service", "money")
def shop_detail(request, pk):
    shop = get_object_or_404(RepairShop, pk=pk)
    summary = rpt.shop_balances([shop])[0]
    return render(request, "service/shop_detail.html", {
        "active": "teknik_servisler",
        "shop": shop,
        "summary": summary,
        "statement": rpt.shop_statement(shop),
        "at_shop": (shop.jobs.filter(status=ServiceOutsource.Status.GONDERILDI)
                    .select_related("ticket__customer", "ticket__device_model__brand")),
        "payment_form": ShopPaymentForm(user=request.user, shop=shop, initial={
            "paid_at": timezone.localdate(),
            "amount": summary["balance"] if summary["balance"] > 0 else None}),
    })


@access_required("service", "money")
@require_POST
def shop_payment(request, pk):
    shop = get_object_or_404(RepairShop, pk=pk)
    form = ShopPaymentForm(request.POST, user=request.user, shop=shop)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.shop = shop
        try:
            services.pay_shop(payment, user=request.user)
            messages.success(request, "Teknik servis ödemesi kaydedildi.")
        except services.ServiceError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form, "Ödeme bilgileri geçersiz.")
    return redirect("service:shop_detail", pk=shop.pk)


@access_required("service", "money", "delete")
@require_POST
def shop_payment_delete(request, pk):
    payment = get_object_or_404(RepairShopPayment, pk=pk)
    shop_id = payment.shop_id
    payment.delete()
    messages.success(request, "Teknik servis ödemesi silindi.")
    return redirect("service:shop_detail", pk=shop_id)
