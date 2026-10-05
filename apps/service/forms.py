"""Teknik servis formları.

Stok formlarının soyutlamaları yeniden kullanılır: MoneyAwareModelForm para
alanlarını (teknik servis bedeli) Maliyet tiki olmayandan tamamen kaldırır,
SearchableSelect + quick_add Cari/Model pop-up'larını stock/form.html'de açar.
"""

from urllib.parse import urlencode

from django import forms
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from apps.dashboard.forms import MoneyField, SearchableSelect, _style
from apps.stock.forms import DATE, PersonChoiceField
from apps.stock.models import Contact, DeviceModel, Payment
from apps.stock.permissions import MoneyAwareModelForm, has_access

from .models import (
    RepairShop,
    RepairShopPayment,
    ServiceCost,
    ServiceOutsource,
    ServicePayment,
    ServiceTicket,
    parse_pattern,
    validate_pattern,
)

Status = ServiceTicket.Status


def _quick_add(form, name, url, label, **params):
    """Alanın yanına pop-up'ta kayıt ekleme düğmesi (stock/partials/form_fields.html)."""
    field_id = form.auto_id % form.add_prefix(name)
    form.fields[name].quick_add = {
        "url": f"{url}?{urlencode({'alan': field_id, **params})}", "label": label,
    }


def pattern_dots():
    """3×3 ızgaranın nokta merkezleri (SVG viewBox 0 0 300 300)."""
    return [{"n": n, "x": 50 + (n - 1) % 3 * 100, "y": 50 + (n - 1) // 3 * 100}
            for n in range(1, 10)]


class PatternWidget(forms.Widget):
    """Kilit ekranı deseni: 3×3 noktaya dokunarak/sürükleyerek çizilir.

    Değer gizli input'ta "1-5-9-6" biçiminde durur; etkileşim static/js/pattern.js
    (Alpine "baycoPattern"). JS çalışmazsa alan boş gider, form yine kaydolur.
    """

    wide = False

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        return render_to_string("service/partials/pattern_input.html", {
            "name": name, "value": "-".join(map(str, parse_pattern(value))),
            "id": attrs.get("id", f"id_{name}"), "dots": pattern_dots(),
        })


class ChipCheckboxes(forms.CheckboxSelectMultiple):
    """Çoklu seçim, tıklanabilir etiketler olarak (seçili olan .filter-chip.active görünümü)."""

    wide = True

    def render(self, name, value, attrs=None, renderer=None):
        selected = {str(v) for v in (value or [])}
        base_id = (attrs or {}).get("id", f"id_{name}")
        return format_html(
            '<div class="flex flex-wrap gap-2" id="{}">{}</div>', base_id,
            format_html_join("", (
                '<label class="filter-chip chip-check cursor-pointer select-none">'
                '<input type="checkbox" class="sr-only" name="{}" value="{}"{}> {}</label>'
            ), ((name, key, " checked" if str(key) in selected else "", label)
                for key, label in self.choices)),
        )


class TicketForm(MoneyAwareModelForm):
    received_items = forms.MultipleChoiceField(
        label="Teslim Alınan Aksesuarlar", required=False,
        choices=ServiceTicket.RECEIVED_ITEMS, widget=ChipCheckboxes)

    #: Yalnızca kabulde: kapora tahsilatı (ServicePayment olarak yazılır).
    deposit = MoneyField(label="Alınan Kapora (₺)", required=False, max_digits=12,
                         decimal_places=2, min_value=0,
                         help_text="Ön ödeme alındıysa. Kabul formunda ve fişte görünür.")
    deposit_method = forms.ChoiceField(label="Kapora Ödeme Şekli",
                                       choices=Payment.Method.choices,
                                       initial=Payment.Method.NAKIT)

    class Meta:
        model = ServiceTicket
        fields = [
            "customer", "device_model", "imei", "serial_no", "color", "technician",
            "received_items", "received_note", "condition_note", "complaint",
            "diagnosis", "lock_pin", "lock_pattern",
            "estimated_price", "estimated_ready", "final_price", "note",
        ]
        field_classes = {"estimated_price": MoneyField, "final_price": MoneyField,
                         "technician": PersonChoiceField}
        widgets = {
            "customer": SearchableSelect(hint="phone"),
            "device_model": SearchableSelect(),
            "lock_pattern": PatternWidget(),
            "estimated_ready": DATE,
            "condition_note": forms.Textarea(attrs={"rows": 2}),
            "complaint": forms.Textarea(attrs={"rows": 3}),
            "diagnosis": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 2}),
            "imei": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
            "lock_pin": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.staff.notify import panel_users

        self.fields["customer"].queryset = Contact.objects.all()
        self.fields["customer"].empty_label = "— Müşteri seçin —"
        self.fields["device_model"].queryset = (
            DeviceModel.objects.filter(is_active=True).select_related("brand"))
        self.fields["device_model"].empty_label = "— Marka ve model seçin —"
        self.fields["technician"].queryset = panel_users()
        self.fields["technician"].empty_label = "— Atanmadı —"
        _quick_add(self, "customer", reverse("stock:contact_quick"), "Kişi Ekle",
                   rol="musteri")
        _quick_add(self, "device_model",
                   reverse("stock:simple_quick", kwargs={"key": "modeller"}), "Model Ekle")
        self.fields["lock_pin"].help_text = (
            "Kabul formunun servis nüshasına basılır; cihaz teslim edilince silinir.")
        self.fields["lock_pattern"].help_text = (
            "Telefondaki gibi noktaları parmakla ya da fareyle birleştirin. "
            "Yeniden çizmek için baştan çizmeniz yeterli.")

        if self.instance.pk:
            self.fields.pop("deposit")
            self.fields.pop("deposit_method")
            if self.instance.is_closed:
                # Teslimde silinen kilit bilgisi kapanmış kayda geri yazılmasın.
                self.fields.pop("lock_pin")
                self.fields.pop("lock_pattern")
        else:
            # Kabulde henüz tespit ve kesin ücret yoktur.
            self.fields.pop("diagnosis")
            self.fields.pop("final_price")

    def clean_lock_pattern(self):
        value = "-".join(map(str, parse_pattern(self.cleaned_data.get("lock_pattern"))))
        validate_pattern(value)
        return value


