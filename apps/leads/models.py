from django.db import models


class QuoteRequest(models.Model):
    """Teklif Al modülünden gelen talepler (iki mod: telefonunu sat / fiyat teklifi al)."""

    class Kind(models.TextChoices):
        SAT = "sat", "Telefonunu Sat / Takas"
        AL = "al", "Fiyat Teklifi Al"

    kind = models.CharField("Tür", max_length=4, choices=Kind.choices, default=Kind.SAT)

    name = models.CharField("Ad Soyad", max_length=120)
    phone = models.CharField("Telefon", max_length=40)

    brand = models.CharField("Marka", max_length=80, blank=True)
    model = models.CharField("Model", max_length=120, blank=True)
    year = models.CharField("Yıl", max_length=10, blank=True)
    storage = models.CharField("Hafıza", max_length=40, blank=True)
    condition = models.CharField("Durum", max_length=80, blank=True)
    note = models.TextField("Not / Ek Bilgi", blank=True)

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quote_requests", verbose_name="İlgili Ürün",
    )

    is_handled = models.BooleanField("İşleme Alındı", default=False)
    created_at = models.DateTimeField("Tarih", auto_now_add=True)

    class Meta:
        verbose_name = "Teklif Talebi"
        verbose_name_plural = "Teklif Talepleri"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.name}"


class ServiceRequest(models.Model):
    """Servis / tamir talepleri."""

    name = models.CharField("Ad Soyad", max_length=120)
    phone = models.CharField("Telefon", max_length=40)
    device = models.CharField("Cihaz", max_length=120)
    issue = models.CharField("Arıza", max_length=200)
    note = models.TextField("Ek Bilgi", blank=True)

    is_handled = models.BooleanField("İşleme Alındı", default=False)
    created_at = models.DateTimeField("Tarih", auto_now_add=True)

    class Meta:
        verbose_name = "Servis Talebi"
        verbose_name_plural = "Servis Talepleri"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.device} · {self.name}"


class ContactMessage(models.Model):
    """İletişim formu mesajları."""

    name = models.CharField("Ad Soyad", max_length=120)
    phone = models.CharField("Telefon", max_length=40, blank=True)
    email = models.EmailField("E-posta", blank=True)
    message = models.TextField("Mesaj")

    is_handled = models.BooleanField("Okundu", default=False)
    created_at = models.DateTimeField("Tarih", auto_now_add=True)

    class Meta:
        verbose_name = "İletişim Mesajı"
        verbose_name_plural = "İletişim Mesajları"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}"
