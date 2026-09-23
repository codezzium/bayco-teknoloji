"""Stok & satış veri modeli.

Temel ayrım: CİHAZ seri takiplidir (1 satır = 1 fiziksel telefon, IMEI tekil,
kâr birim başına), AKSESUAR adet takiplidir (1 satır = 1 ürün tipi + stok
adedi). Bu ikisi tek modelde birleştirilemez.

Mutasyon kuralı: stok adedi, cihaz durumu ve fiş toplamları YALNIZCA
apps/stock/services.py içinden değiştirilir. Buradaki save() metodları sadece
türetilmiş alanları (kod, garanti bitişi, arama metni) doldurur.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Case, F, Q, Sum, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from .utils import add_months, digits_only, money, next_code, trfold

# Saklanan para alanları; hesaplanan/toplam sütunlar için 14 hane kullanılır
# (adet × fiyat taşması olmasın diye).
MONEY = {"max_digits": 12, "decimal_places": 2}
DEC = models.DecimalField(max_digits=14, decimal_places=2)
ZERO = models.Value(Decimal("0.00"), output_field=DEC)

IMEI_VALIDATOR = RegexValidator(
    r"^\d{14,17}$", "IMEI yalnızca rakamlardan oluşmalı ve 14-17 hane olmalıdır."
)


# ===========================================================================
# Yardımcı tablolar
# ===========================================================================

class Counter(models.Model):
    """Stok kodu / fiş no sayacı. Yalnızca utils.next_code() tarafından yazılır."""

    key = models.CharField(max_length=20, primary_key=True)
    value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Sayaç"
        verbose_name_plural = "Sayaçlar"

    def __str__(self):
        return f"{self.key}={self.value}"


class DeviceModel(models.Model):
    """Marka -> Model kataloğu.

    Model adı serbest metin olsaydı "iPhone 13 Pro", "iphone 13 pro" ve
    "İPHONE 13 PRO" üç ayrı ürün sayılır, "en çok satan model" raporu anlamsız
    olurdu. Bu tablonun tek varlık sebebi budur.
    """

    class Kind(models.TextChoices):
        TELEFON = "telefon", "Cep Telefonu"
        TABLET = "tablet", "Tablet"
        SAAT = "saat", "Akıllı Saat"
        DIGER = "diger", "Diğer"

    brand = models.ForeignKey("catalog.Brand", on_delete=models.PROTECT,
                              related_name="device_models", verbose_name="Marka")
    name = models.CharField("Model", max_length=120, help_text="Örn: iPhone 13 Pro")
    kind = models.CharField("Tür", max_length=10, choices=Kind.choices,
                            default=Kind.TELEFON, db_index=True)
    is_active = models.BooleanField("Aktif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cihaz Modeli"
        verbose_name_plural = "Cihaz Modelleri"
        ordering = ["brand__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["brand", "name"],
                                    name="uniq_devicemodel_brand_name"),
        ]
        indexes = [models.Index(fields=["name"])]

    def __str__(self):
        return f"{self.brand.name} {self.name}"


class AccessoryCategory(models.Model):
    name = models.CharField("Kategori", max_length=80, unique=True)
    order = models.PositiveIntegerField("Sıra", default=0)

    class Meta:
        verbose_name = "Aksesuar Kategorisi"
        verbose_name_plural = "Aksesuar Kategorileri"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Contact(models.Model):
    """Cari — müşteri ve tedarikçi aynı tabloda.

    Aynı kişi hem cihaz satın alan hem de takasla cihaz veren olabilir; iki
    ayrı tablo aynı insanı iki kez kaydettirir ve geçmiş sorgulanamaz hale
    gelir.
    """

    full_name = models.CharField("Ad Soyad / Ünvan", max_length=160)
    phone = models.CharField("Telefon", max_length=40, blank=True, default="")
    phone_norm = models.CharField(max_length=20, blank=True, default="",
                                  editable=False, db_index=True)
    email = models.EmailField("E-posta", blank=True, default="")
    tax_no = models.CharField("TCKN / VKN", max_length=20, blank=True, default="")
    company = models.CharField("Firma", max_length=160, blank=True, default="")
    address = models.CharField("Adres", max_length=255, blank=True, default="")
    is_customer = models.BooleanField("Müşteri", default=True)
    is_supplier = models.BooleanField("Tedarikçi", default=False)
    note = models.TextField("Not", blank=True, default="")
    search_blob = models.CharField(max_length=400, blank=True, default="",
                                   editable=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cari"
        verbose_name_plural = "Cariler"
        ordering = ["full_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_customer=True) | Q(is_supplier=True),
                name="contact_has_role",
            ),
        ]
        indexes = [
            models.Index(fields=["full_name"]),
            models.Index(fields=["phone_norm"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.company})" if self.company else self.full_name

    def save(self, *args, **kwargs):
        # Telefon normalizasyonu için apps.leads'teki mevcut yardımcı kullanılır
        # — ikinci bir normalizer yazılmaz.
        from apps.leads.utils import normalize_tr

        self.phone_norm = normalize_tr(self.phone)[:20]
        self.search_blob = trfold(
            " ".join(filter(None, [self.full_name, self.company, self.phone,
                                   self.phone_norm, self.tax_no]))
        )[:400]
        super().save(*args, **kwargs)

    @property
    def role_label(self):
        if self.is_customer and self.is_supplier:
            return "Müşteri + Tedarikçi"
        return "Tedarikçi" if self.is_supplier else "Müşteri"


# ===========================================================================
# Cihaz (seri takipli)
# ===========================================================================

class Device(models.Model):
    class Condition(models.TextChoices):
        SIFIR = "sifir", "Sıfır"
        IKINCI_EL = "ikinci_el", "İkinci El"

    class Status(models.TextChoices):
        STOKTA = "stokta", "Stokta"
        REZERVE = "rezerve", "Rezerve"
        SATILDI = "satildi", "Satıldı"
        IADE = "iade", "İade"
        SERVISTE = "serviste", "Serviste"
        KAYIP = "kayip", "Kayıp / Fire"

    WARRANTY_PRESETS = [0, 3, 6, 12, 18, 24, 36]

    class Acquisition(models.TextChoices):
        ALIM = "alim", "Satın Alım"
        TAKAS = "takas", "Takas"
        IADE = "iade", "Müşteri İadesi"

    # --- kimlik ---
    stock_code = models.CharField("Stok Kodu", max_length=20, unique=True,
                                  editable=False, blank=True)
    device_model = models.ForeignKey(DeviceModel, on_delete=models.PROTECT,
                                     related_name="devices", verbose_name="Model")
    condition = models.CharField("Durum", max_length=10, choices=Condition.choices,
                                 default=Condition.IKINCI_EL)
    status = models.CharField("Stok Durumu", max_length=10, choices=Status.choices,
                              default=Status.STOKTA, db_index=True)

    imei1 = models.CharField("IMEI 1", max_length=20, blank=True, default="")
    imei2 = models.CharField("IMEI 2", max_length=20, blank=True, default="")
    serial_no = models.CharField("Seri No", max_length=40, blank=True, default="")

    # --- fiziksel özellikler ---
    color = models.CharField("Renk", max_length=40, blank=True, default="")
    storage = models.CharField("Hafıza", max_length=40, blank=True, default="",
                               help_text="Örn: 256GB")
    battery_health = models.PositiveSmallIntegerField(
        "Pil Sağlığı (%)", null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    has_box = models.BooleanField("Kutulu", default=False)
    has_invoice = models.BooleanField("Faturalı", default=False)
    defect_note = models.TextField("Hasar / Arıza Notu", blank=True, default="")
    shelf = models.CharField("Raf / Konum", max_length=40, blank=True, default="",
                             db_index=True)

    # --- alış ---
    supplier = models.ForeignKey(Contact, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="supplied_devices",
                                 verbose_name="Alındığı Kişi / Firma")
    purchase_date = models.DateField("Alış Tarihi", default=timezone.localdate)
    purchase_price = models.DecimalField("Alış Fiyatı (₺)", default=0, **MONEY)
    acquisition = models.CharField("Giriş Şekli", max_length=8,
                                   choices=Acquisition.choices, default=Acquisition.ALIM)

    # --- satış (Sale'den denormalize; en sık açılan ekranda join'i kaldırır) ---
    list_price = models.DecimalField("Etiket Satış Fiyatı (₺)", null=True, blank=True,
                                     **MONEY)
    sold_to = models.ForeignKey(Contact, on_delete=models.PROTECT, null=True, blank=True,
                                related_name="bought_devices", verbose_name="Satılan Kişi")
    sold_at = models.DateField("Satış Tarihi", null=True, blank=True)
    sold_price = models.DecimalField("Satış Bedeli (₺)", null=True, blank=True, **MONEY)
    days_in_stock = models.PositiveIntegerField("Stokta Kalan Gün", null=True, blank=True,
                                                editable=False)

    # --- garanti ---
    warranty_months = models.PositiveSmallIntegerField(
        "Garanti Süresi (ay)", default=0,
        validators=[MaxValueValidator(120)],
        help_text="Kalan garanti ay olarak. Üreticinin devreden garantisi için "
                  "17, 22, 23 gibi ara değerler de girilebilir.",
    )
    warranty_start = models.DateField(
        "Garanti Başlangıcı", null=True, blank=True,
        help_text="İkinci elde üreticinin kalan garantisi devrediliyorsa cihazın "
                  "ilk satın alma tarihi; boş bırakılırsa satışta bugün atanır.",
    )
    warranty_end = models.DateField("Garanti Bitişi", null=True, blank=True,
                                    editable=False)

    # --- site vitrini ---
    published_product = models.OneToOneField(
        "catalog.Product", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="source_device", verbose_name="Sitedeki İlan",
    )

    search_blob = models.CharField(max_length=500, blank=True, default="",
                                   editable=False, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cihaz"
        verbose_name_plural = "Cihazlar"
        ordering = ["-created_at", "-id"]
        constraints = [
            # "Doluysa tekil" kalıbı: CharField null kalmadan (Django konvansiyonu)
            # kısmi indeksle tekillik sağlanır. unique=True + null=True kombinasyonu
            # her yerde None kontrolü doğurur ve form round-trip'ini bozar.
            models.UniqueConstraint(fields=["imei1"], condition=~Q(imei1=""),
                                    name="uniq_device_imei1"),
            models.UniqueConstraint(fields=["imei2"], condition=~Q(imei2=""),
                                    name="uniq_device_imei2"),
            models.UniqueConstraint(fields=["serial_no"], condition=~Q(serial_no=""),
                                    name="uniq_device_serial"),
            models.CheckConstraint(condition=Q(purchase_price__gte=0),
                                   name="device_cost_nonneg"),
        ]
        indexes = [
            models.Index(fields=["status", "purchase_date"]),
            models.Index(fields=["status", "device_model"]),
            models.Index(fields=["sold_at"]),
            models.Index(fields=["warranty_end"]),
            models.Index(fields=["stock_code"]),
            models.Index(fields=["imei1"]),
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return f"{self.stock_code} · {self.label}"

    # ------------------------------------------------------------------
    # Türetilmiş alanlar
    # ------------------------------------------------------------------
    @transaction.atomic
    def save(self, *args, **kwargs):
        self.imei1 = digits_only(self.imei1)
        self.imei2 = digits_only(self.imei2)
        if not self.stock_code:
            self.stock_code = next_code("device", "BYC")
        self.warranty_end = add_months(self.warranty_start, self.warranty_months)
        self.search_blob = trfold(" ".join(filter(None, [
            self.stock_code, self.imei1, self.imei2, self.serial_no,
            str(self.device_model) if self.device_model_id else "",
            self.color, self.storage, self.shelf,
        ])))[:500]
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        imei1, imei2 = digits_only(self.imei1), digits_only(self.imei2)
        for value, field in ((imei1, "imei1"), (imei2, "imei2")):
            if value:
                IMEI_VALIDATOR(value)
        if imei1 and imei1 == imei2:
            raise ValidationError({"imei2": "IMEI 2, IMEI 1 ile aynı olamaz."})
        # Çapraz sütun kontrolü: bir cihazın IMEI 2'si başka bir cihazın IMEI 1'i
        # olamaz. Hiçbir DB ifadesi bunu yapamadığı için tek koruma burasıdır —
        # dolayısıyla toplu içe aktarma da full_clean() çağırmak zorundadır.
        for value, field in ((imei1, "imei1"), (imei2, "imei2")):
            if not value:
                continue
            clash = (Device.objects
                     .filter(Q(imei1=value) | Q(imei2=value))
                     .exclude(pk=self.pk).first())
            if clash:
                raise ValidationError({
                    field: f"Bu IMEI zaten {clash.stock_code} kaydında kayıtlı.",
                })

    # ------------------------------------------------------------------
    # Hesaplanan değerler — hiçbiri saklanmaz
    # ------------------------------------------------------------------
    @property
    def label(self):
        parts = [str(self.device_model), self.storage, self.color]
        return " ".join(p for p in parts if p)

    @property
    def total_expense(self):
        return money(self.expenses.aggregate(t=Coalesce(Sum("amount"), ZERO))["t"])

    @property
    def cost_basis(self):
        """Gerçek maliyet: alış + cihaza yazılmış tamir/parça giderleri."""
        return self.purchase_price + self.total_expense

    @property
    def gross_profit(self):
        if self.sold_price is None:
            return None
        return self.sold_price - self.purchase_price

    @property
    def net_profit(self):
        """Giderler düşülmüş kâr. Saklanmaz — ilk tamir faturasında bayatlardı."""
        if self.sold_price is None:
            return None
        return self.sold_price - self.cost_basis

    @property
    def profit_margin(self):
        if not self.sold_price:
            return None
        return (self.net_profit / self.sold_price) * 100

    @property
    def warranty_label(self):
        return f"{self.warranty_months} Ay" if self.warranty_months else "Garantisiz"

    @property
    def warranty_days_left(self):
        if not self.warranty_end:
            return None
        return (self.warranty_end - timezone.localdate()).days

    @property
    def is_available(self):
        return self.status in (self.Status.STOKTA, self.Status.REZERVE)

    @property
    def age_in_days(self):
        """Stokta bekleme süresi; satılmışsa dondurulmuş değer döner."""
        if self.days_in_stock is not None:
            return self.days_in_stock
        return (timezone.localdate() - self.purchase_date).days


# Durum geçiş grafiği. YALNIZCA services.set_device_status() uygular —
# save() içinde uygulamak fixture/loaddata/migration/admin toplu işlemlerini kırar
# ve eski değeri ucuza göremez.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Device.Status.STOKTA: {Device.Status.REZERVE, Device.Status.SATILDI,
                           Device.Status.SERVISTE, Device.Status.KAYIP},
    Device.Status.REZERVE: {Device.Status.STOKTA, Device.Status.SATILDI},
    Device.Status.SATILDI: {Device.Status.IADE},
    Device.Status.IADE: {Device.Status.STOKTA, Device.Status.SERVISTE},
    Device.Status.SERVISTE: {Device.Status.STOKTA, Device.Status.KAYIP},
    Device.Status.KAYIP: set(),
}


class DeviceStatusLog(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE,
                               related_name="status_logs")
    from_status = models.CharField(max_length=10, blank=True, default="")
    to_status = models.CharField(max_length=10)
    sale = models.ForeignKey("Sale", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="+")
    note = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cihaz Durum Kaydı"
        verbose_name_plural = "Cihaz Durum Kayıtları"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["device", "created_at"])]

    def __str__(self):
        return f"{self.device_id}: {self.from_status} -> {self.to_status}"


# ===========================================================================
# Aksesuar (adet takipli)
# ===========================================================================

class Accessory(models.Model):
    sku = models.CharField("Stok Kodu", max_length=20, unique=True, editable=False,
                           blank=True)
    barcode = models.CharField("Barkod", max_length=64, blank=True, default="",
                               help_text="Üretici EAN-13 barkodu. Yoksa boş bırakın; "
                                         "stok kodu ile etiket basılabilir.")
    brand = models.ForeignKey("catalog.Brand", on_delete=models.PROTECT, null=True,
                              blank=True, related_name="accessories",
                              verbose_name="Marka")
    category = models.ForeignKey(AccessoryCategory, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name="accessories",
                                 verbose_name="Kategori")
    name = models.CharField("Ürün Adı", max_length=160)
    variant = models.CharField("Model / Varyant", max_length=120, blank=True, default="")

    cost = models.DecimalField("Alış Fiyatı (₺)", default=0, **MONEY)
    price = models.DecimalField("Satış Fiyatı (₺)", default=0, **MONEY)

    # Hareket defterinin (StockMovement) önbelleği. editable=False olduğu için
    # hiçbir ModelForm dokunamaz; tek yazarı services._resync_accessory_qty().
    stock_qty = models.IntegerField("Stok Adedi", default=0, editable=False)
    min_stock_level = models.PositiveIntegerField("Kritik Stok Seviyesi", default=2)

    note = models.TextField("Not", blank=True, default="")
    is_active = models.BooleanField("Aktif", default=True)
    search_blob = models.CharField(max_length=400, blank=True, default="",
                                   editable=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Aksesuar"
        verbose_name_plural = "Aksesuarlar"
        ordering = ["name", "variant"]
        constraints = [
            models.UniqueConstraint(fields=["barcode"], condition=~Q(barcode=""),
                                    name="uniq_accessory_barcode"),
            models.CheckConstraint(condition=Q(cost__gte=0) & Q(price__gte=0),
                                   name="accessory_prices_nonneg"),
        ]
        indexes = [
            models.Index(fields=["is_active", "stock_qty"]),
            models.Index(fields=["name"]),
            models.Index(fields=["barcode"]),
        ]

    def __str__(self):
        return f"{self.name} {self.variant}".strip()

    @transaction.atomic
    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = next_code("accessory", "BYC-A")
        self.search_blob = trfold(" ".join(filter(None, [
            self.sku, self.barcode, self.name, self.variant,
            self.brand.name if self.brand_id else "",
            self.category.name if self.category_id else "",
        ])))[:400]
        super().save(*args, **kwargs)

    @property
    def is_low_stock(self):
        return self.is_active and self.stock_qty <= self.min_stock_level

    @property
    def stock_value(self):
        return max(self.stock_qty, 0) * self.cost

    @property
    def unit_profit(self):
        return self.price - self.cost


class StockMovement(models.Model):
    """Aksesuar stok defteri — yalnızca ekleme yapılır, asla düzeltilmez.

    "Neden 3 yazıyor, ben 10 almıştım" tartışması bu tablo olmadan
    cevaplanamaz. Bir hareket düzenlenebilir hale gelirse defter stock_qty'yi
    açıklamayı bırakır ve tasarımın tüm denetim değeri kaybolur.
    """

    class Reason(models.TextChoices):
        ACILIS = "acilis", "Açılış Stoğu"
        GIRIS = "giris", "Mal Girişi"
        SATIS = "satis", "Satış"
        IADE = "iade", "İade"
        SAYIM = "sayim", "Sayım Düzeltmesi"
        FIRE = "fire", "Fire / Kayıp"

    accessory = models.ForeignKey(Accessory, on_delete=models.PROTECT,
                                  related_name="movements")
    quantity = models.IntegerField("Miktar", help_text="Giriş +, çıkış −")
    reason = models.CharField("Sebep", max_length=8, choices=Reason.choices,
                              db_index=True)
    unit_cost = models.DecimalField("Birim Alış (₺)", null=True, blank=True, **MONEY)
    sale_item = models.ForeignKey("SaleItem", on_delete=models.SET_NULL, null=True,
                                  blank=True, related_name="movements")
    balance_after = models.IntegerField(editable=False)
    note = models.CharField("Not", max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Stok Hareketi"
        verbose_name_plural = "Stok Hareketleri"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=~Q(quantity=0), name="movement_qty_nonzero"),
        ]
        indexes = [
            models.Index(fields=["accessory", "created_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.accessory_id} {self.quantity:+d} ({self.get_reason_display()})"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise ValueError(
                "Stok hareketi değiştirilemez. Düzeltme için yeni bir hareket yazın."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "Stok hareketi silinemez. Düzeltme için ters yönde yeni bir hareket yazın."
        )


# ===========================================================================
# Satış
# ===========================================================================

class Sale(models.Model):
    """Fiş. Sepet oturumda (session) tutulur — taslak Sale satırı yaratılmaz.

    İKİ AYRI TOPLAM, İKİ AYRI AMAÇ — karıştırılmamalı:
      * grand_total   = Σ line_total (tüm satırlar). Basılan fişin üzerindeki
                        rakam. CİRO KPI'ı BUNU OKUMAZ.
      * payable_total = Σ line_total (iade edilmemiş) − trade_in_total.
                        Müşteriden tahsil edilecek nakit.
    Ciro raporu doğrudan SaleItem.line_total üzerinden toplanır; böylece takas
    ve iadeler ciroyu bozmaz.
    """

    class Status(models.TextChoices):
        TAMAMLANDI = "tamam", "Tamamlandı"
        IPTAL = "iptal", "İptal"

    receipt_no = models.CharField("Fiş No", max_length=20, blank=True, default="",
                                  editable=False)
    customer = models.ForeignKey(Contact, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="sales", verbose_name="Müşteri")
    status = models.CharField("Durum", max_length=8, choices=Status.choices,
                              default=Status.TAMAMLANDI, db_index=True)
    sold_at = models.DateTimeField("Satış Zamanı", default=timezone.now)
    due_date = models.DateField("Vade Tarihi", null=True, blank=True)
    note = models.TextField("Not", blank=True, default="")

    grand_total = models.DecimalField("Fiş Tutarı (₺)", max_digits=14, decimal_places=2,
                                      default=0, editable=False)
    trade_in_total = models.DecimalField("Takas Tutarı (₺)", max_digits=14,
                                         decimal_places=2, default=0, editable=False)
    payable_total = models.DecimalField("Tahsil Edilecek (₺)", max_digits=14,
                                        decimal_places=2, default=0, editable=False)
    paid_total = models.DecimalField("Tahsil Edilen (₺)", max_digits=14,
                                     decimal_places=2, default=0, editable=False)

    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                null=True, blank=True, related_name="sales",
                                verbose_name="Satışı Yapan")
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name="+")
    void_reason = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Satış"
        verbose_name_plural = "Satışlar"
        ordering = ["-sold_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["receipt_no"], condition=~Q(receipt_no=""),
                                    name="uniq_sale_receipt"),
        ]
        indexes = [
            models.Index(fields=["status", "sold_at"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["customer", "status"]),
        ]
        permissions = [
            ("view_money", "Maliyet, kâr ve ciro bilgilerini görebilir"),
            ("manage_stock", "Stok girişi/düzenlemesi yapabilir"),
        ]

    def __str__(self):
        return self.receipt_no or f"Satış #{self.pk}"

    # ------------------------------------------------------------------
    def recalculate(self, commit=True):
        """Dört toplamı da kaynak satırlardan YENİDEN toplar.

        Asla artırımlı (+=) çalışmaz. Bu sayede her önbellek kendi kendini
        onarır ve "bir yerde azaltmayı kaçırdık" hata sınıfı tamamen ortadan
        kalkar; repair_stock_totals komutu da bu metodu çağırmaktan ibarettir.
        """
        totals = self.items.aggregate(
            grand=Coalesce(Sum("line_total"), ZERO),
            active=Coalesce(Sum("line_total", filter=Q(returned_at__isnull=True)), ZERO),
        )
        trade_in = self.trade_ins.aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]
        paid = self.payments.aggregate(t=Coalesce(Sum(Case(
            When(kind=Payment.Kind.IADE, then=-F("amount")),
            default=F("amount"), output_field=DEC,
        )), ZERO))["t"]

        # money() zorunlu: SQLite aggregate sonucu kuruşa yuvarlanmadan gelir
        # ve yuvarlanmazsa 18902.7000000000 gibi bir değer şablona sızar.
        self.grand_total = money(totals["grand"])
        self.trade_in_total = money(trade_in)
        self.payable_total = money(totals["active"]) - money(trade_in)
        self.paid_total = money(paid)
        if commit:
            self.save(update_fields=["grand_total", "trade_in_total",
                                     "payable_total", "paid_total", "updated_at"])
        return self

    @property
    def balance(self):
        """Kalan borç. Negatifse mağaza müşteriye para borçludur."""
        return self.payable_total - self.paid_total

    @property
    def is_credit(self):
        return self.balance > 0

    @property
    def is_overdue(self):
        return bool(self.is_credit and self.due_date
                    and self.due_date < timezone.localdate())

    @property
    def line_cost_total(self):
        return money(self.items.filter(returned_at__isnull=True).aggregate(
            t=Coalesce(Sum("line_cost"), ZERO))["t"])

    @property
    def gross_profit(self):
        active = self.items.filter(returned_at__isnull=True).aggregate(
            revenue=Coalesce(Sum("line_total"), ZERO),
            cost=Coalesce(Sum("line_cost"), ZERO),
        )
        return money(active["revenue"]) - money(active["cost"])


class SaleItem(models.Model):
    """Fiş satırı — ya bir cihaza ya bir aksesuara işaret eder.

    İki nullable FK + CheckConstraint tercih edildi. GenericForeignKey
    select_related'ı ve "en çok satan model" sorgusunu imkânsız kılardı; ayrı
    iki satır tablosu ise her raporu ikiye bölerdi. Asıl kazanç aşağıdaki
    kısmi tekil indeks: veritabanının kendisi bir fiziksel telefonun iki kez
    satılmasını reddeder.
    """

    class Kind(models.TextChoices):
        CIHAZ = "cihaz", "Cihaz"
        AKSESUAR = "aksesuar", "Aksesuar"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField("Tür", max_length=8, choices=Kind.choices)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, null=True, blank=True,
                               related_name="sale_items")
    accessory = models.ForeignKey(Accessory, on_delete=models.PROTECT, null=True,
                                  blank=True, related_name="sale_items")

    # --- anlık görüntüler: ürün sonradan düzenlense de fiş değişmez ---
    item_name = models.CharField("Ürün", max_length=200)
    item_code = models.CharField("Kod", max_length=64, blank=True, default="")
    item_imei = models.CharField("IMEI", max_length=20, blank=True, default="")
    quantity = models.PositiveIntegerField("Adet", default=1)
    unit_price = models.DecimalField("Birim Fiyat (₺)", **MONEY)
    unit_cost = models.DecimalField("Birim Maliyet (₺)", default=0, **MONEY)
    line_discount = models.DecimalField("İndirim (₺)", default=0, **MONEY)
    vat_rate = models.DecimalField("KDV %", max_digits=5, decimal_places=2,
                                   default=Decimal("20.00"))

    line_total = models.GeneratedField(
        expression=F("quantity") * F("unit_price") - F("line_discount"),
        output_field=models.DecimalField(max_digits=14, decimal_places=2),
        db_persist=True, verbose_name="Satır Tutarı",
    )
    line_cost = models.GeneratedField(
        expression=F("quantity") * F("unit_cost"),
        output_field=models.DecimalField(max_digits=14, decimal_places=2),
        db_persist=True, verbose_name="Satır Maliyeti",
    )

    returned_at = models.DateTimeField("İade Zamanı", null=True, blank=True)
    return_reason = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Satış Kalemi"
        verbose_name_plural = "Satış Kalemleri"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="cihaz", device__isnull=False, accessory__isnull=True)
                    | Q(kind="aksesuar", device__isnull=True, accessory__isnull=False)
                ),
                name="saleitem_target_matches_kind",
            ),
            models.CheckConstraint(condition=Q(kind="aksesuar") | Q(quantity=1),
                                   name="saleitem_device_qty_one"),
            models.CheckConstraint(condition=Q(quantity__gt=0),
                                   name="saleitem_qty_positive"),
            models.CheckConstraint(condition=Q(line_discount__gte=0),
                                   name="saleitem_discount_nonneg"),
            # Bir cihazın aynı anda en fazla BİR aktif satırı olabilir.
            # İade edilen satır returned_at aldığı için cihaz otomatik olarak
            # yeniden satılabilir hale gelir.
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(device__isnull=False, returned_at__isnull=True),
                name="uniq_active_device_line",
            ),
        ]
        indexes = [
            models.Index(fields=["sale", "kind"]),
            models.Index(fields=["kind", "returned_at"]),
            models.Index(fields=["returned_at"]),
        ]

    def __str__(self):
        return f"{self.item_name} × {self.quantity}"

    @property
    def line_profit(self):
        return (self.line_total or 0) - (self.line_cost or 0)

    @property
    def is_returned(self):
        return self.returned_at is not None


class TradeIn(models.Model):
    """Takas — indirim DEĞİL, ayni ödemeyle kapatılmış bir alım.

    40.000 ₺ telefon + 15.000 ₺ takas + 25.000 ₺ nakit örneğinde:
      ciro 40.000 (satır toplamı), tahsil edilecek 25.000 (payable_total),
      envantere giren cihazın maliyeti 15.000.
    Negatif satır kalemi kullanılsaydı ciro 25.000 görünür ve kâr 25.000'e
    bölündüğü için marj yapay olarak şişerdi.
    """

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="trade_ins")
    device = models.OneToOneField(Device, on_delete=models.PROTECT,
                                  related_name="trade_in", verbose_name="Alınan Cihaz")
    amount = models.DecimalField("Takas Bedeli (₺)", **MONEY)
    note = models.CharField("Not", max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Takas"
        verbose_name_plural = "Takaslar"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0),
                                   name="tradein_amount_nonneg"),
        ]

    def __str__(self):
        return f"{self.device.stock_code} takas {self.amount} ₺"


class Payment(models.Model):
    """Tahsilat/iade hareketi.

    paid_amount alanı yerine ayrı tablo: "bugün kasaya ne girdi?" sorusu bir
    alanla cevaplanamaz, veresiye doğası gereği çok olaylıdır (2 ayda 3 ödeme,
    her biri farklı yöntemle) ve iade, orijinal tahsilat kaydını silmeden
    işaretli bir nakit olayı gerektirir.
    """

    class Kind(models.TextChoices):
        TAHSILAT = "tahsilat", "Tahsilat"
        IADE = "iade", "İade / Geri Ödeme"

    class Method(models.TextChoices):
        NAKIT = "nakit", "Nakit"
        KART = "kart", "Kredi Kartı"
        HAVALE = "havale", "Havale / EFT"
        DIGER = "diger", "Diğer"

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField("Tür", max_length=10, choices=Kind.choices,
                            default=Kind.TAHSILAT)
    method = models.CharField("Ödeme Şekli", max_length=10, choices=Method.choices,
                              default=Method.NAKIT)
    amount = models.DecimalField("Tutar (₺)", **MONEY)
    paid_at = models.DateTimeField("Ödeme Zamanı", default=timezone.now)
    note = models.CharField("Not", max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ödeme"
        verbose_name_plural = "Ödemeler"
        ordering = ["-paid_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0),
                                   name="payment_amount_positive"),
        ]
        indexes = [
            models.Index(fields=["sale", "paid_at"]),
            models.Index(fields=["paid_at", "method"]),
            models.Index(fields=["kind", "paid_at"]),
        ]

    def __str__(self):
        sign = "-" if self.kind == self.Kind.IADE else "+"
        return f"{sign}{self.amount} ₺ ({self.get_method_display()})"

    @property
    def signed_amount(self):
        return -self.amount if self.kind == self.Kind.IADE else self.amount


class Expense(models.Model):
    """Gider. device doluysa cihaza ait tamir/parça, boşsa genel işletme gideri."""

    class Kind(models.TextChoices):
        PARCA = "parca", "Parça"
        ISCILIK = "iscilik", "İşçilik / Servis"
        NAKLIYE = "nakliye", "Kargo / Nakliye"
        KIRA = "kira", "Kira"
        FATURA = "fatura", "Elektrik / Su / İnternet"
        MAAS = "maas", "Maaş"
        VERGI = "vergi", "Vergi / Resmi"
        DIGER = "diger", "Diğer"

    #: Bir cihaza bağlanabilecek gider türleri. "Kira" bir telefona yazılırsa
    #: o cihazın marjı sessizce bozulur; bunu DB kısıtı engeller.
    DEVICE_KINDS = [Kind.PARCA, Kind.ISCILIK, Kind.NAKLIYE, Kind.DIGER]

    device = models.ForeignKey(Device, on_delete=models.PROTECT, null=True, blank=True,
                               related_name="expenses", verbose_name="İlgili Cihaz")
    kind = models.CharField("Gider Türü", max_length=10, choices=Kind.choices)
    title = models.CharField("Açıklama", max_length=160)
    amount = models.DecimalField("Tutar (₺)", **MONEY)
    spent_on = models.DateField("Tarih", default=timezone.localdate)
    supplier = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="expenses", verbose_name="Ödenen Yer")
    note = models.TextField("Not", blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gider"
        verbose_name_plural = "Giderler"
        ordering = ["-spent_on", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0),
                                   name="expense_amount_positive"),
            models.CheckConstraint(
                condition=Q(device__isnull=True)
                | Q(kind__in=["parca", "iscilik", "nakliye", "diger"]),
                name="expense_device_kind_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["device", "spent_on"]),
            models.Index(fields=["spent_on", "kind"]),
            models.Index(fields=["kind"]),
        ]

    def __str__(self):
        return f"{self.title} — {self.amount} ₺"
