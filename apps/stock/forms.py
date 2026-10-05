"""Stok formları.

Tasarım sistemi sınıflarını uygulayan mevcut soyutlama yeniden kullanılır
(apps.dashboard.forms.StyledModelForm); MoneyAwareModelForm onun üzerine para
alanlarını yetkisiz kullanıcıdan tamamen kaldıran katmanı ekler.
"""

from urllib.parse import urlencode

from django import forms
from django.urls import reverse
from django.utils.html import format_html

from apps.catalog.models import Brand
from apps.dashboard.forms import MoneyField, QtyInput, SearchableSelect
from apps.dashboard.utils import define_link

from .models import (
    Accessory,
    AccessoryCategory,
    Contact,
    Device,
    DeviceModel,
    Expense,
    Payment,
)
from .permissions import MoneyAwareModelForm
from .utils import MAX_QTY

# Mobilde yerel tarih seçici. `format` ŞART: tarayıcı type="date" değerini
# yalnızca ISO biçiminde kabul eder; Türkçe yerel biçimle ("30/09/2026")
# basılan varsayılan ve kayıtlı tarih boş görünür, form "zorunlu alan" der.
DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


def _simple_create(key: str) -> str:
    return reverse("stock:simple_create", kwargs={"key": key})


def _brand_create() -> str:
    return reverse("dashboard:crud_create", kwargs={"key": "markalar"})


