"""Cari (müşteri/tedarikçi) ekranları.

"Cariler" tiki listeyi, detayı (bakiyeler) ve düzenlemeyi açar. YENİ cari
eklemek herkese açıktır: kasadaki "+ Yeni Müşteri" veresiye satış için
gereklidir. Tiki olmayan kullanıcı kayıttan sonra kasaya döner, cari
detayına değil.
"""

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..forms import ContactForm
from ..models import Contact
from ..utils import trfold
from .base import (
    access_required,
    created_response,
    deny,
    has_access,
    paginate,
    panel_required,
    pick_template,
    querystring,
    quick_target,
    safe_next,
)


def _same_phone(raw_phone):
    """Aynı telefonla kayıtlı ilk cari (yoksa None).

    Telefonda unique kısıtı YOKTUR — aile bireyleri aynı numarayı paylaşır ve
    kısıt gerçek bir satışı bloke ederdi. Bunun yerine kullanıcıyı uyarırız.
    """
    from apps.leads.utils import normalize_tr
    phone = normalize_tr(raw_phone or "")
    return Contact.objects.filter(phone_norm=phone).first() if phone else None


@access_required("contacts")
def contact_list(request):
    query = request.GET.get("q", "").strip()
    role = request.GET.get("rol", "")

    contacts = Contact.objects.all()
    if query:
        contacts = contacts.filter(search_blob__contains=trfold(query))
    if role == "musteri":
        contacts = contacts.filter(is_customer=True)
    elif role == "tedarikci":
        contacts = contacts.filter(is_supplier=True)

    page = paginate(contacts, request)
    return render(request, pick_template(request, "stock/partials/contact_rows.html",
                                         "stock/contact_list.html"), {
        "active": "cariler", "title": "Cariler", "singular": "Cari",
        "page": page, "total": page.paginator.count,
        "q": query, "rol": role, "qs": querystring(request),
        "create_url": reverse("stock:contact_create"),
    })


@access_required("contacts")
def contact_detail(request, pk):
    from django.db.models import F, Sum

    from ..models import Sale
    from ..utils import money

    contact = get_object_or_404(Contact, pk=pk)
    open_sales = contact.sales.filter(status=Sale.Status.TAMAMLANDI,
                                      payable_total__gt=F("paid_total"))
    balance = money(open_sales.aggregate(
        t=Sum(F("payable_total") - F("paid_total")))["t"])
    return render(request, "stock/contact_detail.html", {
        "active": "cariler",
        "contact": contact,
        "sales": contact.sales.prefetch_related("items")[:30],
        "supplied": contact.supplied_devices.select_related(
            "device_model__brand")[:30],
        "bought": contact.bought_devices.select_related("device_model__brand")[:30],
        "open_sales": open_sales,
        "balance": balance,
    })


@panel_required
def contact_form(request, pk=None):
    can_browse = has_access(request.user, "contacts")
    if pk and not can_browse:
        return deny(request)
    instance = get_object_or_404(Contact, pk=pk) if pk else None
    duplicate = None

    next_url = safe_next(request)

    if request.method == "POST":
        form = ContactForm(request.POST, instance=instance, user=request.user)
        if form.is_valid():
            contact = form.save()
            messages.success(request, f"{contact.full_name} kaydedildi.")
            if next_url:
                from .. import cart as cart_utils
                cart = cart_utils.get_cart(request)
                cart["customer_id"] = contact.pk
                cart_utils.save_cart(request, cart)
                return redirect(next_url)
            if not can_browse:
                return redirect("stock:pos")
            return redirect("stock:contact_detail", pk=contact.pk)
    else:
        form = ContactForm(instance=instance, user=request.user)

    if instance is None and request.method == "POST":
        duplicate = _same_phone(request.POST.get("phone"))

    return render(request, "stock/form.html", {
        "active": "cariler", "form": form, "title": "Cariler",
        "singular": "Cari", "is_edit": instance is not None,
        "duplicate": duplicate,
        "next_url": next_url,
        "back_url": (next_url or
                     (reverse("stock:contact_detail", kwargs={"pk": instance.pk})
                      if instance else reverse("stock:contact_list" if can_browse
                                               else "stock:pos"))),
    })


@panel_required
def contact_quick(request):
    """Cihaz formundaki "+ Kişi Ekle" pop-up'ı (stock/partials/quick_form.html).

    contact_form'la aynı form ve aynı yetki (yeni cari herkese açık); fark,
    sayfadan hiç çıkılmamasıdır: kayıttan sonra yönlendirme yerine yeni cari
    çağıran formun seçim kutusuna eklenip seçilir (created_response). Böylece
    arkadaki cihaz formuna girilmiş hiçbir değer kaybolmaz. Kasa sepetine
    dokunmaz.

    Aynı telefonla kayıtlı cari varsa ilk kayıt denemesi durur ve mevcut kaydı
    seçme önerilir; kullanıcı yine de kaydederse o numara için bir daha
    sorulmaz (gizli `confirm_phone`).
    """
    field_id = quick_target(request, "id_supplier")
    duplicate = None
    if request.method == "POST":
        form = ContactForm(request.POST, user=request.user, auto_id="quick_%s", popup=True)
        if form.is_valid():
            phone = form.cleaned_data.get("phone", "")
            if request.POST.get("confirm_phone") != phone:
                duplicate = _same_phone(phone)
            if duplicate is None:
                contact = form.save()
                request.audit = {"target": contact, "invalid": False, "target_url": reverse(
                    "stock:contact_detail", kwargs={"pk": contact.pk})}
                return created_response(field_id, contact, search=contact.search_blob,
                                        hint=contact.phone)
        # htmx pop-up'ı hatada da 200 döner; kayıt "eklendi" diye loglanmasın.
        request.audit = {"invalid": True}
    else:
        # Tedarikçi rolü işaretli gelir: cihaz formundan eklenen kişi bize mal satandır.
        form = ContactForm(user=request.user, initial={"is_supplier": True},
                           auto_id="quick_%s", popup=True)
    return render(request, "stock/partials/quick_form.html", {
        "form": form, "title": "Yeni Cari", "field_id": field_id,
        "duplicate": duplicate,
    })


@access_required("delete")
@require_POST
def contact_delete(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if (contact.sales.exists() or contact.supplied_devices.exists()
            or contact.bought_devices.exists()):
        messages.error(
            request,
            "Bu cariye bağlı satış/cihaz kaydı var; silinemez. "
            "Kaydı düzenleyebilir veya notunu güncelleyebilirsiniz.",
        )
        return redirect("stock:contact_detail", pk=pk)
    name = contact.full_name
    contact.delete()
    messages.success(request, f"{name} silindi.")
    if request.headers.get("HX-Request"):
        return HttpResponse("")
    return redirect("stock:contact_list")
