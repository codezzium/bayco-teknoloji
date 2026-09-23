"""Stok formları.

Tasarım sistemi sınıflarını uygulayan mevcut soyutlama yeniden kullanılır
(apps.dashboard.forms.StyledModelForm); MoneyAwareModelForm onun üzerine para
alanlarını yetkisiz kullanıcıdan tamamen kaldıran katmanı ekler.
"""

from django import forms
from django.urls import reverse

from apps.catalog.models import Brand
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

DATE = forms.DateInput(attrs={"type": "date"})       # mobilde yerel tarih seçici
DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"})


def _simple_create(key: str) -> str:
    return reverse("stock:simple_create", kwargs={"key": key})


def _brand_create() -> str:
    return reverse("dashboard:crud_create", kwargs={"key": "markalar"})


class DeviceForm(MoneyAwareModelForm):
    MONEY_FIELDS = ["purchase_price"]

    class Meta:
        model = Device
        fields = [
            "device_model", "condition", "imei1", "imei2", "serial_no",
            "storage", "color", "battery_health", "has_box", "has_invoice",
            "shelf", "defect_note",
            "supplier", "purchase_date", "purchase_price",
            "list_price", "warranty_months", "warranty_start",
        ]
        widgets = {
            "purchase_date": DATE,
            "warranty_start": DATE,
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
        self.fields["device_model"].help_text = define_link(
            _simple_create("modeller"),
            self.back_url or reverse("stock:device_create"),
            "model",
        )
        self.fields["supplier"].queryset = Contact.objects.filter(is_supplier=True)
        self.fields["supplier"].empty_label = "— Tedarikçi seçin —"
        self.fields["warranty_start"].help_text = (
            "Boş bırakılırsa satış günü otomatik atanır. İkinci elde üreticinin "
            "kalan garantisi devrediliyorsa cihazın ilk alım tarihini girin."
        )


class AccessoryForm(MoneyAwareModelForm):
    MONEY_FIELDS = ["cost"]

    #: Yalnızca yeni kayıtta gösterilir; kaydedildikten sonra stok değişimi
    #: hareket defteri üzerinden yapılır (doğrudan adet düzenlenemez).
    opening_qty = forms.IntegerField(
        label="Açılış Stoğu (adet)", min_value=0, max_value=MAX_QTY, required=False,
        initial=0,
        help_text="Elinizdeki mevcut adet. Sonradan 'Stok Girişi' ekranından eklenir.",
    )

    class Meta:
        model = Accessory
        fields = [
            "name", "variant", "brand", "category", "barcode",
            "cost", "price", "min_stock_level", "note", "is_active",
        ]
        widgets = {
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


class DeviceModelForm(MoneyAwareModelForm):
    class Meta:
        model = DeviceModel
        fields = ["brand", "name", "kind", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["brand"].empty_label = "— Marka seçin —"
        self.fields["brand"].help_text = define_link(
            _brand_create(),
            self.back_url or _simple_create("modeller"),
            "marka",
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
        widgets = {"paid_at": DATETIME}


class StockIntakeForm(forms.Form):
    """Aksesuar mal girişi — doğrudan adet düzenlemek yerine hareket yazar."""

    quantity = forms.IntegerField(label="Giren Adet", min_value=1, max_value=MAX_QTY,
                                  initial=1)
    unit_cost = forms.DecimalField(label="Birim Alış (₺)", max_digits=12,
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
                                     max_value=MAX_QTY)
    note = forms.CharField(label="Not", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.dashboard.forms import _style
        _style(self.fields)