class DeviceForm(MoneyAwareModelForm):
    MONEY_FIELDS = ["purchase_price"]
    PRICE_FIELDS = ["list_price"]

    class Meta:
        model = Device
        fields = [
            "device_model", "condition", "imei1", "imei2", "serial_no",
            "storage", "color", "battery_health", "has_box", "has_invoice",
            "shelf", "defect_note",
            "supplier", "purchase_date", "purchase_price",
            "list_price", "warranty_months", "warranty_start",
        ]
        field_classes = {"purchase_price": MoneyField, "list_price": MoneyField}
        widgets = {
            "device_model": SearchableSelect(),
            "supplier": SearchableSelect(hint="phone"),
            "purchase_date": DATE,
            # Tarih seçilince süre alanına 24 yazılır (stock/form.html).
            "warranty_start": forms.DateInput(
                attrs={"type": "date",
                       "data-warranty-months": Device.MANUFACTURER_WARRANTY_MONTHS},
                format="%Y-%m-%d"),
            "defect_note": forms.Textarea(attrs={"rows": 2}),
            "imei1": forms.TextInput(attrs={"inputmode": "numeric",
                                            "autocomplete": "off"}),
            "imei2": forms.TextInput(attrs={"inputmode": "numeric",
                                            "autocomplete": "off"}),
            "warranty_months": forms.NumberInput(attrs={"min": 0, "max": 120,
                                                        "list": "garanti-onerileri"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["device_model"].queryset = (
            DeviceModel.objects.filter(is_active=True).select_related("brand")
        )
        # Marka ayrı sorulmaz: DeviceModel zaten marka+model çiftidir ve
        # listede "Apple iPhone 13 Pro" olarak görünür. Serbest metin marka/
        # model alanları olsaydı "en çok satan model" raporu anlamsızlaşırdı.
        self.fields["device_model"].empty_label = "— Marka ve model seçin —"
        # Tüm cariler listelenir: telefonu bize satan çoğu zaman daha önce
        # müşterimiz olmuş biridir. Yalnızca tedarikçiler listelenseydi aynı
        # kişi için ikinci bir cari açılırdı. Seçilen cari kayıtta tedarikçi
        # olarak da işaretlenir (views.catalog.device_form).
        self.fields["supplier"].queryset = Contact.objects.all()
        self.fields["supplier"].empty_label = "— Kişi / firma seçin —"
        # "Listede yoksa ekle" pop-up'ta açılır (stock/partials/form_fields.html):
        # başka sayfaya gidilseydi forma girilen IMEI, fiyat vb. kaybolurdu.
        self._quick_add("device_model", reverse("stock:simple_quick",
                                                kwargs={"key": "modeller"}), "Model Ekle")
        self._quick_add("supplier", reverse("stock:contact_quick"), "Kişi Ekle")
        self.fields["warranty_start"].help_text = (
            "Boş bırakılırsa satış günü otomatik atanır. İkinci elde üreticinin "
            "garantisi devrediliyorsa cihazın ilk alım tarihini girin; süre 24 ay olur."
        )
        self.fields["warranty_months"].help_text = (
            "Başlangıç tarihinden itibaren toplam süre — kalan ay değil. "
            "Başlangıç boşsa satış gününden sayılır."
        )

    def clean(self):
        data = super().clean()
        # Tarih seçici JS'i çalışmadıysa süre 0 kalır ve bitiş tarihi hiç
        # hesaplanmaz. Kullanıcının elle yazdığı süreye ve tarihi bu formda
        # girilmemiş eski kayıtlara dokunulmaz.
        if ("warranty_start" in self.changed_data and data.get("warranty_start")
                and not data.get("warranty_months")):
            data["warranty_months"] = Device.MANUFACTURER_WARRANTY_MONTHS
        return data

    def _quick_add(self, name, url, label):
        # Pop-up, kaydettiği kaydı bu id'deki <select>'e ekleyip seçer.
        field_id = self.auto_id % self.add_prefix(name)
        self.fields[name].quick_add = {
            "url": f"{url}?{urlencode({'alan': field_id})}", "label": label,
        }


class AccessoryForm(MoneyAwareModelForm):
    MONEY_FIELDS = ["cost"]
    PRICE_FIELDS = ["price"]

    #: Yalnızca yeni kayıtta gösterilir; kaydedildikten sonra stok değişimi
    #: hareket defteri üzerinden yapılır (doğrudan adet düzenlenemez).
    opening_qty = forms.IntegerField(
        label="Açılış Stoğu (adet)", min_value=0, max_value=MAX_QTY, required=False,
        initial=0, widget=QtyInput,
        help_text="Elinizdeki mevcut adet. Sonradan 'Stok Girişi' ekranından eklenir.",
    )

    class Meta:
        model = Accessory
        fields = [
            "name", "variant", "brand", "category", "barcode",
            "cost", "price", "min_stock_level", "note", "is_active",
        ]
        field_classes = {"cost": MoneyField, "price": MoneyField}
        widgets = {
            "min_stock_level": QtyInput,
            "note": forms.Textarea(attrs={"rows": 2}),
            "barcode": forms.TextInput(attrs={"inputmode": "numeric",
                                              "autocomplete": "off",
                                              "data-scan-fill": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        back = self.back_url or reverse("stock:accessory_create")
        self.fields["brand"].queryset = Brand.objects.all()
        self.fields["brand"].empty_label = "— Marka seçin —"
        self.fields["brand"].help_text = define_link(_brand_create(), back, "marka")
        self.fields["category"].queryset = AccessoryCategory.objects.all()
        self.fields["category"].empty_label = "— Kategori seçin —"
        self.fields["category"].help_text = define_link(
            _simple_create("kategoriler"), back, "kategori")
        if self.instance.pk:
            self.fields.pop("opening_qty", None)
        # Barkodu olan kartta düğme yok: kodu değiştirmek basılı etiketleri
        # okunmaz yapar. Düğme alanı sunucudan önerilen kodla yeniden çizer.
        if not self.instance.barcode:
            self.fields["barcode"].help_text = format_html(
                'Ürünün barkodunu okutun. Barkodu yok mu? '
                '<button type="button" class="underline font-semibold" '
                'style="color:var(--ink)" hx-get="{}" hx-target="#{}" '
                'hx-swap="outerHTML">EAN-13 üret</button> — mağaza içi kod, '
                'mevcut barkodlarla çakışmaz.',
                # self["barcode"] burada KULLANILMAZ: BoundField help_text'i
                # oluştuğu anda kopyalar ve bu metin sayfaya hiç çıkmazdı.
                reverse("stock:accessory_barcode"),
                self.auto_id % self.add_prefix("barcode"),
            )


class DeviceModelForm(MoneyAwareModelForm):
    class Meta:
        model = DeviceModel
        fields = ["brand", "name", "kind", "is_active"]
        widgets = {"brand": SearchableSelect()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["brand"].empty_label = "— Marka seçin —"
        self.fields["brand"].help_text = define_link(
            _brand_create(),
            self.back_url or _simple_create("modeller"),
            "marka",
            new_tab=self.popup,
        )
        self.fields["name"].help_text = (
            "Yalnızca model adı — markayı tekrar yazmayın. Tek biçim kullanın: "
            "'iPhone 13 Pro'. Farklı yazımlar raporlarda ayrı ürün gibi görünür."
        )


class AccessoryCategoryForm(MoneyAwareModelForm):
    class Meta:
        model = AccessoryCategory
        fields = ["name", "order"]


class ContactForm(MoneyAwareModelForm):
    class Meta:
        model = Contact
        fields = ["full_name", "phone", "company", "email", "tax_no", "address",
                  "is_customer", "is_supplier", "note"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"inputmode": "tel",
                                            "autocomplete": "off"}),
        }

    def clean(self):
        data = super().clean()
        if not data.get("is_customer") and not data.get("is_supplier"):
            raise forms.ValidationError(
                "Cari en az bir role sahip olmalı: müşteri ve/veya tedarikçi."
            )
        return data


class ExpenseForm(MoneyAwareModelForm):
    class Meta:
        model = Expense
        fields = ["kind", "title", "amount", "spent_on", "device", "supplier", "note"]
        field_classes = {"amount": MoneyField}
        widgets = {"spent_on": DATE, "note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, device=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Contact.objects.all()
        self.fields["supplier"].empty_label = "— Ödenen yer (opsiyonel) —"
        if device is not None:
            # Cihaz detayından açıldı: yalnızca cihaza bağlanabilen türler
            self.fields["kind"].choices = [
                (k.value, k.label) for k in Expense.Kind if k in Expense.DEVICE_KINDS
            ]
            self.fields["device"].queryset = Device.objects.filter(pk=device.pk)
            self.fields["device"].initial = device
            self.fields["device"].widget = forms.HiddenInput()
        else:
            self.fields["device"].queryset = Device.objects.select_related(
                "device_model__brand")
            self.fields["device"].empty_label = "— Genel gider (cihaza bağlı değil) —"
            self.fields["device"].help_text = (
                "Kira/elektrik gibi genel giderleri bir cihaza bağlamayın; "
                "o cihazın kâr marjı bozulur."
            )

    def clean(self):
        data = super().clean()
        if data.get("device") and data.get("kind") not in Expense.DEVICE_KINDS:
            raise forms.ValidationError(
                "Bu gider türü bir cihaza bağlanamaz (genel işletme gideridir)."
            )
        return data


class PaymentForm(MoneyAwareModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "method", "kind", "paid_at", "note"]
        field_classes = {"amount": MoneyField}
        widgets = {"paid_at": DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .permissions import has_access

        # Para iadesi "Silme, iptal, iade" tikine bağlı. Seçenekten çıkarmak
        # elle POST edilen "iade"yi de geçersiz seçim yapar.
        if not has_access(self.user, "delete"):
            self.fields["kind"].choices = [
                choice for choice in self.fields["kind"].choices
                if choice[0] != Payment.Kind.IADE
            ]


class PersonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.get_full_name() or user.get_username()


class SellerChangeForm(forms.Form):
    """Satıcı değiştirme pop-up'ı (Satışlar listesi ve fiş sayfası).

    Ekip: panele girebilen aktif kullanıcılar, mevcut satıcı hariç. Kimin
    doğrudan değiştirip kimin onaya düşeceği services.request_seller_change'te.
    """

    to_user = PersonChoiceField(label="Yeni satıcı", queryset=None,
                                empty_label="Ekipten seçin…")
    reason = forms.CharField(
        label="Gerekçe", max_length=200,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Örn: Satışı Ayşe yaptı, kasada Mehmet'in oturumu açıktı.",
        }))

    def __init__(self, *args, sale, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.dashboard.forms import _style
        from apps.staff.notify import panel_users

        self.fields["to_user"].queryset = panel_users().exclude(pk=sale.cashier_id)
        _style(self.fields)


class StockIntakeForm(forms.Form):
    """Aksesuar mal girişi — doğrudan adet düzenlemek yerine hareket yazar."""

    quantity = forms.IntegerField(label="Giren Adet", min_value=1, max_value=MAX_QTY,
                                  initial=1, widget=QtyInput)
    unit_cost = MoneyField(label="Birim Alış (₺)", max_digits=12,
                           decimal_places=2, min_value=0, required=False)
    note = forms.CharField(label="Not", max_length=200, required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.dashboard.forms import _style
        from .permissions import can_see_money

        if not can_see_money(user):
            self.fields.pop("unit_cost", None)
        _style(self.fields)


class StocktakeForm(forms.Form):
    """Sayım — girilen değer hedef adettir, fark kadar hareket yazılır."""

    counted_qty = forms.IntegerField(label="Sayılan Adet", min_value=0,
                                     max_value=MAX_QTY, widget=QtyInput)
    note = forms.CharField(label="Not", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.dashboard.forms import _style
        _style(self.fields)
