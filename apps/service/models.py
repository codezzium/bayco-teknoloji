"""Teknik servis veri modeli.

Servise gelen cihaz MÜŞTERİNİNDİR: stoğa girmez, Device tablosuna yazılmaz.
Müşteri ve model kataloğu stok modülünden gelir (Contact, DeviceModel) —
aynı kişi hem telefon alıp hem tamire getirebilir, ikinci bir müşteri tablosu
geçmişi böler.

PARA İKİ AYRI DEFTERDE:
  * Müşteri tarafı: final_price (kesin ücret) ve ServicePayment (kapora,
    tahsilat, iade). paid_total bunların önbelleğidir.
  * Maliyet tarafı: ServiceCost (iç parça/işçilik) ve ServiceOutsource.cost
    (teknik servise borç). Teknik servis borcu RepairShopPayment ile kapanır.
Servis kârı mağaza satış kârına KARIŞTIRILMAZ (apps/service/reports.py).

Mutasyon kuralı stok modülüyle aynıdır: durum, ödeme toplamı ve teknik servis
işleri YALNIZCA apps/service/services.py içinden değiştirilir.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Case, F, Q, Sum, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.stock.models import DEC, MONEY, ZERO, Contact, DeviceModel, Payment
from apps.stock.utils import digits_only, money, next_code, trfold

#: Desen ızgarası (telefon kilit ekranı gibi):
#:   1 2 3
#:   4 5 6
#:   7 8 9
PATTERN_MIN_POINTS = 4


def parse_pattern(value) -> list[int]:
    """"1-5-9-6" → [1, 5, 9, 6]. Geçersiz karakterler atılır."""
    return [int(ch) for ch in str(value or "") if ch in "123456789"]


def validate_pattern(value):
    points = parse_pattern(value)
    if not points:
        return
    if len(set(points)) != len(points):
        raise ValidationError("Desende aynı nokta iki kez kullanılamaz.")
    if len(points) < PATTERN_MIN_POINTS:
        raise ValidationError(f"Desen en az {PATTERN_MIN_POINTS} noktadan oluşmalı.")


class RepairShop(models.Model):
    """Teknik servis — cihazın dışarıda tamire verildiği yer (anlaşmalı dış servis).

    Arayüzde her yerde "Teknik Servis" denir; "tamirhane" kelimesi kullanılmaz
    (kullanıcı kaba buldu). Python adları (RepairShop, shop_*, outsource) iç adlardır.

    Cari (Contact) tablosuna konmadı: teknik servisin hesabı satış/alış
    bakiyesinden ayrı tutulur ve kendi ekstresi vardır.
    """

    name = models.CharField("Teknik Servis Adı", max_length=160)
    contact_name = models.CharField("Yetkili", max_length=120, blank=True, default="")
    phone = models.CharField("Telefon", max_length=40, blank=True, default="")
    address = models.CharField("Adres", max_length=255, blank=True, default="")
    iban = models.CharField("IBAN", max_length=40, blank=True, default="")
    note = models.TextField("Not", blank=True, default="")
    is_active = models.BooleanField("Aktif", default=True)
    search_blob = models.CharField(max_length=400, blank=True, default="",
                                   editable=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Teknik Servis"
        verbose_name_plural = "Teknik Servisler"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.search_blob = trfold(" ".join(filter(None, [
            self.name, self.contact_name, self.phone, digits_only(self.phone),
        ])))[:400]
        super().save(*args, **kwargs)


class ServiceTicket(models.Model):
    class Status(models.TextChoices):
        KABUL = "kabul", "Teslim Alındı"
        INCELEME = "inceleme", "Arıza Tespiti"
        ONAY = "onay", "Müşteri Onayı Bekleniyor"
        TAMIRDE = "tamirde", "Tamirde"
        DIS_SERVISTE = "dis_servis", "Teknik Serviste"
        HAZIR = "hazir", "Teslime Hazır"
        TESLIM = "teslim", "Teslim Edildi"
        IADE = "iade", "Tamirsiz İade"

    #: Elle seçilebilen açık durumlar. "Teknik Serviste" durumuna yalnızca teknik servise
    #: gönderme işlemiyle girilir; kapanış durumlarına yalnızca kapanış işlemiyle.
    MANUAL_STATUSES = [Status.KABUL, Status.INCELEME, Status.ONAY, Status.TAMIRDE,
                       Status.HAZIR]
    OPEN_STATUSES = MANUAL_STATUSES + [Status.DIS_SERVISTE]
    CLOSED_STATUSES = [Status.TESLIM, Status.IADE]

    RECEIVED_ITEMS = [
        ("sarj", "Şarj aleti"),
        ("kablo", "Kablo"),
        ("kutu", "Kutu"),
        ("kilif", "Kılıf"),
        ("sim", "SIM kart"),
        ("hafiza", "Hafıza kartı"),
        ("kalem", "Kalem"),
    ]

    ticket_no = models.CharField("Servis No", max_length=20, unique=True,
                                 editable=False, blank=True)
    customer = models.ForeignKey(Contact, on_delete=models.PROTECT,
                                 related_name="service_tickets", verbose_name="Müşteri")
    device_model = models.ForeignKey(DeviceModel, on_delete=models.PROTECT,
                                     related_name="service_tickets",
                                     verbose_name="Cihaz (Marka / Model)")
    imei = models.CharField("IMEI", max_length=20, blank=True, default="")
    serial_no = models.CharField("Seri No", max_length=40, blank=True, default="")
    color = models.CharField("Renk", max_length=40, blank=True, default="")

    # --- ekran kilidi: teslimde silinir (services.close_ticket) ---
    lock_pin = models.CharField("Ekran Parolası / PIN", max_length=40, blank=True,
                                default="")
    lock_pattern = models.CharField("Ekran Deseni", max_length=17, blank=True,
                                    default="", validators=[validate_pattern])

    received_items = models.JSONField("Teslim Alınan Aksesuarlar", default=list,
                                      blank=True)
    received_note = models.CharField("Diğer Aksesuar", max_length=200, blank=True,
                                     default="")
    condition_note = models.TextField("Fiziksel Durum", blank=True, default="",
                                      help_text="Çizik, kırık, ekran yanığı, sıvı teması…")
    complaint = models.TextField("Müşteri Şikâyeti / Arıza")
    diagnosis = models.TextField("Tespit / Yapılan İşlem", blank=True, default="")

    estimated_price = models.DecimalField("Tahmini Ücret (₺)", null=True, blank=True,
                                          **MONEY)
    final_price = models.DecimalField("Servis Ücreti (₺)", null=True, blank=True,
                                      help_text="Müşteriden alınacak kesin ücret.",
                                      **MONEY)
    estimated_ready = models.DateField("Tahmini Teslim", null=True, blank=True)

    status = models.CharField("Durum", max_length=10, choices=Status.choices,
                              default=Status.KABUL, db_index=True)
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+",
                                   verbose_name="Sorumlu")
    received_at = models.DateTimeField("Teslim Alınma", default=timezone.now)
    closed_at = models.DateTimeField("Kapanış", null=True, blank=True)

    # ServicePayment önbelleği; yalnızca recalculate() yazar.
    paid_total = models.DecimalField("Tahsil Edilen (₺)", max_digits=14,
                                     decimal_places=2, default=0, editable=False)

    note = models.TextField("İç Not", blank=True, default="",
                            help_text="Müşteriye basılan belgelerde görünmez.")
    search_blob = models.CharField(max_length=400, blank=True, default="",
                                   editable=False, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Servis Kaydı"
        verbose_name_plural = "Servis Kayıtları"
        ordering = ["-received_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(estimated_price__isnull=True) | Q(estimated_price__gte=0))
                & (Q(final_price__isnull=True) | Q(final_price__gte=0)),
                name="serviceticket_prices_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "received_at"]),
            models.Index(fields=["closed_at"]),
            models.Index(fields=["customer", "received_at"]),
        ]

    def __str__(self):
        return f"{self.ticket_no} · {self.device_label}" if self.ticket_no else "Servis"

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.imei = digits_only(self.imei)
        if not self.ticket_no:
            self.ticket_no = next_code("service", "SRV")
        # Müşteri adı burada TUTULMAZ: cari yeniden adlandırılınca bayatlardı.
        # Liste araması customer__search_blob'a ayrıca bakar.
        self.search_blob = trfold(" ".join(filter(None, [
            self.ticket_no, self.imei, self.serial_no, self.color,
            str(self.device_model) if self.device_model_id else "",
        ])))[:400]
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    def recalculate(self, commit=True):
        """Tahsilat önbelleğini kaynak satırlardan YENİDEN toplar (Sale ile aynı)."""
        paid = self.payments.aggregate(t=Coalesce(Sum(Case(
            When(kind=Payment.Kind.IADE, then=-F("amount")),
            default=F("amount"), output_field=DEC,
        )), ZERO))["t"]
        self.paid_total = money(paid)
        if commit:
            self.save(update_fields=["paid_total", "updated_at"])
        return self

    # ------------------------------------------------------------------
    @property
    def device_label(self):
        parts = [str(self.device_model) if self.device_model_id else "", self.color]
        return " ".join(p for p in parts if p)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_closed(self):
        return self.status in self.CLOSED_STATUSES

    @property
    def at_shop(self):
        return self.status == self.Status.DIS_SERVISTE

    @property
    def received_labels(self) -> list[str]:
        labels = dict(self.RECEIVED_ITEMS)
        items = [labels.get(key, key) for key in (self.received_items or [])]
        if self.received_note:
            items.append(self.received_note)
        return items

    @property
    def pattern_points(self) -> list[int]:
        return parse_pattern(self.lock_pattern)

    @property
    def has_lock(self):
        return bool(self.lock_pin or self.lock_pattern)

    @property
    def balance(self):
        """Kalan alacak; kesin ücret girilmemişse None."""
        if self.final_price is None:
            return None
        return self.final_price - self.paid_total

    @property
    def internal_cost(self) -> Decimal:
        return money(self.costs.aggregate(t=Coalesce(Sum("amount"), ZERO))["t"])

    @property
    def external_cost(self) -> Decimal:
        return money(self.outsources.filter(status=ServiceOutsource.Status.DONDU)
                     .aggregate(t=Coalesce(Sum("cost"), ZERO))["t"])

    @property
    def profit(self):
        if self.final_price is None:
            return None
        return self.final_price - self.internal_cost - self.external_cost


class ServiceStatusLog(models.Model):
    ticket = models.ForeignKey(ServiceTicket, on_delete=models.CASCADE,
                               related_name="status_logs")
    from_status = models.CharField(max_length=10, blank=True, default="")
    to_status = models.CharField(max_length=10)
    note = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Servis Durum Kaydı"
        verbose_name_plural = "Servis Durum Kayıtları"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.ticket_id}: {self.from_status} -> {self.to_status}"

    @property
    def to_label(self):
        return ServiceTicket.Status(self.to_status).label


class ServicePayment(models.Model):
    """Müşteriden servis tahsilatı (kapora dahil) ya da para iadesi."""

    ticket = models.ForeignKey(ServiceTicket, on_delete=models.PROTECT,
                               related_name="payments")
    kind = models.CharField("Tür", max_length=10, choices=Payment.Kind.choices,
                            default=Payment.Kind.TAHSILAT)
    method = models.CharField("Ödeme Şekli", max_length=10,
                              choices=Payment.Method.choices,
                              default=Payment.Method.NAKIT)
    amount = models.DecimalField("Tutar (₺)", **MONEY)
    paid_at = models.DateTimeField("Ödeme Zamanı", default=timezone.now)
    note = models.CharField("Not", max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Servis Ödemesi"
        verbose_name_plural = "Servis Ödemeleri"
        ordering = ["-paid_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0),
                                   name="servicepayment_amount_positive"),
        ]
        indexes = [models.Index(fields=["paid_at"])]

    def __str__(self):
        sign = "-" if self.kind == Payment.Kind.IADE else "+"
        return f"{sign}{self.amount} ₺ ({self.get_method_display()})"

    @property
    def signed_amount(self):
        return -self.amount if self.kind == Payment.Kind.IADE else self.amount


class ServiceCost(models.Model):
    """Servisin iç maliyeti: mağazanın kendi aldığı parça, kendi işçiliği."""

    class Kind(models.TextChoices):
        PARCA = "parca", "Parça"
        ISCILIK = "iscilik", "İşçilik"
        DIGER = "diger", "Diğer"

    ticket = models.ForeignKey(ServiceTicket, on_delete=models.CASCADE,
                               related_name="costs")
    kind = models.CharField("Tür", max_length=10, choices=Kind.choices,
                            default=Kind.PARCA)
    title = models.CharField("Açıklama", max_length=160)
    amount = models.DecimalField("Tutar (₺)", **MONEY)
    spent_on = models.DateField("Tarih", default=timezone.localdate)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Servis Maliyeti"
        verbose_name_plural = "Servis Maliyetleri"
        ordering = ["spent_on", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0),
                                   name="servicecost_amount_positive"),
        ]

    def __str__(self):
        return f"{self.title} — {self.amount} ₺"


class ServiceOutsource(models.Model):
    """Teknik servis işi: cihazın teknik servise gidişi ve dönüşü.

    Borç, cihaz DÖNDÜĞÜNDE yazılır (status=dondu). Gönderirken girilen bedel
    anlaşılan/tahmini bedeldir; dönüşte kesinleşir. İptal edilen iş borç
    yazmaz.
    """

    class Status(models.TextChoices):
        GONDERILDI = "gonderildi", "Teknik Serviste"
        DONDU = "dondu", "Döndü"
        IPTAL = "iptal", "İptal"

    ticket = models.ForeignKey(ServiceTicket, on_delete=models.PROTECT,
                               related_name="outsources", verbose_name="Servis Kaydı")
    shop = models.ForeignKey(RepairShop, on_delete=models.PROTECT,
                             related_name="jobs", verbose_name="Teknik Servis")
    work = models.CharField("Yapılacak İş", max_length=200)
    cost = models.DecimalField("Teknik Servis Bedeli (₺)", null=True, blank=True,
                               help_text="Teknik servise ödenecek tutar.", **MONEY)
    sent_at = models.DateField("Gönderim Tarihi", default=timezone.localdate)
    returned_at = models.DateField("Dönüş Tarihi", null=True, blank=True)
    status = models.CharField("Durum", max_length=10, choices=Status.choices,
                              default=Status.GONDERILDI, db_index=True)
    note = models.CharField("Not", max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Teknik Servis İşi"
        verbose_name_plural = "Teknik Servis İşleri"
        ordering = ["-sent_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(cost__isnull=True) | Q(cost__gte=0),
                                   name="serviceoutsource_cost_nonneg"),
            # Bir cihaz aynı anda yalnızca BİR teknik serviste olabilir.
            models.UniqueConstraint(fields=["ticket"], condition=Q(status="gonderildi"),
                                    name="uniq_active_outsource"),
        ]
        indexes = [models.Index(fields=["shop", "status"])]

    def __str__(self):
        return f"{self.ticket.ticket_no} → {self.shop}"


class RepairShopPayment(models.Model):
    """Teknik servise yapılan ödeme — teknik servis ekstresinin alacak tarafı."""

    shop = models.ForeignKey(RepairShop, on_delete=models.PROTECT,
                             related_name="payments", verbose_name="Teknik Servis")
    outsource = models.ForeignKey(ServiceOutsource, on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name="payments",
                                  verbose_name="İlgili İş")
    amount = models.DecimalField("Tutar (₺)", **MONEY)
    method = models.CharField("Ödeme Şekli", max_length=10,
                              choices=Payment.Method.choices,
                              default=Payment.Method.NAKIT)
    paid_at = models.DateField("Ödeme Tarihi", default=timezone.localdate)
    note = models.CharField("Not", max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Teknik Servis Ödemesi"
        verbose_name_plural = "Teknik Servis Ödemeleri"
        ordering = ["-paid_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0),
                                   name="repairshoppayment_amount_positive"),
        ]
        indexes = [models.Index(fields=["shop", "paid_at"])]

    def __str__(self):
        return f"{self.shop} ← {self.amount} ₺"