class StatusForm(forms.Form):
    status = forms.ChoiceField(label="Yeni Durum", choices=[
        (s.value, s.label) for s in ServiceTicket.MANUAL_STATUSES])
    note = forms.CharField(label="Not", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class ServicePaymentForm(MoneyAwareModelForm):
    class Meta:
        model = ServicePayment
        fields = ["amount", "method", "kind", "note"]
        field_classes = {"amount": MoneyField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Para iadesi "Silme, iptal, iade" tikine bağlı (kasadaki PaymentForm gibi).
        if not has_access(self.user, "delete"):
            self.fields["kind"].choices = [c for c in self.fields["kind"].choices
                                           if c[0] != Payment.Kind.IADE]


class CostForm(MoneyAwareModelForm):
    class Meta:
        model = ServiceCost
        fields = ["kind", "title", "amount", "spent_on"]
        field_classes = {"amount": MoneyField}
        widgets = {"spent_on": DATE}


class SendForm(MoneyAwareModelForm):
    """Teknik servise gönderme. Bedel Maliyet tikine bağlıdır."""

    MONEY_FIELDS = ["cost"]

    class Meta:
        model = ServiceOutsource
        fields = ["shop", "work", "cost", "sent_at", "note"]
        field_classes = {"cost": MoneyField}
        widgets = {"sent_at": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shop"].queryset = RepairShop.objects.filter(is_active=True)
        self.fields["shop"].empty_label = "— Teknik servis seçin —"
        if "cost" in self.fields:
            self.fields["cost"].label = "Anlaşılan Bedel (₺)"
            self.fields["cost"].help_text = "Biliniyorsa. Dönüşte kesinleştirilir."


class ReturnForm(forms.Form):
    next_status = forms.ChoiceField(label="Cihazın Durumu", choices=[
        (Status.HAZIR.value, "Tamir edildi — Teslime Hazır"),
        (Status.TAMIRDE.value, "Tamirde (mağazada devam)"),
        (Status.INCELEME.value, "Tamir edilemedi — Arıza Tespiti"),
    ])
    cost = MoneyField(label="Teknik Servis Bedeli (₺)", required=False, max_digits=12,
                      decimal_places=2, min_value=0,
                      help_text="Teknik servise borç olarak yazılır. Ücretsizse boş bırakın.")
    returned_at = forms.DateField(label="Dönüş Tarihi", widget=DATE)
    note = forms.CharField(label="Not", max_length=200, required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.stock.permissions import can_see_money

        if not can_see_money(user):
            self.fields.pop("cost")
        _style(self.fields)


class JobCostForm(forms.Form):
    cost = MoneyField(label="Teknik Servis Bedeli (₺)", required=False, max_digits=12,
                      decimal_places=2, min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class CloseForm(forms.Form):
    outcome = forms.ChoiceField(label="Sonuç", choices=[
        (Status.TESLIM.value, "Tamir edildi — Teslim Edildi"),
        (Status.IADE.value, "Tamirsiz İade"),
    ])
    final_price = MoneyField(label="Servis Ücreti (₺)", required=False, max_digits=12,
                             decimal_places=2, min_value=0,
                             help_text="Müşteriden alınacak toplam. Tamirsiz iadede "
                                       "inceleme ücreti yoksa boş bırakın.")
    payment = MoneyField(label="Şimdi Tahsil Edilen (₺)", required=False, max_digits=12,
                         decimal_places=2, min_value=0)
    method = forms.ChoiceField(label="Ödeme Şekli", choices=Payment.Method.choices)
    note = forms.CharField(label="Not", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)

    def clean(self):
        data = super().clean()
        if data.get("outcome") == Status.TESLIM and data.get("final_price") is None:
            self.add_error("final_price", "Teslim için servis ücretini girin (ücretsizse 0).")
        return data


class ShopForm(MoneyAwareModelForm):
    class Meta:
        model = RepairShop
        fields = ["name", "contact_name", "phone", "address", "iban", "note", "is_active"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"}),
        }


class ShopPaymentForm(MoneyAwareModelForm):
    class Meta:
        model = RepairShopPayment
        fields = ["amount", "method", "paid_at", "outsource", "note"]
        field_classes = {"amount": MoneyField}
        widgets = {"paid_at": DATE}

    def __init__(self, *args, shop=None, **kwargs):
        super().__init__(*args, **kwargs)
        jobs = ServiceOutsource.objects.none()
        if shop is not None:
            jobs = (shop.jobs.filter(status=ServiceOutsource.Status.DONDU)
                    .select_related("ticket__device_model__brand"))
        self.fields["outsource"].queryset = jobs
        self.fields["outsource"].empty_label = "— Genel ödeme (işe bağlı değil) —"
        self.fields["outsource"].required = False
