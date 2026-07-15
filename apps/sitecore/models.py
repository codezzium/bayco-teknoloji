from django.db import models


class SiteSettings(models.Model):
    """Site geneli ayarlar — tekil (singleton) kayıt. Panelden yönetilir."""

    brand_name = models.CharField("İşletme Adı", max_length=120, default="Bayço Teknoloji")
    tagline = models.CharField(
        "Slogan", max_length=200, blank=True,
        default="Telefon ve teknolojide güvenin adresi",
    )

    # İletişim
    phone = models.CharField("Telefon", max_length=40, default="0850 000 00 00")
    whatsapp_number = models.CharField(
        "WhatsApp Numarası", max_length=20, default="905000000000",
        help_text="Ülke koduyla, sadece rakam. Örn: 905321234567",
    )
    email = models.EmailField("E-posta", blank=True, default="info@baycoteknoloji.com")
    address = models.CharField("Adres", max_length=255, blank=True,
                               default="Merkez Mah. Teknoloji Cad. No:1, İstanbul")
    maps_embed = models.TextField(
        "Google Harita Embed URL", blank=True,
        help_text="Google Maps > Paylaş > Harita yerleştir > src bağlantısı",
    )
    working_hours = models.CharField("Çalışma Saatleri", max_length=120, blank=True,
                                     default="Hafta içi 09:00 - 20:00 · Cumartesi 10:00 - 18:00")

    # Hero
    hero_title = models.CharField("Hero Başlık", max_length=160,
                                  default="Yeni ve İkinci El Telefonda Doğru Adres")
    hero_subtitle = models.CharField(
        "Hero Alt Metin", max_length=300, blank=True,
        default="Sıfır ve garantili ikinci el telefonlar, aksesuarlar ve profesyonel "
                "teknik servis. Telefonunu sat, takas et veya hemen fiyat teklifi al.",
    )
    hero_bg = models.ImageField("Hero Arka Plan (mağaza fotoğrafı)",
                                upload_to="site/", blank=True, null=True)
    hero_cta_text = models.CharField("Hero Buton Metni", max_length=40, default="Teklif Al")

    # Kampanya şeridi
    campaign_active = models.BooleanField("Kampanya şeridi aktif", default=True)
    campaign_text = models.CharField(
        "Kampanya Metni", max_length=200, blank=True,
        default="🎉 Tüm ikinci el telefonlarda 12 aya varan garanti · Ücretsiz kargo · Kapıda ödeme",
    )

    # Sosyal kanıt
    google_rating = models.DecimalField("Google Puanı", max_digits=2, decimal_places=1, default=4.9)
    google_review_count = models.PositiveIntegerField("Yorum Sayısı", default=128)
    google_review_url = models.URLField("Google Yorum Linki", blank=True)

    # Footer
    footer_about = models.TextField(
        "Footer Açıklama", blank=True,
        default="Bayço Teknoloji; sıfır ve ikinci el telefon satışı, takas, aksesuar ve "
                "teknik servis alanında güvenilir çözüm ortağınız.",
    )

    # Sosyal medya
    instagram = models.URLField("Instagram", blank=True)
    facebook = models.URLField("Facebook", blank=True)
    tiktok = models.URLField("TikTok", blank=True)
    youtube = models.URLField("YouTube", blank=True)

    class Meta:
        verbose_name = "Site Ayarı"
        verbose_name_plural = "Site Ayarları"

    def __str__(self):
        return self.brand_name

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def whatsapp_link(self):
        return f"https://wa.me/{self.whatsapp_number}"


class Slider(models.Model):
    """Hero'daki cube swiper slaytları / duyuru görselleri."""

    title = models.CharField("Başlık", max_length=120)
    subtitle = models.CharField("Alt Başlık", max_length=200, blank=True)
    badge = models.CharField("Rozet", max_length=40, blank=True,
                             help_text="Örn: YENİ, KAMPANYA")
    image = models.ImageField("Görsel", upload_to="slider/", blank=True, null=True)
    link_url = models.CharField("Bağlantı (opsiyonel)", max_length=255, blank=True)
    order = models.PositiveIntegerField("Sıra", default=0)
    is_active = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Duyuru / Slayt"
        verbose_name_plural = "Duyurular / Slaytlar"
        ordering = ["order", "-id"]

    def __str__(self):
        return self.title


class Testimonial(models.Model):
    """Müşteri yorumları."""

    name = models.CharField("Ad Soyad", max_length=120)
    role = models.CharField("Ünvan / Şehir", max_length=120, blank=True)
    rating = models.PositiveSmallIntegerField("Puan (1-5)", default=5)
    comment = models.TextField("Yorum")
    avatar = models.ImageField("Fotoğraf", upload_to="testimonials/", blank=True, null=True)
    order = models.PositiveIntegerField("Sıra", default=0)
    is_active = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Müşteri Yorumu"
        verbose_name_plural = "Müşteri Yorumları"
        ordering = ["order", "-id"]

    def __str__(self):
        return f"{self.name} ({self.rating}★)"

    @property
    def stars(self):
        return range(self.rating)

    @property
    def empty_stars(self):
        return range(5 - self.rating)


class FAQ(models.Model):
    """Sık sorulan sorular."""

    question = models.CharField("Soru", max_length=200)
    answer = models.TextField("Cevap")
    order = models.PositiveIntegerField("Sıra", default=0)
    is_active = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Sık Sorulan Soru"
        verbose_name_plural = "Sık Sorulan Sorular"
        ordering = ["order", "-id"]

    def __str__(self):
        return self.question
